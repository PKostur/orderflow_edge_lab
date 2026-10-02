"""Strategy families for strategy-zoo-v1 (config/strategy_zoo_v1.json), plus causal market-regime labels.

All books are daily: a signal uses data up to the open of day d, trades at that open and earns the
open(d) -> open(d+1) return. Returned series are keyed by d (the day the position is held).
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.xs_premia import daily_open_panel, run_xs

BTC = "BTC_USDT"


def daily_volume_panel(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Volume summed over each UTC day, stamped at that day's 00:00 (complete only after the day ends)."""
    return pd.DataFrame({s: f["volume"].astype(float).groupby(f.index.floor("D")).sum() for s, f in frames.items()}).sort_index()


def daily_returns(opens: pd.DataFrame) -> pd.DataFrame:
    """r at d = open(d) / open(d-1) - 1, known at the open of d."""
    return opens / opens.shift(1) - 1.0


def run_targets(targets: pd.DataFrame, opens: pd.DataFrame, fund: pd.DataFrame, *, cost_bps: float) -> pd.Series:
    """Daily target weights (decided at the open of d) -> net return over open(d) -> open(d+1)."""
    fwd = opens.shift(-1) / opens - 1.0
    w = pd.Series(0.0, index=opens.columns)
    out = {}
    for d in opens.index[:-1]:
        new = targets.loc[d].reindex(opens.columns).fillna(0.0) if d in targets.index else pd.Series(0.0, index=opens.columns)
        new = new.where(fwd.loc[d].notna(), 0.0)
        turn = float((new - w).abs().sum())
        r = fwd.loc[d].fillna(0.0)
        f = fund.loc[d].reindex(opens.columns).fillna(0.0) if d in fund.index else 0.0
        out[d] = float((new * r).sum() - (new * f).sum() - turn * cost_bps / 2 / 1e4)
        w = new * (1.0 + r)
    return pd.Series(out, dtype=float)


def _basket_weights(opens: pd.DataFrame, cols) -> pd.DataFrame:
    fwd_ok = (opens.shift(-1).notna() & opens.notna())[cols]
    return fwd_ok.astype(float).div(fwd_ok.sum(axis=1).clip(lower=1), axis=0)


def weekend_targets(opens: pd.DataFrame) -> pd.DataFrame:
    """Z1: long the equal-weight basket for the days starting Friday, Saturday and Sunday."""
    w = _basket_weights(opens, list(opens.columns))
    hold = pd.Series(opens.index.dayofweek.isin([4, 5, 6]), index=opens.index)
    return w.mul(hold.astype(float), axis=0)


def btc_leadlag_targets(opens: pd.DataFrame, threshold: float = 0.02) -> pd.DataFrame:
    """Z2: alt basket (ex BTC) long after a BTC day above +threshold, short after one below -threshold."""
    alts = [c for c in opens.columns if c != BTC]
    r_btc = daily_returns(opens)[BTC]
    side = np.sign(r_btc.where(r_btc.abs() > threshold, 0.0)).fillna(0.0)
    return _basket_weights(opens, alts).mul(side, axis=0).reindex(columns=opens.columns).fillna(0.0)


def residual_reversal_score(opens: pd.DataFrame, lookback: int = 7, beta_window: int = 60) -> pd.DataFrame:
    """Z3: minus the lookback return left after removing BTC beta x BTC's lookback return."""
    r = daily_returns(opens)
    rb = r[BTC]
    beta = r.rolling(beta_window, min_periods=beta_window).cov(rb).div(rb.rolling(beta_window, min_periods=beta_window).var(), axis=0)
    ret = opens / opens.shift(lookback) - 1.0
    resid = ret - beta.mul(ret[BTC], axis=0)
    return -resid.drop(columns=[BTC], errors="ignore").reindex(columns=opens.columns)


def max_lottery_score(opens: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Z4: minus the largest single-day return over the window."""
    return -daily_returns(opens).rolling(window, min_periods=window).max()


def high_proximity_score(opens: pd.DataFrame, window: int = 180) -> pd.DataFrame:
    """Z5: price relative to its highest daily open over the window."""
    return opens / opens.rolling(window, min_periods=window).max()


def volume_shock_score(volume: pd.DataFrame, index: pd.DatetimeIndex, short: int = 7, long: int = 90) -> pd.DataFrame:
    """Z6: short-window mean volume over long-window mean, using only completed days (shifted one day)."""
    v = volume.reindex(index).shift(1)
    return v.rolling(short, min_periods=short).mean() / v.rolling(long, min_periods=long).mean()


def skewness_score(opens: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Z7: minus the skewness of daily returns over the window."""
    return -daily_returns(opens).rolling(window, min_periods=window).skew()


def market_regimes(opens: pd.DataFrame) -> pd.DataFrame:
    """Causal basket regimes at day d (data before d only): trend efficiency, volatility, direction."""
    r = daily_returns(opens).mean(axis=1).fillna(0.0)
    basket = (1.0 + r).cumprod()
    er = (basket - basket.shift(14)).abs() / basket.diff().abs().rolling(14, min_periods=14).sum()
    rank = er.rolling(181, min_periods=60).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    eff = pd.Series(np.where(rank <= 1 / 3, "CHOP", np.where(rank >= 2 / 3, "TREND", "MIXED")), index=r.index).where(rank.notna())
    vol = r.rolling(20, min_periods=20).std()
    vol_med = vol.rolling(180, min_periods=60).median().shift(1)
    volr = pd.Series(np.where(vol > vol_med, "HIGH_VOL", "LOW_VOL"), index=r.index).where(vol_med.notna() & vol.notna())
    ma = basket.rolling(100, min_periods=100).mean()
    direc = pd.Series(np.where(basket > ma, "BULL", "BEAR"), index=r.index).where(ma.notna())
    # every label uses the basket up to the open of d-1 or earlier
    return pd.DataFrame({"trend_efficiency": eff, "volatility": volr, "direction": direc}).shift(1)


def zoo_books(frames: Mapping[str, pd.DataFrame], fund_panel: pd.DataFrame, *, cost_bps: float = 20.0,
              btc_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """`btc_frame` supplies BTC as a signal-only context series when BTC is not part of the traded sample."""
    opens = daily_open_panel(frames)
    fund = fund_panel.reindex(opens.index).fillna(0.0)
    vol = daily_volume_panel(frames)
    xs = dict(rebalance_days=7, q=0.25, cost_bps=cost_bps)
    ctx = opens
    if BTC not in opens.columns:
        if btc_frame is None:
            raise ValueError("BTC context is required for Z2/Z3 when BTC is not in the sample")
        ctx = opens.join(daily_open_panel({BTC: btc_frame})[BTC], how="left")
    leadlag = btc_leadlag_targets(ctx).reindex(columns=opens.columns).fillna(0.0)
    resid = residual_reversal_score(ctx).reindex(columns=opens.columns)
    books = {
        "Z1_weekend": run_targets(weekend_targets(opens), opens, fund, cost_bps=cost_bps),
        "Z2_btc_leadlag": run_targets(leadlag, opens, fund, cost_bps=cost_bps),
        "Z3_residual_reversal": run_xs(opens, fund, resid, **xs)["returns"],
        "Z4_max_lottery": run_xs(opens, fund, max_lottery_score(opens), **xs)["returns"],
        "Z5_high_proximity": run_xs(opens, fund, high_proximity_score(opens), **xs)["returns"],
        "Z6_volume_shock": run_xs(opens, fund, volume_shock_score(vol, opens.index), **xs)["returns"],
        "Z7_skewness": run_xs(opens, fund, skewness_score(opens), **xs)["returns"],
    }
    return pd.DataFrame(books)

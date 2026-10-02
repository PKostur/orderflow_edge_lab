"""Market-neutral cross-sectional premia on crypto perps (daily, point-in-time universe).

Each rebalance date ranks coins that have data by a score and holds the top and
bottom quantiles at equal dollar weight (50% gross long, 50% gross short).
Positions are held until the next rebalance; weight changes pay turnover cost,
held positions pay or receive funding.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


def daily_open_panel(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({s: f["open"].loc[f.index.hour == 0].astype(float) for s, f in frames.items()}).sort_index()


def daily_funding_panel(funding: Mapping[str, pd.Series], index: pd.DatetimeIndex) -> pd.DataFrame:
    """Sum of settlements in (d, d+1], stamped at d (paid over the day that starts at d)."""
    out = {}
    for s, f in funding.items():
        if f is None or len(f) == 0:
            out[s] = pd.Series(0.0, index=index)
            continue
        day = (f.index - pd.Timedelta(microseconds=1)).floor("D")
        out[s] = f.groupby(day).sum().reindex(index).fillna(0.0)
    return pd.DataFrame(out).reindex(index).fillna(0.0)


def quantile_weights(score: pd.Series, q: float) -> pd.Series:
    s = score.dropna()
    n = int(np.floor(len(s) * q))
    w = pd.Series(0.0, index=score.index)
    if n < 1:
        return w
    order = s.sort_values()
    w[order.index[-n:]] = 0.5 / n
    w[order.index[:n]] = -0.5 / n
    return w


def run_xs(opens: pd.DataFrame, fund: pd.DataFrame, score: pd.DataFrame, *, rebalance_days: int, q: float,
           cost_bps: float, min_names: int = 8) -> dict[str, Any]:
    """Score at day d uses data up to the open of d; trade at the open of d; hold to the next rebalance."""
    ret = opens.shift(-1) / opens - 1.0  # open(d) -> open(d+1)
    w = pd.Series(0.0, index=opens.columns)
    rows, turnover = {}, {}
    for i, d in enumerate(opens.index[:-1]):
        if i % rebalance_days == 0:
            sc = score.loc[d]
            tradable = opens.loc[d].notna() & ret.loc[d].notna()
            sc = sc.where(tradable)
            new = quantile_weights(sc, q) if sc.notna().sum() >= min_names else pd.Series(0.0, index=opens.columns)
            turnover[d] = float((new - w).abs().sum())
            w = new
        r = ret.loc[d].fillna(0.0)
        f = fund.loc[d] if d in fund.index else 0.0
        cost = turnover.get(d, 0.0) * cost_bps / 2.0 / 10_000.0
        rows[d] = float((w * r).sum() - (w * f).sum() - cost)
        grown = w * (1.0 + r)
        w = grown  # drift between rebalances (dollar positions)
    return {"returns": pd.Series(rows).sort_index(), "turnover": pd.Series(turnover)}


def momentum_score(opens: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    return opens / opens.shift(lookback_days) - 1.0


def carry_score(fund: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """Rank by minus trailing funding: long the low-funding names, short the high-funding names.

    Uses funding paid over days strictly before d (shifted by one day).
    """
    return -fund.rolling(lookback_days, min_periods=lookback_days).sum().shift(1)

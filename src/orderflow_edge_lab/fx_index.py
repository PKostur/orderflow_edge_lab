"""FX and stock-index books for fx-index-prop-v1 (config/fx_index_prop_v1.json). Daily, trading-day index.

Weights for day d are decided with closes up to d-1 and earn the close(d-1) -> close(d) return.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

TD = 252


def close_panel(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    c = pd.DataFrame({s: f["close"].astype(float) for s, f in frames.items()}).sort_index()
    return c.ffill(limit=3)


def _vol_size(r: pd.DataFrame, target: float = 0.10, window: int = 60) -> pd.DataFrame:
    vol = r.rolling(window, min_periods=window).std() * np.sqrt(TD)
    return (target / vol).replace([np.inf, -np.inf], np.nan)


def _weekly(w: pd.DataFrame) -> pd.DataFrame:
    keep = w.index.dayofweek == 0
    return w.where(pd.Series(keep, index=w.index), np.nan).ffill()


def run_book(w_decided: pd.DataFrame, closes: pd.DataFrame, *, cost_bps: float, long_financing: float = 0.0) -> pd.Series:
    """w_decided at row d uses data up to d (close); it is applied to the next day's return."""
    r = closes / closes.shift(1) - 1.0
    w = w_decided.shift(1).fillna(0.0)
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1)
    fin = w.clip(lower=0).sum(axis=1) * long_financing / TD
    return (w * r.fillna(0.0)).sum(axis=1) - turn * cost_bps / 2 / 1e4 - fin


def tsmom_weights(closes: pd.DataFrame, lookbacks=(21, 63, 126, 252)) -> pd.DataFrame:
    r = closes / closes.shift(1) - 1.0
    sig = sum(np.sign(closes / closes.shift(L) - 1.0) for L in lookbacks) / len(lookbacks)
    w = sig * _vol_size(r)
    n = w.notna().sum(axis=1).clip(lower=1)
    return _weekly(w.div(n, axis=0)).fillna(0.0)


def long_voltarget_weights(closes: pd.DataFrame) -> pd.DataFrame:
    r = closes / closes.shift(1) - 1.0
    w = _vol_size(r)
    n = w.notna().sum(axis=1).clip(lower=1)
    return _weekly(w.div(n, axis=0)).fillna(0.0)


def rsi2(closes: pd.DataFrame) -> pd.DataFrame:
    d = closes.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    au = up.ewm(alpha=0.5, adjust=False).mean()
    ad = dn.ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + au / ad.replace(0, np.nan))


def rsi2_dip_weights(closes: pd.DataFrame) -> pd.DataFrame:
    r = closes / closes.shift(1) - 1.0
    rsi, ma = rsi2(closes), closes.rolling(200, min_periods=200).mean()
    size = _vol_size(r)
    out = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    for c in closes.columns:
        on, col = False, np.zeros(len(closes))
        for i, (x, p, m, z) in enumerate(zip(rsi[c].to_numpy(), closes[c].to_numpy(), ma[c].to_numpy(), size[c].to_numpy())):
            if not on and np.isfinite(x) and np.isfinite(m) and x < 10 and p > m:
                on = True
            elif on and np.isfinite(x) and x > 70:
                on = False
            col[i] = (z if np.isfinite(z) else 0.0) if on else 0.0
        out[c] = col
    return out / max(1, closes.shape[1])


def fx_xs_momentum_weights(closes: pd.DataFrame, *, lookback: int = 63, k: int = 3, every: int = 21) -> pd.DataFrame:
    r = closes / closes.shift(1) - 1.0
    mom = closes / closes.shift(lookback) - 1.0
    size = _vol_size(r)
    rows, w = {}, pd.Series(0.0, index=closes.columns)
    for i, d in enumerate(closes.index):
        if i % every == 0:
            sc = mom.loc[d].dropna()
            w = pd.Series(0.0, index=closes.columns)
            if len(sc) >= 2 * k:
                o = sc.sort_values()
                w[o.index[-k:]] = size.loc[d, o.index[-k:]].fillna(0.0) / (2 * k)
                w[o.index[:k]] = -size.loc[d, o.index[:k]].fillna(0.0) / (2 * k)
        rows[d] = w
    return pd.DataFrame(rows).T


def sharpe(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std() * np.sqrt(TD)) if len(x) > 20 and x.std() > 0 else float("nan")

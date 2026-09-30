"""Books for custom-sentiment-v1 (config/custom_sentiment_v1.json): forced-flow-with-trend and Fear & Greed signals."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_zoo import _basket_weights, daily_returns


def fng_series(rows: Iterable[Mapping[str, Any]]) -> pd.Series:
    """Fear & Greed values keyed by their UTC date."""
    s = pd.Series({pd.Timestamp(int(r["timestamp"]), unit="s", tz="UTC").floor("D"): float(r["value"]) for r in rows})
    return s.sort_index()


def fng_known_at(fng: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Latest value stamped strictly before day d (value dated d-1 or earlier) for each d in index."""
    prior = index - pd.Timedelta(days=1)
    full = fng.reindex(fng.index.union(prior)).ffill()
    return pd.Series(full.reindex(prior).to_numpy(), index=index)


def forced_flow_targets(opens: pd.DataFrame, volume: pd.DataFrame, *, ma: int = 50, slope: int = 5, k: float = 2.5,
                        vol_win: int = 20, v_mult: float = 2.0, v_win: int = 30, hold: int = 3,
                        size_win: int = 60, target_vol: float = 0.15) -> pd.DataFrame:
    r = daily_returns(opens)  # r at d = move of day d-1 (open d-1 -> open d)
    mean = opens.rolling(ma, min_periods=ma).mean()
    up = (opens > mean) & (mean > mean.shift(slope))
    down = (opens < mean) & (mean < mean.shift(slope))
    sd = r.shift(1).rolling(vol_win, min_periods=vol_win).std()  # stdev before the shock day
    v = volume.reindex(opens.index)
    v_prev = v.shift(1)  # completed volume of day d-1
    v_base = v.shift(2).rolling(v_win, min_periods=v_win).mean()
    spike = v_prev > v_mult * v_base
    buy = up & (r < -k * sd) & spike
    sell = down & (r > k * sd) & spike
    trigger = buy.astype(float) - sell.astype(float)
    size = (target_vol / (r.rolling(size_win, min_periods=size_win).std() * np.sqrt(365))).clip(upper=1.0)
    held = pd.DataFrame(0.0, index=opens.index, columns=opens.columns)
    for c in opens.columns:
        t, z = trigger[c].to_numpy(), size[c].to_numpy()
        out, left, side, sz = np.zeros(len(t)), 0, 0.0, 0.0
        for i in range(len(t)):
            if t[i] != 0 and np.isfinite(z[i]):
                left, side, sz = hold, t[i], z[i]
            out[i] = side * sz if left > 0 else 0.0
            left -= 1
        held[c] = out
    return held.div(opens.notna().sum(axis=1).clip(lower=1), axis=0)


def extreme_fear_targets(opens: pd.DataFrame, fng_at: pd.Series, *, enter: float = 20, leave: float = 50) -> pd.DataFrame:
    state, on = [], False
    for v in fng_at.to_numpy():
        if np.isfinite(v):
            if not on and v <= enter:
                on = True
            elif on and v >= leave:
                on = False
        state.append(1.0 if on else 0.0)
    return _basket_weights(opens, list(opens.columns)).mul(pd.Series(state, index=opens.index), axis=0)


def sentiment_following_targets(opens: pd.DataFrame, fng_at: pd.Series, *, window: int = 7, hi: float = 55, lo: float = 45) -> pd.DataFrame:
    m = fng_at.rolling(window, min_periods=window).mean()
    side = pd.Series(np.where(m >= hi, 1.0, np.where(m <= lo, -1.0, 0.0)), index=opens.index).where(m.notna(), 0.0)
    return _basket_weights(opens, list(opens.columns)).mul(side, axis=0)

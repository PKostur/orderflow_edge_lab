"""Crowding overlay: stand aside when funding says the trend side is crowded.

Per-8h-equivalent funding = sum of settlement rates in the trailing 72 hours up
to the signal bar's close, divided by 9 (so 4h and 8h settlement schedules mean
the same thing).  A long target is set flat while that average exceeds
``threshold``; a short target is set flat while it is below ``-threshold``.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_backtest import FunctionStrategy, StrategyPlugin


def funding_avg_per_8h(funding: pd.Series, bar_index: pd.DatetimeIndex, *, bar_hours: int = 8,
                       window_hours: int = 72) -> pd.Series:
    f = funding.sort_index()
    cum = f.cumsum()
    close = bar_index + pd.Timedelta(hours=bar_hours)  # known at the bar's close
    lo = close - pd.Timedelta(hours=window_hours)
    upto_close = cum.reindex(cum.index.union(close)).ffill().fillna(0.0).reindex(close).to_numpy()
    upto_lo = cum.reindex(cum.index.union(lo)).ffill().fillna(0.0).reindex(lo).to_numpy()
    have = (f.index.min() <= lo) if len(f) else np.zeros(len(close), dtype=bool)
    out = (upto_close - upto_lo) / (window_hours / 8.0)
    return pd.Series(np.where(have, out, np.nan), index=bar_index)


def apply_crowding(base: pd.Series, avg: pd.Series, threshold: float) -> pd.Series:
    a = avg.reindex(base.index)
    crowded_long = (base > 0) & (a > threshold)
    crowded_short = (base < 0) & (a < -threshold)
    return base.where(~(crowded_long | crowded_short).fillna(False), 0.0)


def funding_overlay_strategy(base: StrategyPlugin, funding: pd.Series, *, threshold: float,
                             window_hours: int = 72) -> FunctionStrategy:
    def target(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
        raw = base.generate_target(frame, params, None).reindex(frame.index).fillna(0.0)
        return apply_crowding(raw, funding_avg_per_8h(funding, frame.index, window_hours=window_hours), threshold)

    return FunctionStrategy(strategy_id=f"{base.strategy_id}+funding", target_fn=target,
                            warmup_bars=int(getattr(base, "warmup_bars", 100)))

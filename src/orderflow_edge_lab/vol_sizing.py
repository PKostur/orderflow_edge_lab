"""Entry-time inverse-volatility sizing for frozen trend signals.

size = min(cap, target_vol / realized_vol), with realized volatility taken from
the ``window`` 8h log returns up to and including the signal bar and annualized
with sqrt(3 * 365).  The size is fixed when an episode opens and held until the
signal changes side or goes flat, so under canonical v3 (fixed quantity) it adds
no turnover.  Direction always comes from the unchanged base signal; with
cap <= 1 there is never leverage.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_backtest import FunctionStrategy, StrategyPlugin

BARS_PER_YEAR = 3 * 365


def entry_sized_target(
    frame: pd.DataFrame,
    raw_target: pd.Series,
    *,
    window: int,
    target_vol: float,
    cap: float,
) -> pd.Series:
    close = frame["close"].astype(float)
    realized = np.log(close).diff().rolling(window, min_periods=window).std(ddof=1) * math.sqrt(BARS_PER_YEAR)
    raw = raw_target.reindex(frame.index).fillna(0.0).to_numpy(dtype=float)
    vol = realized.to_numpy(dtype=float)
    out = np.zeros(len(raw))
    size = 0.0
    for i in range(len(raw)):
        side = 1.0 if raw[i] > 0 else (-1.0 if raw[i] < 0 else 0.0)
        previous_side = 0.0 if i == 0 else (1.0 if raw[i - 1] > 0 else (-1.0 if raw[i - 1] < 0 else 0.0))
        if side == 0.0:
            size = 0.0
        elif side != previous_side or size == 0.0:
            v = vol[i]
            size = min(cap, target_vol / v) if np.isfinite(v) and v > 0 else 0.0
        out[i] = side * size
    return pd.Series(out, index=frame.index)


def vol_sized_strategy(
    base: StrategyPlugin, *, window: int, target_vol: float, cap: float
) -> FunctionStrategy:
    def target(frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
        raw = base.generate_target(frame, params, None)
        return entry_sized_target(frame, raw, window=window, target_vol=target_vol, cap=cap)

    return FunctionStrategy(
        strategy_id=f"{base.strategy_id}+invvol",
        target_fn=target,
        warmup_bars=max(int(getattr(base, "warmup_bars", 0)), window + 1),
    )

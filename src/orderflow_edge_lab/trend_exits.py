"""Channel trailing-exit overlay for the frozen trend strategies.

Entries come from the frozen signals.  A long exits to flat when the completed
close falls below the lowest low of the prior ``exit_window`` bars (shorts
mirror it), and it re-enters only on a fresh entry event: a new breakout for
DON8, or a new transition into +/-1 for EMA8.  Winners are never capped.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import generate_target_position
from orderflow_edge_lab.universal_backtest import FunctionStrategy


def entry_events(frame: pd.DataFrame, family: str, params: Mapping[str, Any], base: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    if family == "donchian_breakout":
        n = int(params["lookback"])
        hi = frame["high"].rolling(n, min_periods=n).max().shift(1)
        lo = frame["low"].rolling(n, min_periods=n).min().shift(1)
        close = frame["close"]
        return (close > hi).fillna(False).to_numpy(), (close < lo).fillna(False).to_numpy()
    prev = base.shift(1).fillna(0.0)
    return ((base > 0) & (prev <= 0)).to_numpy(), ((base < 0) & (prev >= 0)).to_numpy()


def with_channel_exit(frame: pd.DataFrame, base: pd.Series, long_ev: np.ndarray, short_ev: np.ndarray,
                      exit_window: int) -> pd.Series:
    b = base.reindex(frame.index).fillna(0.0).to_numpy()
    exit_lo = frame["low"].rolling(exit_window, min_periods=exit_window).min().shift(1).to_numpy()
    exit_hi = frame["high"].rolling(exit_window, min_periods=exit_window).max().shift(1).to_numpy()
    close = frame["close"].to_numpy(dtype=float)
    out = np.zeros(len(b))
    state = 0.0
    for i in range(len(b)):
        if state > 0 and (b[i] <= 0 or (np.isfinite(exit_lo[i]) and close[i] < exit_lo[i])):
            state = 0.0
        elif state < 0 and (b[i] >= 0 or (np.isfinite(exit_hi[i]) and close[i] > exit_hi[i])):
            state = 0.0
        if state == 0.0:
            if b[i] > 0 and long_ev[i]:
                state = 1.0
            elif b[i] < 0 and short_ev[i]:
                state = -1.0
        out[i] = state
    return pd.Series(out, index=frame.index)


def exit_overlay_target(frame: pd.DataFrame, family: str, params: Mapping[str, Any], exit_window: int) -> pd.Series:
    base = generate_target_position(frame, family, dict(params)).reindex(frame.index).fillna(0.0)
    le, se = entry_events(frame, family, params, base)
    return with_channel_exit(frame, base, le, se, exit_window)


def core_strategy(trend_params: Mapping[str, Mapping[str, Any]], *, exit_window: int | None) -> FunctionStrategy:
    """Average of DON8 and EMA8 targets, optionally with the channel exit overlay."""
    fam = {"DON8": "donchian_breakout", "EMA8": "ema_tsmom"}

    def target(frame: pd.DataFrame, _p: Mapping[str, Any]) -> pd.Series:
        parts = []
        for k, f in fam.items():
            if exit_window is None:
                parts.append(generate_target_position(frame, f, dict(trend_params[k])).reindex(frame.index).fillna(0.0))
            else:
                parts.append(exit_overlay_target(frame, f, trend_params[k], exit_window))
        return sum(parts) / len(parts)

    return FunctionStrategy(strategy_id=f"core_exit{exit_window}", target_fn=target, warmup_bars=100)

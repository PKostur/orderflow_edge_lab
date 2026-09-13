from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].astype(float).shift(1)
    true_range = pd.concat(
        [
            (frame["high"].astype(float) - frame["low"].astype(float)).abs(),
            (frame["high"].astype(float) - previous_close).abs(),
            (frame["low"].astype(float) - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(int(period), min_periods=int(period)).mean()


def directional_fib_depth(
    frame: pd.DataFrame,
    target: pd.Series,
    *,
    lookback_bars: int,
    minimum_impulse_atr: float,
    atr_period: int = 14,
) -> pd.Series:
    """Causal retracement depth using only bars strictly before each signal bar."""
    close = frame["close"].astype(float)
    local_atr = atr(frame, atr_period).shift(1)
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    sides = target.reindex(frame.index).fillna(0.0).astype(float)

    for i in range(int(lookback_bars), len(frame)):
        side = int(np.sign(float(sides.iloc[i])))
        if side == 0:
            continue
        hist = frame.iloc[i - int(lookback_bars) : i]
        if len(hist) < int(lookback_bars):
            continue

        if side > 0:
            low_pos = int(np.argmin(hist["low"].to_numpy(dtype=float)))
            if low_pos >= len(hist) - 1:
                continue
            after = hist.iloc[low_pos + 1 :]
            swing_low = float(hist["low"].iloc[low_pos])
            swing_high = float(after["high"].max())
        else:
            high_pos = int(np.argmax(hist["high"].to_numpy(dtype=float)))
            if high_pos >= len(hist) - 1:
                continue
            after = hist.iloc[high_pos + 1 :]
            swing_high = float(hist["high"].iloc[high_pos])
            swing_low = float(after["low"].min())

        impulse = swing_high - swing_low
        atr_ref = local_atr.iloc[i]
        if impulse <= 0 or pd.isna(atr_ref) or float(atr_ref) <= 0:
            continue
        if impulse < float(minimum_impulse_atr) * float(atr_ref):
            continue

        signal_close = float(close.iloc[i])
        depth = (
            (swing_high - signal_close) / impulse
            if side > 0
            else (signal_close - swing_low) / impulse
        )
        if 0.0 <= depth <= 1.0 and math.isfinite(depth):
            out.iloc[i] = float(depth)
    return out


def eligible_near_levels(
    depth: pd.Series, levels: Sequence[float], tolerance: float
) -> pd.Series:
    values = depth.to_numpy(dtype=float)
    ok = np.zeros(len(depth), dtype=bool)
    finite = np.isfinite(values)
    for level in levels:
        ok |= finite & (np.abs(values - float(level)) <= float(tolerance))
    return pd.Series(ok, index=depth.index, dtype=bool)


def gate_target_on_entry_transitions(
    target: pd.Series, eligible: pd.Series
) -> pd.Series:
    """Gate baseline entry/reversal transitions and never manufacture delayed entries."""
    base = target.fillna(0.0).clip(-1.0, 1.0).astype(float)
    gate = eligible.reindex(base.index).fillna(False).astype(bool)
    out = np.zeros(len(base), dtype=float)
    overlay_state = 0
    previous_baseline = 0

    for i in range(len(base)):
        desired = int(np.sign(float(base.iloc[i])))
        transition = desired != previous_baseline
        if overlay_state == 0:
            if desired != 0 and transition and bool(gate.iloc[i]):
                overlay_state = desired
        else:
            if desired == overlay_state:
                pass
            elif desired == 0:
                overlay_state = 0
            else:
                overlay_state = desired if transition and bool(gate.iloc[i]) else 0
        out[i] = float(overlay_state)
        previous_baseline = desired
    return pd.Series(out, index=base.index, dtype=float)

"""Deterministic research controls, not promoted strategies or live instructions.

The midpoint momentum control is a comparison baseline. Its parameters must be
fixed before evaluating a recording; no claim of novel or profitable alpha is
made. It reads displayed quotes only, not a caller-supplied future close field.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class PaperSignalControlError(ValueError):
    """A control parameter or causal observation is inadmissible."""


def make_midpoint_momentum_control(
    *, lookback_quotes: int, cadence_ns: int, target_fraction: float, tolerance_ns: int = 0,
) -> Callable[[Sequence[Mapping[str, Any]]], float]:
    """Return a stateless signed midpoint-momentum comparison control.

    A value is first available after ``lookback_quotes + 1`` valid observations.
    Each recorded interval must match the prespecified cadence within tolerance;
    missing observations raise rather than silently changing the rule's horizon.
    The paper runner interprets an exception as a latched halt. It models the
    resulting target only on a later quote, not on this decision quote.
    """
    for name, value in (("lookback_quotes", lookback_quotes), ("cadence_ns", cadence_ns)):
        if type(value) is not int or value <= 0:
            raise PaperSignalControlError(f"{name} must be a positive integer")
    if type(tolerance_ns) is not int or not 0 <= tolerance_ns < cadence_ns:
        raise PaperSignalControlError("tolerance_ns must be an integer in [0, cadence_ns)")
    if isinstance(target_fraction, bool) or not isinstance(target_fraction, (int, float)):
        raise PaperSignalControlError("target_fraction must be numeric")
    target_fraction = float(target_fraction)
    if not math.isfinite(target_fraction) or not 0 < target_fraction <= 1:
        raise PaperSignalControlError("target_fraction must be finite in (0, 1]")
    specification = {
        "schema": "orderflow_edge_lab.midpoint_momentum_control.v3",
        "lookback_quotes": lookback_quotes, "cadence_ns": cadence_ns,
        "target_fraction": target_fraction, "tolerance_ns": tolerance_ns,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "purpose": "development_comparison_control_only",
        "profitable_edge_established": False, "live_order_transmission_supported": False,
    }
    identity = hashlib.sha256(json.dumps(specification, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def control(history: Sequence[Mapping[str, Any]]) -> float:
        window = history[-(lookback_quotes + 1):]
        mids = []
        previous_ts = None
        for frame in window:
            timestamp = frame.get("ts_ns")
            if type(timestamp) is not int or timestamp <= 0:
                raise PaperSignalControlError("quote timestamp must be positive integer nanoseconds")
            if previous_ts is not None and abs(timestamp - previous_ts - cadence_ns) > tolerance_ns:
                raise PaperSignalControlError("quote cadence differs from the frozen control specification")
            previous_ts = timestamp
            values = [frame.get("bid"), frame.get("ask")]
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
                raise PaperSignalControlError("valid displayed bid/ask are required")
            bid, ask = float(values[0]), float(values[1])
            if bid > ask:
                raise PaperSignalControlError("crossed quote is inadmissible")
            mids.append((bid + ask) / 2)
        if len(window) < lookback_quotes + 1:
            return 0.0
        return target_fraction if mids[-1] > mids[0] else -target_fraction if mids[-1] < mids[0] else 0.0

    control.signal_id = "DEVCTRL-MIDPOINT-MOMENTUM-" + identity  # type: ignore[attr-defined]
    control.specification = specification.copy()  # type: ignore[attr-defined]
    return control

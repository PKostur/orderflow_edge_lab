from __future__ import annotations

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_calibration import (
    build_calibration_report,
    independent_target,
)


def _frame(n: int = 240, phase: float = 0.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="8h", tz="UTC")
    t = np.arange(n, dtype=float)
    close = 100.0 + 0.035 * t + 4.0 * np.sin(t / 11.0 + phase) + 1.5 * np.sin(t / 3.7)
    open_ = close * (1.0 + 0.001 * np.sin(t / 5.0))
    high = np.maximum(open_, close) * 1.006
    low = np.minimum(open_, close) * 0.994
    volume = 1000.0 + t
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _protocol(symbols: list[str]) -> dict:
    return {
        "protocol_name": "test-calibration",
        "candidate_id": "test",
        "data": {"symbols": symbols},
        "strategy": {"fast_ema": 24, "slow_ema": 96, "atr_period": 14, "min_atr_spread": 0.25},
        "parity_gate": {
            "raw_target_disagreements_allowed_per_symbol": 0,
            "execution_target_disagreements_allowed_per_symbol": 0,
        },
    }


def test_independent_target_has_only_three_states() -> None:
    target = independent_target(_frame(), fast=24, slow=96, atr_period=14, threshold=0.25)
    assert set(target.unique()).issubset({-1.0, 0.0, 1.0})


def test_independent_math_matches_current_reference_exactly_on_synthetic_data() -> None:
    frames = {"A": _frame(phase=0.0), "B": _frame(phase=0.7), "C": _frame(phase=1.4)}
    report = build_calibration_report(frames, _protocol(list(frames)))
    assert report["reference_independent_parity_pass"] is True
    for row in report["symbols"].values():
        assert row["raw_target_disagreements"] == 0
        assert row["execution_target_disagreements"] == 0
        assert row["transition_timestamps_match"] is True


def test_future_price_mutation_does_not_change_prior_targets() -> None:
    original = _frame()
    mutated = original.copy()
    cutoff = 180
    mutated.iloc[cutoff:, mutated.columns.get_loc("close")] *= 1.25
    mutated.iloc[cutoff:, mutated.columns.get_loc("open")] *= 1.25
    mutated.iloc[cutoff:, mutated.columns.get_loc("high")] *= 1.25
    mutated.iloc[cutoff:, mutated.columns.get_loc("low")] *= 1.25
    a = independent_target(original, fast=24, slow=96, atr_period=14, threshold=0.25)
    b = independent_target(mutated, fast=24, slow=96, atr_period=14, threshold=0.25)
    pd.testing.assert_series_equal(a.iloc[:cutoff], b.iloc[:cutoff])


def test_execution_target_is_next_bar_not_same_bar() -> None:
    frame = _frame()
    target = independent_target(frame, fast=24, slow=96, atr_period=14, threshold=0.25)
    from orderflow_edge_lab.discovery_v2_calibration import execution_target
    executed = execution_target(target)
    assert executed.iloc[0] == 0.0
    pd.testing.assert_series_equal(
        executed.iloc[1:].reset_index(drop=True),
        target.iloc[:-1].reset_index(drop=True),
        check_names=False,
    )

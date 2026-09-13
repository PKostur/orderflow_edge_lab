from __future__ import annotations

from hashlib import sha256
import json
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.fibonacci_overlay import (
    directional_fib_depth,
    gate_target_on_entry_transitions,
)
from orderflow_edge_lab.htf_fibonacci_forward_shadow import (
    build_execution_targets,
    build_forward_report,
)
from orderflow_edge_lab.htf_trend_forward_shadow import verify_candidate_spec


def _candidate(symbols, start: pd.Timestamp, *, cost_bps: float = 20.0):
    value = {
        "schema_version": 1,
        "candidate_id": "test-fib-trend",
        "frozen_at_utc": start.isoformat(),
        "forward_signal_start_utc": start.isoformat(),
        "selection_provenance": {},
        "specification": {
            "symbols": list(symbols),
            "fast_ema": 2,
            "slow_ema": 4,
            "atr_period": 2,
            "min_atr_spread": 0.0,
            "round_trip_cost_bps": cost_bps,
            "gross_portfolio_exposure_cap": 1.0,
            "leverage": 1.0,
        },
        "fibonacci_overlay": {
            "mode": "entry_transition_gate_only",
            "anchor_lookback_bars": 24,
            "minimum_impulse_atr": 2.0,
            "levels": [0.382, 0.5, 0.618],
            "level_tolerance": 0.025,
        },
        "forward_protocol": {
            "minimum_completed_forward_trades_for_edge_review": 20
        },
    }
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    value["spec_sha256"] = sha256(raw).hexdigest()
    return value


def _frame(index: pd.DatetimeIndex, slope: float = 0.01):
    close = 100.0 * np.exp(np.arange(len(index)) * slope)
    open_ = close * 0.999
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


class HtfFibonacciForwardShadowTests(unittest.TestCase):
    def test_candidate_hash_and_first_execution_are_strictly_forward(self):
        idx = pd.date_range("2026-08-01", periods=160, freq="8h", tz="UTC")
        start = idx[120]
        candidate = _candidate(["A"], start)
        self.assertTrue(verify_candidate_spec(candidate))
        as_of = idx[126] + pd.Timedelta(hours=2)
        targets = build_execution_targets(_frame(idx), candidate, as_of_utc=as_of)
        self.assertGreater(len(targets), 0)
        self.assertEqual(targets.index.min(), start + pd.Timedelta(hours=8))
        self.assertFalse((targets.index <= start).any())

    def test_failed_entry_gate_does_not_manufacture_delayed_entry(self):
        idx = pd.date_range("2026-09-01", periods=6, freq="8h", tz="UTC")
        target = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0, 1.0], index=idx)
        eligible = pd.Series([False, False, True, True, False, True], index=idx)
        gated = gate_target_on_entry_transitions(target, eligible)
        self.assertEqual(gated.tolist(), [0.0, 0.0, 0.0, 0.0, 0.0, 1.0])

    def test_current_signal_bar_high_is_not_part_of_swing_anchor(self):
        idx = pd.date_range("2026-07-01", periods=40, freq="8h", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": np.full(40, 100.0),
                "high": np.full(40, 102.0),
                "low": np.full(40, 98.0),
                "close": np.full(40, 100.0),
            },
            index=idx,
        )
        frame.loc[idx[10], "low"] = 80.0
        frame.loc[idx[20], "high"] = 120.0
        target = pd.Series(0.0, index=idx)
        target.loc[idx[30]] = 1.0
        baseline = directional_fib_depth(
            frame, target, lookback_bars=24, minimum_impulse_atr=2.0, atr_period=14
        )
        altered = frame.copy()
        altered.loc[idx[30], "high"] = 1000.0
        changed = directional_fib_depth(
            altered, target, lookback_bars=24, minimum_impulse_atr=2.0, atr_period=14
        )
        self.assertTrue(np.isfinite(baseline.loc[idx[30]]))
        self.assertEqual(baseline.loc[idx[30]], changed.loc[idx[30]])

    def test_forward_report_remains_paper_only(self):
        idx = pd.date_range("2026-08-01", periods=160, freq="8h", tz="UTC")
        start = idx[120]
        symbols = ["A", "B"]
        candidate = _candidate(symbols, start)
        frames = {
            symbol: _frame(idx, 0.004 + i * 0.0001)
            for i, symbol in enumerate(symbols)
        }
        funding = {
            symbol: pd.DataFrame(
                columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC")
            )
            for symbol in symbols
        }
        report = build_forward_report(
            frames, funding, candidate, as_of_utc=idx[128] + pd.Timedelta(hours=1)
        )
        self.assertEqual(report["experiment"], "htf-fibonacci-forward-shadow-v1")
        self.assertTrue(report["claims"]["fibonacci_overlay_frozen"])
        self.assertTrue(report["claims"]["paper_shadow_only"])
        self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])


if __name__ == "__main__":
    unittest.main()

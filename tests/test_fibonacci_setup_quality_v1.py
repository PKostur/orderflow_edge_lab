from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from scripts.fibonacci_setup_quality_v1 import directional_fib_depth, gate_target_on_entry_transitions


class FibonacciSetupQualityV1Tests(unittest.TestCase):
    def test_missed_entry_is_not_manufactured_later(self) -> None:
        index = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC")
        target = pd.Series([0.0, 1.0, 1.0, 1.0, 0.0, 1.0], index=index)
        eligible = pd.Series([False, False, True, True, False, True], index=index)
        actual = gate_target_on_entry_transitions(target, eligible)
        self.assertEqual(actual.tolist(), [0.0, 0.0, 0.0, 0.0, 0.0, 1.0])

    def test_unqualified_reversal_exits_old_side_without_delayed_reverse(self) -> None:
        index = pd.date_range("2026-01-01", periods=7, freq="h", tz="UTC")
        target = pd.Series([0.0, 1.0, 1.0, -1.0, -1.0, 0.0, -1.0], index=index)
        eligible = pd.Series([False, True, False, False, True, False, True], index=index)
        actual = gate_target_on_entry_transitions(target, eligible)
        self.assertEqual(actual.tolist(), [0.0, 1.0, 1.0, 0.0, 0.0, 0.0, -1.0])

    def test_fib_anchor_excludes_current_signal_bar(self) -> None:
        index = pd.date_range("2026-01-01", periods=25, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": np.full(25, 110.0),
                "high": np.full(25, 111.0),
                "low": np.full(25, 109.0),
                "close": np.full(25, 110.0),
            },
            index=index,
        )
        frame.iloc[0, frame.columns.get_loc("low")] = 100.0
        frame.iloc[10, frame.columns.get_loc("high")] = 120.0
        # Extreme current-bar values must not alter the prior-bar anchor.
        frame.iloc[24, frame.columns.get_loc("high")] = 999.0
        frame.iloc[24, frame.columns.get_loc("low")] = 1.0
        target = pd.Series(0.0, index=index)
        target.iloc[24] = 1.0
        depth = directional_fib_depth(
            frame,
            target,
            lookback_bars=24,
            minimum_impulse_atr=2.0,
            atr_period=14,
        )
        self.assertAlmostEqual(float(depth.iloc[24]), 0.5, places=9)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_session_diagnostics import build_universal_session_diagnostics


class UniversalSessionDiagnosticsTests(unittest.TestCase):
    def test_compounded_return_sessions_correct_direction_and_alignment(self):
        index = pd.date_range("2024-01-01", periods=10, freq="8h", tz="UTC")
        opens = np.arange(100.0, 110.0)
        closes = opens.copy()
        closes[0] = 101.0
        closes[1] = 103.0
        closes[2] = 101.0
        closes[3] = 104.0
        closes[4] = 106.0
        closes[5] = 104.0
        frame = pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, closes) + 1.0,
                "low": np.minimum(opens, closes) - 1.0,
                "close": closes,
            },
            index=index,
        )
        ledger = [
            {
                "entry": index[1].isoformat(),
                "exit": index[2].isoformat(),
                "side": 1,
                "gross_bps": 120.0,
                "net_bps": 100.0,
                "mfe_bps": 300.0,
                "mae_bps": -40.0,
            },
            {
                "entry": index[2].isoformat(),
                "exit": index[3].isoformat(),
                "side": -1,
                "gross_bps": -30.0,
                "net_bps": -50.0,
                "mfe_bps": 80.0,
                "mae_bps": -100.0,
            },
            {
                "entry": index[3].isoformat(),
                "exit": index[4].isoformat(),
                "side": 1,
                "gross_bps": 220.0,
                "net_bps": 200.0,
                "mfe_bps": 400.0,
                "mae_bps": -20.0,
            },
        ]
        expected = 1.01 * 0.995 * 1.02 - 1.0
        result = build_universal_session_diagnostics(
            frame,
            {
                "trades_ledger": ledger,
                "total_return": expected,
                "accounting": {"version": 2},
            },
            symbol="ETH_USDT",
            btc_frame=frame,
        )

        self.assertAlmostEqual(result["baseline"]["cumulative_return"], expected)
        self.assertTrue(result["baseline_reconciles_to_canonical_total_return"])
        self.assertAlmostEqual(result["baseline"]["win_rate"], 2.0 / 3.0)
        self.assertAlmostEqual(result["baseline"]["expectancy_bps"], 250.0 / 3.0)
        self.assertEqual(result["baseline"]["correct_direction_observations"], 2)
        self.assertAlmostEqual(result["baseline"]["median_correct_direction_mfe_bps"], 350.0)
        self.assertTrue(result["protocol"]["alignment_uses_pre_entry_information_only"])

        asia = next(row for row in result["by_session_membership"] if row["session"] == "ASIA")
        self.assertGreaterEqual(asia["observations"], 1)
        aligned = next(
            row
            for row in result["by_alignment_factor"]
            if row["factor"] == "prior_bar_direction" and row["state"] == "ALIGNED"
        )
        self.assertGreaterEqual(aligned["observations"], 1)

    def test_empty_ledger_is_descriptive_and_zero_return(self):
        index = pd.date_range("2024-01-01", periods=4, freq="8h", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [101.0, 102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0, 102.0],
                "close": [100.5, 101.5, 102.5, 103.5],
            },
            index=index,
        )
        result = build_universal_session_diagnostics(
            frame,
            {"trades_ledger": [], "total_return": 0.0, "accounting": {"version": 2}},
            symbol="BTC_USDT",
            btc_frame=frame,
        )
        self.assertEqual(result["baseline"]["observations"], 0)
        self.assertEqual(result["baseline"]["cumulative_return"], 0.0)
        self.assertTrue(result["baseline_reconciles_to_canonical_total_return"])
        self.assertFalse(result["claims"]["strategy_promotion_authorized"])


if __name__ == "__main__":
    unittest.main()

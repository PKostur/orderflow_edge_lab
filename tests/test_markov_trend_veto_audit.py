from __future__ import annotations

import unittest

import pandas as pd

from orderflow_edge_lab.markov_trend_veto_audit import audit_trend_decisions


class MarkovTrendVetoAuditTests(unittest.TestCase):
    def test_pass_veto_realized_discrimination_is_causal_and_cost_aware(self) -> None:
        idx = pd.date_range("2026-09-16", periods=8, freq="8h", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": [100, 101, 102, 104, 105, 106, 107, 108],
                "high": [101, 102, 103, 105, 106, 107, 108, 109],
                "low": [99, 100, 101, 103, 104, 105, 106, 107],
                "close": [100.5, 101.5, 102.5, 104.5, 105.5, 106.5, 107.5, 108.5],
            },
            index=idx,
        )
        decisions = [
            {
                "symbol": "A",
                "execution_time": idx[0].isoformat(),
                "decision": "PASS",
                "base_requested_side": 1.0,
                "state": "UP|NORMAL",
                "conservative_score_bps": 5.0,
            },
            {
                "symbol": "A",
                "execution_time": idx[1].isoformat(),
                "decision": "VETO",
                "base_requested_side": -1.0,
                "state": "UP|NORMAL",
                "conservative_score_bps": -3.0,
            },
            {
                "symbol": "A",
                "execution_time": idx[-2].isoformat(),
                "decision": "VETO",
                "base_requested_side": 1.0,
                "state": "UP|NORMAL",
                "conservative_score_bps": -1.0,
            },
        ]
        funding = {"A": pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC"))}
        report = audit_trend_decisions(
            decisions,
            {"A": frame},
            funding,
            horizon_bars=3,
            round_trip_cost_bps=20.0,
            minimum_completed_decisions_for_review=20,
        )
        self.assertEqual(report["completed_decisions"], 2)
        self.assertEqual(report["censored_decisions"], 1)
        self.assertGreater(report["pass"]["mean_realized_net_bps"], 0)
        self.assertLess(report["veto"]["mean_realized_net_bps"], 0)
        self.assertGreater(report["pass_minus_veto_mean_realized_net_bps"], 0)
        self.assertEqual(report["avoided_veto_losses"], 1)
        self.assertFalse(report["reviewable_count_reached"])


if __name__ == "__main__":
    unittest.main()

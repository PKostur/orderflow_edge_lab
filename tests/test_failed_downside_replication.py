"""Independent replay boundary, scheduling and dependence regression checks."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from orderflow_edge_lab.failed_downside_replication import feasibility, replay
from orderflow_edge_lab.public_strategy_shadow import Bar


def fixture():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [Bar(start + timedelta(hours=8 * i), 106, 110, 100, 106, 1) for i in range(40)]
    for i, low in ((30, 90), (32, 80), (39, 70)):
        # Bearish recovery bars are valid in the original definition.
        bars[i] = Bar(bars[i].timestamp, 109, 110, low, 108, 1)
    bars[31] = Bar(bars[31].timestamp, 108, 110, 100, 106, 1)
    bars[33] = Bar(bars[33].timestamp, 110, 110, 100, 106, 1)
    btc = [Bar(b.timestamp, 100, 100, 100, 100, 1) for b in bars]
    return bars, btc


class IndependentFailedDownsideTests(unittest.TestCase):
    def test_next_open_exit_reentry_and_terminal_pending(self):
        bars, btc = fixture()
        report = replay("ETH_USDT", bars, btc)
        self.assertEqual(report["signals_count"], 3)
        self.assertEqual(report["overlap_skipped"], 0)
        first, second, pending = report["events"]
        self.assertEqual(first["entry_open"], 108)
        self.assertEqual(first["exit_open"], 110)
        self.assertEqual(first["exit_time"], second["entry_time"])
        self.assertAlmostEqual(first["net_bps"], (110 / 108 - 1) * 10_000 - 20)
        self.assertEqual(pending["status"], "pending")
        self.assertNotIn("gross_bps", pending)

    def test_signal_uses_previous_lows_and_strict_break(self):
        bars, btc = fixture()
        prefix = replay("ETH_USDT", bars[:31], btc[:31])
        self.assertEqual(prefix["events"][0]["signal_time"], replay("ETH_USDT", bars, btc)["events"][0]["signal_time"])
        b = bars[30]
        bars[30] = Bar(b.timestamp, 109, 110, 100, 108, 1)
        self.assertEqual(replay("ETH_USDT", bars[:31], btc[:31])["signals_count"], 0)

    def test_same_week_duplicates_do_not_create_statistical_information(self):
        design = {"study_id": "test", "family_alpha": 0.05, "multiplicity_denominator": 9,
                  "target_power": 0.8, "economic_hurdle_excess_bps": 5,
                  "spent_grid_bars": 6726, "true_mean_scenarios_bps": [10, 25],
                  "calendar_year_scenarios": [1, 2]}
        events = [{"status": "completed", "exit_time": "2026-01-01T00:00:00Z", "excess_vs_btc_bps": 0},
                  {"status": "completed", "exit_time": "2026-01-08T00:00:00Z", "excess_vs_btc_bps": 100}]
        a = feasibility(events, design)
        b = feasibility(events + events, design)
        self.assertEqual(a["cluster_ratio_mean_standard_error_bps"], 50)
        self.assertEqual(a["cluster_ratio_mean_standard_error_bps"], b["cluster_ratio_mean_standard_error_bps"])
        self.assertEqual(a["power_scenarios"], b["power_scenarios"])
        self.assertFalse(a["candidate_frozen"])


if __name__ == "__main__":
    unittest.main()

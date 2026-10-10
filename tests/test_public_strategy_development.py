"""Regression checks for research diagnostics and source gap detection."""

from __future__ import annotations

import importlib.util
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orderflow_edge_lab.public_strategy_development import drawdown, path_metrics, portfolio_equity, row_metrics
from orderflow_edge_lab.public_strategy_shadow import Bar


class DevelopmentDiagnosticsTests(unittest.TestCase):
    def test_path_excludes_exit_bar_and_does_not_invent_intrabar_order(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [
            Bar(t, 100, 110, 95, 103, 1),
            Bar(t + timedelta(hours=8), 103, 120, 90, 115, 1),
            Bar(t + timedelta(hours=16), 115, 500, 1, 115, 1),
        ]
        result = path_metrics(bars, 0, 2, 100, 20)
        self.assertAlmostEqual(result["mfe_bps"], 2000)
        self.assertAlmostEqual(result["mae_bps"], -1000)
        self.assertAlmostEqual(result["pre_mfe_completed_bar_adverse_bps"], -500)
        self.assertAlmostEqual(result["mfe_after_cost_bps"], 1980)

    def test_return_metrics_apply_cost_once_and_keep_btc_matched(self):
        rows = [{"symbol": "ETH_USDT", "week": "2026-W01", "gross_bps": 100,
                 "btc_gross_bps": 60, "excess_bps": 40, "mfe_bps": 120, "mae_bps": -50,
                 "pre_mfe_completed_bar_adverse_bps": None, "pre_exit_adverse_bps": -50},
                {"symbol": "SOL_USDT", "week": "2026-W02", "gross_bps": -100,
                 "btc_gross_bps": -50, "excess_bps": -50, "mfe_bps": 10, "mae_bps": -130,
                 "pre_mfe_completed_bar_adverse_bps": -80, "pre_exit_adverse_bps": -130}]
        result = row_metrics(rows)
        self.assertEqual(result["net_expectancy_bps"], -20)
        self.assertEqual(result["matched_btc_net_bps"], -15)
        self.assertEqual(result["excess_vs_btc_bps"], -5)
        self.assertEqual(result["cost_stress_mean_net_bps"]["40"], -40)
        self.assertEqual(result["pre_mfe_completed_bar_adverse_bps"]["n"], 1)
        self.assertTrue(math.isclose(drawdown([100, -100])[0], -0.01))

    def test_collector_marks_discontinuity_without_filling(self):
        module_path = Path(__file__).resolve().parents[1] / "scripts/collect_public_spot_8h.py"
        spec = importlib.util.spec_from_file_location("spot_collector", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        step = 8 * 60 * 60 * 1000
        row = lambda stamp: [stamp, "100", "110", "90", "105", "1"]
        result = module.validate([row(0), row(2 * step)], "TESTUSDT")
        self.assertEqual(len(result["gaps"]), 1)

    def test_portfolio_uses_cash_sleeves_and_both_side_costs(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stamps = [t + timedelta(hours=8 * i) for i in range(3)]
        frames = {
            "ETH_USDT": [Bar(stamps[i], opening, opening, opening, opening, 1)
                         for i, opening in enumerate((100, 110, 110))],
            "SOL_USDT": [Bar(stamps[i], 100, 100, 100, 100, 1) for i in range(3)],
        }
        events = [{"status": "completed", "symbol": "ETH_USDT",
                   "entry_time": "2026-01-01T00:00:00Z", "exit_time": "2026-01-01T08:00:00Z"}]
        result = portfolio_equity(events, frames, ["ETH_USDT", "SOL_USDT"])
        expected = ((1.1 * 0.999 * 0.999 + 1) / 2 - 1) * 100
        self.assertAlmostEqual(result["terminal_return_pct"], expected)
        self.assertLess(result["max_drawdown_pct"], 0)


if __name__ == "__main__":
    unittest.main()

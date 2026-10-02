from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.short_convention_comparison import (
    ShortConventionError,
    static_net_bps,
    summarize,
    trade_pair,
)


def _frame(opens: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01T00:00:00Z", periods=len(opens), freq="8h")
    o = np.asarray(opens, dtype=float)
    return pd.DataFrame({"open": o, "high": o * 1.01, "low": o * 0.99, "close": o}, index=idx)


class ShortConventionTests(unittest.TestCase):
    def test_static_net_charges_entry_and_exit_side_costs(self):
        self.assertAlmostEqual(static_net_bps(0.0, 20.0), ((1 - 0.001) ** 2 - 1) * 1e4)
        self.assertAlmostEqual(static_net_bps(100.0, 0.0), 100.0)

    def test_long_is_identical_under_both_conventions(self):
        frame = _frame([100, 110, 90, 120, 120])
        trade = {"entry": frame.index[0].isoformat(), "exit": frame.index[3].isoformat(),
                 "side": 1, "entry_position": 1.0, "gross_bps": 2000.0, "net_bps": 0.0}
        trade["net_bps"] = static_net_bps(2000.0, 20.0)
        pair = trade_pair(trade, frame, cost_bps=20.0)
        self.assertAlmostEqual(pair["ledger_net_bps"], pair["static_net_bps"])

    def test_short_rebalanced_differs_from_fixed_quantity(self):
        frame = _frame([100, 110, 90, 100, 100])
        path = (0.9 * (1 + 20 / 110) * (1 - 10 / 90) - 1) * 1e4
        trade = {"entry": frame.index[0].isoformat(), "exit": frame.index[3].isoformat(),
                 "side": -1, "entry_position": -1.0, "gross_bps": path,
                 "net_bps": static_net_bps(path, 20.0)}
        pair = trade_pair(trade, frame, cost_bps=20.0)
        self.assertAlmostEqual(pair["static_gross_bps"], 0.0)
        self.assertLess(pair["ledger_gross_bps"], 0.0)
        self.assertGreater(pair["static_net_bps"], pair["ledger_net_bps"])

    def test_non_unit_position_is_rejected(self):
        frame = _frame([100, 101, 102])
        trade = {"entry": frame.index[0].isoformat(), "exit": frame.index[1].isoformat(),
                 "side": 1, "entry_position": 0.5, "gross_bps": 50.0, "net_bps": 30.0}
        with self.assertRaises(ShortConventionError):
            trade_pair(trade, frame, cost_bps=20.0)

    def test_summary_splits_direction_and_reports_both_conventions(self):
        rows = [
            {"side_label": "LONG", "ledger_net_bps": 10.0, "static_net_bps": 10.0},
            {"side_label": "SHORT", "ledger_net_bps": -30.0, "static_net_bps": 5.0},
            {"side_label": "SHORT", "ledger_net_bps": 20.0, "static_net_bps": 25.0},
        ]
        out = summarize(rows)
        self.assertEqual(out["SHORT"]["n"], 2)
        self.assertAlmostEqual(out["SHORT"]["ledger"]["expectancy_bps"], -5.0)
        self.assertAlmostEqual(out["SHORT"]["static"]["expectancy_bps"], 15.0)
        self.assertAlmostEqual(out["ALL"]["static"]["win_rate"], 1.0)
        self.assertIsNone(out["LONG"]["ledger"]["profit_factor"])


if __name__ == "__main__":
    unittest.main()

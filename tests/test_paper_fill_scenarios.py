from __future__ import annotations

import unittest

import pandas as pd

from orderflow_edge_lab.paper_account import replay
from orderflow_edge_lab.paper_fill_scenarios import CLAIMS, REGISTERED, SCENARIOS, adverse_fill_price, replay_scenario, run_grid

SPEC = {"A_USDT": {"contractSize": 1.0, "minVol": 1, "takerFeeRate": 0.0}, "B_USDT": {"contractSize": 10.0, "minVol": 1, "takerFeeRate": 0.0004}}
START = pd.Timestamp("2026-10-05", tz="UTC")


def _data(n=6):
    days = pd.date_range("2026-10-05", periods=n, freq="D", tz="UTC")
    idx = days + pd.Timedelta(hours=8)
    a = [100.0 + 3 * i - (i % 2) * 5 for i in range(n)]
    b = [50.0 - 2 * i + (i % 3) * 4 for i in range(n)]
    open8 = pd.DataFrame({"A_USDT": a, "B_USDT": b}, index=idx)
    ranges = open8 * 0.04
    scale = [1.0 if i % 2 == 0 else 0.6 for i in range(n)]  # weights change daily so trades occur every day
    tw = pd.DataFrame({"A_USDT": [0.5 * x for x in scale], "B_USDT": [-0.5 * x for x in scale]}, index=days)
    fund = {"B_USDT": pd.Series([0.001], index=[pd.Timestamp("2026-10-05T16:00Z")])}
    return tw, open8, ranges, fund


class PaperFillScenariosTests(unittest.TestCase):
    def test_registered_reproduces_replay_exactly(self):
        tw, open8, ranges, fund = _data()
        ref = replay(tw, open8, fund, SPEC, start=START, initial=10000.0)
        got = replay_scenario(tw, open8, fund, SPEC, start=START, initial=10000.0, ranges=ranges)
        self.assertEqual(got["equity"], ref["equity"])
        self.assertEqual(got["curve"], ref["curve"])
        self.assertEqual(round(got["totals"]["fees"], 2), ref["totals"]["fees"])
        self.assertEqual(round(got["totals"]["traded_notional"], 2), ref["totals"]["traded_notional"])

    def test_higher_slippage_never_increases_equity(self):
        tw, open8, ranges, fund = _data()
        res = run_grid(tw, open8, fund, SPEC, start=START, initial=10000.0, ranges=ranges)
        eq = [res[k]["final_equity"] for k in ("registered_5bps", "slippage_10bps", "slippage_20bps", "slippage_40bps")]
        self.assertTrue(all(x >= y for x, y in zip(eq, eq[1:])))
        self.assertEqual(res[REGISTERED]["equity_diff_vs_registered"], 0.0)
        self.assertLess(res["adverse_fill_quarter_range_10bps"]["final_equity"], res["slippage_10bps"]["final_equity"])

    def test_adverse_adjustment_direction(self):
        self.assertAlmostEqual(adverse_fill_price(100.0, 110.0, 90.0, 5, 0.25), 105.0)
        self.assertAlmostEqual(adverse_fill_price(100.0, 110.0, 90.0, -5, 0.25), 95.0)
        self.assertEqual(adverse_fill_price(100.0, 110.0, 90.0, 5, 0.0), 100.0)

    def test_min_order_stress_skips_small_positions(self):
        tw, open8, ranges, fund = _data()
        spec = {**SPEC, "A_USDT": {**SPEC["A_USDT"], "minVol": 30}}  # ~30-50 contracts pass minVol but fall below 2 x 30
        base = replay_scenario(tw, open8, fund, spec, start=START, initial=10000.0)
        strict = replay_scenario(tw, open8, fund, spec, start=START, initial=10000.0, min_order_mult=2)
        self.assertGreater(base["totals"]["traded_notional"], strict["totals"]["traded_notional"])

    def test_claims_all_false(self):
        self.assertFalse(any(CLAIMS.values()))
        self.assertIn(REGISTERED, SCENARIOS)


if __name__ == "__main__":
    unittest.main()

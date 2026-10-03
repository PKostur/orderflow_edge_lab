from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from orderflow_edge_lab.paper_account import contracts_for, replay

SPEC = {"A_USDT": {"contractSize": 1.0, "minVol": 1, "takerFeeRate": 0.0}, "B_USDT": {"contractSize": 10.0, "minVol": 1, "takerFeeRate": 0.0004}}


def _data(prices_a, prices_b):
    days = pd.date_range("2026-10-05", periods=len(prices_a), freq="D", tz="UTC")
    open8 = pd.DataFrame({"A_USDT": prices_a, "B_USDT": prices_b}, index=days + pd.Timedelta(hours=8))
    targets = pd.DataFrame({"A_USDT": [0.5] * len(days), "B_USDT": [-0.5] * len(days)}, index=days)
    return targets, open8


class PaperAccountTests(unittest.TestCase):
    def test_config_is_paper_only(self):
        cfg = json.loads(Path("config/paper_account_blend_v1.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["claims"]["live_trading_authorized"])
        self.assertFalse(cfg["claims"]["orders_sent"])

    def test_lot_rounding_and_minimum(self):
        self.assertEqual(contracts_for(0.5, 10000, 100.0, {"contractSize": 1.0, "minVol": 1}), 50)
        self.assertEqual(contracts_for(0.001, 10000, 100.0, {"contractSize": 1.0, "minVol": 1}), 0)  # 0.1 contract rounds to 0
        self.assertEqual(contracts_for(-0.5, 10000, 100.0, {"contractSize": 10.0, "minVol": 1}), -5)

    def test_replay_pnl_fees_and_funding(self):
        targets, open8 = _data([100.0, 110.0, 110.0], [100.0, 100.0, 100.0])
        fund = {"B_USDT": pd.Series([0.001], index=[pd.Timestamp("2026-10-05T16:00Z")])}
        led = replay(targets, open8, fund, SPEC, start=pd.Timestamp("2026-10-05", tz="UTC"), initial=10000.0, slippage=0.0, min_fee=0.0)
        # day 0: buy 50 A (fee 0), sell 5 B contracts = 50 units (fee 0.0004 x 5000 = 2)
        self.assertAlmostEqual(led["totals"]["fees"], 2.0)  # A is fee-free; later A trims are fee-free too
        first = led["curve"][0]["equity"]
        # A +10 x 50 = +500; short B receives funding 0.001 x 5000 = +5; minus the day-0 fee 2
        self.assertAlmostEqual(first, 10000 - 2 + 500 + 5, places=6)
        self.assertEqual(len(led["curve"]), 2)

    def test_pre_start_days_are_ignored(self):
        targets, open8 = _data([100.0, 100.0], [100.0, 100.0])
        led = replay(targets, open8, {}, SPEC, start=pd.Timestamp("2026-12-01", tz="UTC"), initial=10000.0)
        self.assertEqual(led["days"], 0)
        self.assertEqual(led["equity"], 10000.0)


if __name__ == "__main__":
    unittest.main()

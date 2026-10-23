import json
import unittest
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.carry_forward import build_report

CFG = json.loads(Path("config/carry_forward_v1.json").read_text(encoding="utf-8"))
DAYS = pd.date_range("2026-09-24", "2026-11-03", freq="D", tz="UTC")


def inputs(funding_per_day=0.0003):
    px = pd.Series(100.0, index=DAYS)
    return {s: (px, px, pd.Series(funding_per_day, index=DAYS)) for s in CFG["assets"]}


class CarryForwardTests(unittest.TestCase):
    def test_pre_start_days_are_never_scored(self):
        r = build_report(CFG, inputs(), as_of="2026-10-24T05:00:00Z")
        self.assertEqual(r["status"], "PRE_START")
        self.assertEqual(r["portfolio"]["days"], 0)

    def test_constant_funding_accrues_on_hedged_notional(self):
        r = build_report(CFG, inputs(0.0003), as_of="2026-11-03T05:00:00Z")
        a = r["assets"]["BTCUSDT"]
        self.assertEqual(r["status"], "COLLECTING")
        self.assertEqual(a["days"], 10)                                  # entered 10-24 close, earns 10-25..11-03
        self.assertAlmostEqual(a["funding_usdt"], 2500 * 0.0003 * 10)
        self.assertAlmostEqual(a["costs_usdt"], 2500 * 19e-4)            # entry only; the book is still open
        self.assertAlmostEqual(a["net_after_exit_usdt"], a["net_usdt"] - 2500 * 19e-4)
        self.assertAlmostEqual(r["portfolio"]["net_usdt"], 2 * a["net_usdt"])
        self.assertTrue(all(t > r["prospective_start_utc"] for t in r["daily_returns"]["portfolio"]))
        self.assertFalse(any(v for k, v in r["claims"].items()))

    def test_missing_asset_is_reported_not_dropped_silently(self):
        inp = inputs()
        inp.pop("ETHUSDT")
        r = build_report(CFG, inp, as_of="2026-11-03T05:00:00Z")
        self.assertEqual(r["assets"]["ETHUSDT"], {"status": "MISSING_DATA"})


if __name__ == "__main__":
    unittest.main()

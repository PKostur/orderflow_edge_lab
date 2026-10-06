from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from orderflow_edge_lab.prop_paper_forward import run_career

FIRM = json.loads(Path("config/prop_firm_v1.json").read_text(encoding="utf-8"))["firms"]["HyroTrader_1step"]
PRULE = json.loads(Path("config/prop_firm_v6.json").read_text(encoding="utf-8"))["payout_rules"]["HyroTrader_1step"]


def _series(vals):
    idx = pd.date_range("2026-10-06", periods=len(vals), freq="D", tz="UTC")
    return pd.Series(vals, index=idx), pd.Series(0.25, index=idx)  # 25% annual vol -> challenge scale 1x


class PropPaperForwardTests(unittest.TestCase):
    def test_registered_before_start_and_paper_only(self):
        cfg = json.loads(Path("config/prop_paper_forward_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["prospective_start_utc"], "2026-10-05T00:00:00Z")
        self.assertFalse(any(cfg["claims"].values()))

    def test_pass_then_payouts(self):
        r, v = _series([0.02] * 30)
        c = run_career(r, v, FIRM, PRULE)
        kinds = [e["event"] for e in c["events"]]
        self.assertEqual(kinds[0], "challenge_bought")
        self.assertIn("challenge_passed", kinds)
        self.assertIn("payout", kinds)
        self.assertGreater(c["net_pct"], 0)
        self.assertEqual(c["phase"], "funded")

    def test_breach_rebuys(self):
        r, v = _series([0.0, -0.05, 0.0])
        c = run_career(r, v, FIRM, PRULE)
        self.assertEqual(c["challenges_bought"], 2)
        self.assertIn("challenge_breach", [e["event"] for e in c["events"]])


if __name__ == "__main__":
    unittest.main()

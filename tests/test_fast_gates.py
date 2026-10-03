from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from orderflow_edge_lab.fast_gates import breakage_alarm, build_report, implementation_gate

CFG = json.loads(Path("config/fast_gates_v1.json").read_text(encoding="utf-8"))
START = pd.Timestamp(CFG["prospective_start_utc"])
TH1 = CFG["thresholds"]["G1_implementation"]
TH2 = CFG["thresholds"]["G2_breakage_alarm"]


def _days(n, first="2026-10-06"):
    return pd.date_range(first, periods=n, freq="D", tz="UTC")


class FastGatesTests(unittest.TestCase):
    def test_config_frozen_and_descriptive(self):
        self.assertEqual(CFG["status"], "FROZEN_BEFORE_PROSPECTIVE_START")
        self.assertTrue(all(v is False for v in CFG["claims"].values()))
        self.assertLess(TH2["max_drawdown_alarm"], 0)
        self.assertEqual(CFG["prospective_start_utc"], "2026-10-05T00:00:00Z")

    def test_g1_pass_when_tracking(self):
        idx = _days(61)
        v = pd.Series(0.001, index=idx)
        g = implementation_gate(v + TH1["mean_daily_diff"], v, 70, start=START, as_of=pd.Timestamp("2026-12-10", tz="UTC"),
                                th=TH1, checkpoints=[30, 60])
        self.assertEqual(g["days"], 60)  # first (book-building) day excluded
        self.assertEqual(g["checkpoints"]["30"]["verdict"], "ON_TRACK")
        self.assertEqual(g["status"], "PASS")

    def test_g1_fail_on_cost_drift_and_missing_coins(self):
        idx = _days(61)
        v = pd.Series(0.001, index=idx)
        g = implementation_gate(v - 0.0005, v, 70, start=START, as_of=pd.Timestamp("2026-12-10", tz="UTC"), th=TH1, checkpoints=[30, 60])
        self.assertEqual(g["status"], "FAIL")
        self.assertFalse(g["checkpoints"]["60"]["rules"]["band"])
        g2 = implementation_gate(v, v, 40, start=START, as_of=pd.Timestamp("2026-12-10", tz="UTC"), th=TH1, checkpoints=[30, 60])
        self.assertFalse(g2["checkpoints"]["60"]["rules"]["data"])

    def test_g1_collecting_before_checkpoint(self):
        idx = _days(5)
        v = pd.Series(0.0, index=idx)
        g = implementation_gate(v, v, 70, start=START, as_of=pd.Timestamp("2026-10-11", tz="UTC"), th=TH1, checkpoints=[30, 60])
        self.assertEqual(g["status"], "COLLECTING")

    def test_g2_alarm_and_ok(self):
        idx = _days(40)
        calm = pd.Series(0.0005, index=idx)
        self.assertEqual(breakage_alarm(calm, start=START, th=TH2, window=180)["status"], "OK")
        crash = pd.Series(-0.01, index=idx)  # about -33% over 40 days
        a = breakage_alarm(crash, start=START, th=TH2, window=180)
        self.assertEqual(a["status"], "ALARM")
        self.assertTrue(a["rules_hit"]["drawdown"])

    def test_g2_ignores_pre_start_days(self):
        s = pd.Series(-0.05, index=pd.date_range("2026-09-30", "2026-10-05", tz="UTC"))
        self.assertEqual(breakage_alarm(s, start=START, th=TH2, window=180)["status"], "PRE_START")

    def test_report_shape(self):
        r = build_report(CFG, {"blend": None, "human": None, "paper": None}, None, as_of="2026-10-04T12:00:00Z")
        self.assertEqual(r["status"], "PRE_START")
        self.assertNotIn("daily_returns", r)
        self.assertEqual([x["audit_id"] for x in r["strategies"]], ["G1_implementation", "G2_breakage_alarm", "G3_venue_replication"])


if __name__ == "__main__":
    unittest.main()

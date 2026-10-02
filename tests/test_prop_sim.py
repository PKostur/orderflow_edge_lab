from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np

from orderflow_edge_lab.prop_sim import evaluate, evaluate_survival, run_challenge, run_funded, run_phase

FTMO2 = {"phases": [0.10, 0.05], "daily_loss": 0.05, "max_loss": 0.10, "max_loss_type": "static", "min_days": 4,
         "best_day_rule": 0.5, "split": 0.8, "fee_pct": 0.0054}


class PropSimTests(unittest.TestCase):
    def test_config_declared(self):
        cfg = json.loads(Path("config/prop_firm_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["status"], "DECLARED_BEFORE_EVALUATION")
        self.assertEqual(len(cfg["firms"]), 5)

    def test_steady_gains_pass_both_phases(self):
        r = np.full(100, 0.01)
        ok, days, end = run_challenge(r, 0, FTMO2)
        self.assertTrue(ok)
        self.assertEqual(days, 10 + 5)  # 1% a day: ~10 days to +10%, then ~5 days to +5%

    def test_daily_loss_with_buffer(self):
        r = np.array([0.0, -0.041, 0.2])  # 4.1% loss > 0.8 x 5%
        self.assertFalse(run_phase(r, 0, 0.10, FTMO2).passed)
        r2 = np.array([0.0, -0.039] + [0.02] * 20)
        self.assertTrue(run_phase(r2, 0, 0.10, FTMO2).passed)

    def test_best_day_rule_delays_pass(self):
        r = np.array([0.105] + [0.001] * 200)
        res = run_phase(r, 0, 0.10, FTMO2)
        self.assertFalse(res.passed and res.days < 4)
        no_rule = dict(FTMO2, best_day_rule=None)
        self.assertEqual(run_phase(r, 0, 0.10, no_rule).days, 4)  # min days only

    def test_trailing_max_loss(self):
        trail = dict(FTMO2, max_loss_type="trailing_eod", max_loss=0.05, daily_loss=0.5)
        r = np.array([0.04, -0.02, -0.025])  # peak 1.04, floor 1.0; ends below
        self.assertFalse(run_phase(r, 0, 0.5, trail).passed)
        self.assertEqual(run_phase(r, 0, 0.5, trail).days, 3)

    def test_funded_payout_and_evaluate(self):
        r = np.full(400, 0.002)
        paid = run_funded(r, 0, FTMO2)
        self.assertGreater(paid, 0.05)
        out = evaluate(r, FTMO2)
        self.assertEqual(out["pass_rate"], 1.0)
        self.assertGreater(out["ev_per_100"], 0)
        self.assertEqual(evaluate(np.full(400, -0.002), FTMO2)["pass_rate"], 0.0)

    def test_survival_metrics_separate_breach_and_stuck(self):
        steady = evaluate_survival(np.full(900, 0.003), FTMO2)
        self.assertEqual(steady["pass_rate"], 1.0)
        self.assertEqual(steady["funded_survival_12m"], 1.0)
        self.assertEqual(steady["p_paid_by_3m"], 1.0)
        flat = evaluate_survival(np.zeros(900), FTMO2)
        self.assertEqual(flat["stuck_rate"], 1.0)
        self.assertEqual(flat["breach_rate"], 0.0)
        crash = np.zeros(900)
        crash[::50] = -0.06
        self.assertEqual(evaluate_survival(crash, FTMO2)["breach_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

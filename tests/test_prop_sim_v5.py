from __future__ import annotations

import unittest

import numpy as np

from orderflow_edge_lab.prop_sim import evaluate_survival
from orderflow_edge_lab.prop_sim_v5 import evaluate_pair, run_phase

FIRM = {"phases": [0.10], "daily_loss": 0.04, "max_loss": 0.06, "max_loss_type": "static", "min_days": 5,
        "best_day_rule": None, "split": 0.8, "fee_pct": 0.00579}


class PropSimV5Tests(unittest.TestCase):
    def test_constant_approach_matches_v2_simulator(self):
        r = np.random.default_rng(3).normal(0.0006, 0.01, 1500)
        const = lambda st: 0.5  # noqa: E731
        v5 = evaluate_pair(r, r, FIRM, const, const, {}, {})
        v2 = evaluate_survival(r * 0.5, FIRM)
        self.assertAlmostEqual(v5["pass_rate"], v2["pass_rate"])
        self.assertAlmostEqual(v5["funded_survival_12m"], v2["funded_survival_12m"])

    def test_scale_function_sees_state(self):
        seen = []
        def fn(st):
            seen.append((st["k"], round(st["eq"], 6)))
            return 1.0
        why, days, _ = run_phase(np.full(30, 0.02), 0, 0.10, FIRM, fn, {})
        self.assertEqual(why, "pass")
        self.assertEqual(seen[0], (0, 1.0))
        self.assertGreater(seen[-1][1], 1.0)


if __name__ == "__main__":
    unittest.main()

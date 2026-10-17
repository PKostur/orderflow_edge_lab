import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab import capacity as cap


def _panel(n=40, coins=("A", "B")):
    idx = pd.date_range("2026-01-01", periods=n, tz="UTC")
    rng = np.random.default_rng(1)
    dw = pd.DataFrame(rng.normal(0, 0.05, (n, len(coins))), index=idx, columns=list(coins))
    adv = pd.DataFrame(1e8, index=idx, columns=list(coins))
    sig = pd.DataFrame(0.03, index=idx, columns=list(coins))
    return dw, adv, sig


class CapacityTests(unittest.TestCase):
    def test_sqrt_scaling(self):
        a = cap.impact_cost_fraction(1e5, 1e8, 0.03)
        b = cap.impact_cost_fraction(4e5, 1e8, 0.03)
        self.assertAlmostEqual(float(b / a), 2.0)
        self.assertAlmostEqual(float(cap.impact_cost_fraction(1e5, 1e8, 0.03, y=2.0) / a), 2.0)

    def test_zero_turnover_zero_drag(self):
        dw, adv, sig = _panel()
        z = dw * 0.0
        self.assertEqual(cap.impact_drag(z, adv, sig, 1e7), 0.0)
        self.assertEqual(cap.fee_drag(z), 0.0)

    def test_drag_monotone_in_aum(self):
        dw, adv, sig = _panel()
        d = [cap.impact_drag(dw, adv, sig, a) for a in (1e4, 1e5, 1e6, 1e7)]
        self.assertTrue(all(x < y for x, y in zip(d, d[1:])))
        self.assertAlmostEqual(d[1] / d[0], np.sqrt(10), places=6)

    def test_threshold_solver(self):
        dw, adv, sig = _panel()
        fn = lambda a: cap.impact_drag(dw, adv, sig, a)  # noqa: E731
        target = 0.05
        a = cap.solve_aum_threshold(fn, target)
        self.assertAlmostEqual(fn(a), target, places=6)
        self.assertEqual(cap.solve_aum_threshold(lambda x: 0.0, 0.1), float("inf"))

    def test_nan_liquidity_ignored(self):
        dw, adv, sig = _panel()
        adv.iloc[:, 0] = np.nan
        per = cap.per_coin_impact_drag(dw, adv, sig, 1e6)
        self.assertEqual(per["A"], 0.0)
        self.assertGreater(per["B"], 0.0)


if __name__ == "__main__":
    unittest.main()

import math
import unittest
from statistics import NormalDist

import numpy as np

from orderflow_edge_lab import review_methods as rm


def _series(t, mean=0.001, sd=0.01, seed=3):
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, sd, t)
    return x - x.mean() + mean


class DeflatedSharpeNullConsistentTests(unittest.TestCase):
    def test_n1_is_probabilistic_sharpe_vs_zero(self):
        x = _series(500)
        out = rm.deflated_sharpe_null_consistent(x, 1)
        sr = out["sharpe_daily"]
        psr = NormalDist().cdf(
            sr * math.sqrt(out["T"] - 1)
            / math.sqrt(1 - out["skew"] * sr + (out["kurtosis"] - 1) / 4 * sr**2)
        )
        self.assertEqual(out["sr0_daily"], 0.0)
        self.assertEqual(out["expected_max_z"], 0.0)
        self.assertAlmostEqual(out["probability"], psr, places=12)

    def test_probability_increases_with_T(self):
        probs = []
        for t in (100, 400, 1600):
            x = np.tile(_series(100, mean=0.001, sd=0.01), t // 100)
            probs.append(rm.deflated_sharpe_null_consistent(x, 5)["probability"])
        self.assertLess(probs[0], probs[1])
        self.assertLess(probs[1], probs[2])

    def test_larger_n_raises_sr0(self):
        x = _series(300)
        sr0 = [rm.deflated_sharpe_null_consistent(x, n)["sr0_daily"] for n in (1, 2, 10, 50)]
        self.assertEqual(sr0, sorted(sr0))
        self.assertLess(sr0[0], sr0[-1])
        p1 = rm.deflated_sharpe_null_consistent(x, 2)["probability"]
        p2 = rm.deflated_sharpe_null_consistent(x, 50)["probability"]
        self.assertGreater(p1, p2)

    def test_hand_computed_small_series(self):
        x = [0.01, -0.01, 0.02, 0.0]
        # mean 0.005, sample sd = sqrt(0.0003/... ) computed by hand
        mean = 0.005
        dev = [0.005, -0.015, 0.015, -0.005]
        sd = math.sqrt(sum(d * d for d in dev) / 3)
        sr = mean / sd
        m2 = sum(d**2 for d in dev) / 4
        skew = sum(d**3 for d in dev) / 4 / m2**1.5  # symmetric deviations -> 0
        kurt = sum(d**4 for d in dev) / 4 / m2**2
        var_term = 1 - skew * sr + (kurt - 1) / 4 * sr**2
        n = 10
        g = 0.5772156649015329
        nd = NormalDist()
        emax = (1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e))
        sr0 = math.sqrt(var_term / 3) * emax
        prob = nd.cdf((sr - sr0) * math.sqrt(3) / math.sqrt(var_term))
        out = rm.deflated_sharpe_null_consistent(x, n)
        self.assertAlmostEqual(out["sharpe_daily"], sr, places=12)
        self.assertAlmostEqual(out["sr0_daily"], sr0, places=12)
        self.assertAlmostEqual(out["probability"], prob, places=12)
        self.assertEqual(out["T"], 4)
        self.assertEqual(out["pass"], prob >= 0.95)

    def test_expected_max_approximation(self):
        # The approximation deviates from the exact values: N=2 0.52 vs 0.564, N=10 1.575 vs 1.539, so tolerances are wider than 0.02.
        for n, known, tol in ((2, 0.56, 0.05), (10, 1.54, 0.04), (100, 2.51, 0.03)):
            self.assertAlmostEqual(rm.expected_max_normal_z(n), known, delta=tol)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            rm.deflated_sharpe_null_consistent([0.01, 0.01, 0.01], 3)
        with self.assertRaises(ValueError):
            rm.expected_max_normal_z(0)


if __name__ == "__main__":
    unittest.main()

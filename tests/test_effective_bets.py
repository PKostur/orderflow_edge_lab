from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.effective_bets import (
    average_pairwise_correlation,
    marginal_gain,
    participation_ratio,
)


class EffectiveBetsTests(unittest.TestCase):
    def test_independent_series_give_n(self):
        rng = np.random.default_rng(0)
        x = pd.DataFrame(rng.normal(size=(20000, 5)))
        self.assertAlmostEqual(participation_ratio(x), 5.0, delta=0.05)

    def test_identical_series_give_one(self):
        rng = np.random.default_rng(1)
        base = rng.normal(size=5000)
        x = pd.DataFrame({i: base * (i + 1) for i in range(6)})
        self.assertAlmostEqual(participation_ratio(x), 1.0, places=6)
        self.assertAlmostEqual(average_pairwise_correlation(x), 1.0, places=6)

    def test_one_factor_market_is_close_to_one_when_correlation_is_high(self):
        rng = np.random.default_rng(2)
        m = rng.normal(size=(20000, 1))
        x = pd.DataFrame(0.9 * m + np.sqrt(1 - 0.81) * rng.normal(size=(20000, 10)))
        self.assertLess(participation_ratio(x), 1.6)

    def test_marginal_gain_prefers_uncorrelated_candidate(self):
        rng = np.random.default_rng(3)
        m = rng.normal(size=(5000, 1))
        base = pd.DataFrame(0.8 * m + 0.6 * rng.normal(size=(5000, 4)), columns=list("abcd"))
        cands = pd.DataFrame({"same": (0.8 * m + 0.6 * rng.normal(size=(5000, 1)))[:, 0],
                              "indep": rng.normal(size=5000)})
        gains = {r["symbol"]: r["gain"] for r in marginal_gain(base, cands)}
        self.assertGreater(gains["indep"], gains["same"])

    def test_sparse_columns_are_dropped(self):
        x = pd.DataFrame({"a": np.arange(100.0), "b": [np.nan] * 90 + list(range(10))})
        self.assertEqual(participation_ratio(x), 1.0)


if __name__ == "__main__":
    unittest.main()

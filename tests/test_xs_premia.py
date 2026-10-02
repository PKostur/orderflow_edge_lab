from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.xs_premia import carry_score, momentum_score, quantile_weights, run_xs


class XsPremiaTests(unittest.TestCase):
    def test_quantile_weights_are_dollar_neutral(self):
        w = quantile_weights(pd.Series(np.arange(12.0), index=list("abcdefghijkl")), 0.25)
        self.assertAlmostEqual(w.sum(), 0.0)
        self.assertAlmostEqual(w.abs().sum(), 1.0)
        self.assertGreater(w["l"], 0)
        self.assertLess(w["a"], 0)

    def test_momentum_pays_in_persistent_cross_section(self):
        idx = pd.date_range("2024-01-01", periods=400, freq="D", tz="UTC")
        drift = np.linspace(-0.002, 0.002, 12)
        opens = pd.DataFrame(100 * np.exp(np.outer(np.arange(400), drift)), index=idx, columns=[f"c{i}" for i in range(12)])
        fund = pd.DataFrame(0.0, index=idx, columns=opens.columns)
        r = run_xs(opens, fund, momentum_score(opens, 30), rebalance_days=7, q=0.25, cost_bps=20)["returns"]
        self.assertGreater(r.iloc[60:].mean(), 0)

    def test_carry_collects_funding_on_flat_prices(self):
        idx = pd.date_range("2024-01-01", periods=200, freq="D", tz="UTC")
        cols = [f"c{i}" for i in range(12)]
        opens = pd.DataFrame(100.0, index=idx, columns=cols)
        fund = pd.DataFrame(np.tile(np.linspace(-0.001, 0.001, 12), (200, 1)), index=idx, columns=cols)
        r = run_xs(opens, fund, carry_score(fund, 7), rebalance_days=7, q=0.25, cost_bps=0)["returns"]
        self.assertGreater(r.iloc[20:].mean(), 0)

    def test_score_is_causal(self):
        idx = pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC")
        fund = pd.DataFrame(np.random.default_rng(0).normal(size=(50, 3)), index=idx, columns=list("abc"))
        a = carry_score(fund, 7)
        fund.iloc[30:] = 99.0
        b = carry_score(fund, 7)
        pd.testing.assert_frame_equal(a.iloc[:31], b.iloc[:31])


if __name__ == "__main__":
    unittest.main()

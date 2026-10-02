from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.portfolio_optimizer import (
    mean_variance_weights,
    min_variance_weights,
    shrunk_means,
    walk_forward,
)


class OptimizerTests(unittest.TestCase):
    def test_weights_are_long_only_sum_to_one_and_capped(self):
        rng = np.random.default_rng(0)
        mu = rng.normal(0.001, 0.001, 10)
        a = rng.normal(size=(10, 10))
        cov = a @ a.T / 1e4 + np.eye(10) * 1e-4
        w = mean_variance_weights(mu, cov, risk_aversion=5.0, cap=0.2)
        self.assertAlmostEqual(w.sum(), 1.0, places=6)
        self.assertTrue((w >= -1e-9).all())
        self.assertTrue((w <= 0.2 + 1e-9).all())

    def test_mvo_tilts_toward_higher_mean_at_equal_risk(self):
        cov = np.eye(3) * 1e-4
        mu = np.array([0.001, 0.0, 0.0])
        w = mean_variance_weights(mu, cov, risk_aversion=1.0, cap=1.0)
        self.assertGreater(w[0], 0.9)

    def test_min_variance_prefers_low_vol_assets(self):
        cov = np.diag([1e-4, 4e-4, 9e-4])
        w = min_variance_weights(cov, cap=1.0)
        self.assertTrue(w[0] > w[1] > w[2])
        self.assertAlmostEqual(w.sum(), 1.0, places=6)

    def test_shrunk_means_move_toward_grand_mean(self):
        rng = np.random.default_rng(1)
        x = pd.DataFrame(rng.normal(0.0, 0.02, (200, 5)))
        x.iloc[:, 0] += 0.004
        raw = x.mean().to_numpy()
        s = shrunk_means(x)
        grand = raw.mean()
        self.assertTrue((np.abs(s - grand) <= np.abs(raw - grand) + 1e-12).all())

    def test_walk_forward_is_causal_and_charges_turnover(self):
        rng = np.random.default_rng(2)
        idx = pd.date_range("2020-01-01", periods=900, freq="D", tz="UTC")
        r = pd.DataFrame(rng.normal(0.0005, 0.02, (900, 4)), index=idx, columns=list("abcd"))
        out = walk_forward(r, method="equal", lookback_days=365, rebalance="MS", cost_bps=10.0, cap=1.0)
        self.assertEqual(out["returns"].index.min(), pd.Timestamp("2021-01-01", tz="UTC"))
        changed = r.copy()
        changed.loc["2022-06-01":] *= -5.0  # future data must not move earlier weights
        out2 = walk_forward(changed, method="mvo_shrunk", lookback_days=365, rebalance="MS", cost_bps=10.0, cap=0.5)
        out3 = walk_forward(r, method="mvo_shrunk", lookback_days=365, rebalance="MS", cost_bps=10.0, cap=0.5)
        early = out2["weights"].loc[:"2022-05-01"]
        pd.testing.assert_frame_equal(early, out3["weights"].loc[:"2022-05-01"])
        self.assertGreaterEqual(out3["turnover_cost_total"], 0.0)


if __name__ == "__main__":
    unittest.main()

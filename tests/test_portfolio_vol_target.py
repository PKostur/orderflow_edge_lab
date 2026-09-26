from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.portfolio_vol_target import vol_target_overlay


class VolTargetTests(unittest.TestCase):
    def _series(self, vol_daily: float, n: int = 800, seed: int = 0) -> pd.Series:
        idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
        return pd.Series(np.random.default_rng(seed).normal(0.0003, vol_daily, n), index=idx)

    def test_hits_target_vol_when_uncapped(self):
        r = self._series(0.005)  # ~9.6% annual
        out = vol_target_overlay(r, pd.Series(0.3, index=r.index), target_annual_vol=0.15,
                                 window_days=60, max_leverage=10.0, cost_bps=0.0)
        realized = out["returns"].iloc[200:].std() * np.sqrt(365)
        self.assertAlmostEqual(realized, 0.15, delta=0.02)

    def test_leverage_cap_and_causality(self):
        r = self._series(0.001)
        out = vol_target_overlay(r, pd.Series(0.3, index=r.index), target_annual_vol=0.15,
                                 window_days=60, max_leverage=3.0, cost_bps=0.0)
        self.assertLessEqual(out["leverage"].max(), 3.0)
        r2 = r.copy()
        r2.iloc[500:] *= 10
        out2 = vol_target_overlay(r2, pd.Series(0.3, index=r.index), target_annual_vol=0.15,
                                  window_days=60, max_leverage=3.0, cost_bps=0.0)
        pd.testing.assert_series_equal(out["leverage"].iloc[:500], out2["leverage"].iloc[:500])

    def test_costs_charged_on_leverage_changes(self):
        r = self._series(0.01)
        out = vol_target_overlay(r, pd.Series(0.5, index=r.index), target_annual_vol=0.15,
                                 window_days=60, max_leverage=3.0, cost_bps=20.0)
        self.assertGreater(out["total_cost"], 0.0)


if __name__ == "__main__":
    unittest.main()

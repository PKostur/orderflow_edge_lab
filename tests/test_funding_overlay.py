from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.funding_overlay import apply_crowding, funding_avg_per_8h


class FundingOverlayTests(unittest.TestCase):
    def test_average_is_per_8h_equivalent_for_4h_and_8h_schedules(self):
        bars = pd.date_range("2024-01-05T00:00Z", periods=3, freq="8h")
        f8 = pd.Series(0.0003, index=pd.date_range("2024-01-01T00:00Z", "2024-01-06T00:00Z", freq="8h"))
        f4 = pd.Series(0.00015, index=pd.date_range("2024-01-01T00:00Z", "2024-01-06T00:00Z", freq="4h"))
        self.assertTrue(np.allclose(funding_avg_per_8h(f8, bars), 0.0003))
        self.assertTrue(np.allclose(funding_avg_per_8h(f4, bars), 0.0003))

    def test_uses_only_settlements_up_to_bar_close(self):
        bars = pd.DatetimeIndex([pd.Timestamp("2024-01-05T00:00Z")])
        f = pd.Series(0.0, index=pd.date_range("2024-01-01T00:00Z", "2024-01-07T00:00Z", freq="8h"))
        before = funding_avg_per_8h(f, bars).iloc[0]
        f.loc[pd.Timestamp("2024-01-05T16:00Z")] = 1.0  # after the bar's close (08:00)
        self.assertEqual(funding_avg_per_8h(f, bars).iloc[0], before)

    def test_crowded_side_goes_flat_only(self):
        idx = pd.RangeIndex(4)
        base = pd.Series([1.0, 1.0, -1.0, -1.0], index=idx)
        avg = pd.Series([0.0005, 0.0001, -0.0005, 0.0005], index=idx)
        self.assertEqual(list(apply_crowding(base, avg, 0.0003)), [0.0, 1.0, 0.0, -1.0])

    def test_missing_history_is_nan_and_leaves_target(self):
        bars = pd.DatetimeIndex([pd.Timestamp("2024-01-01T00:00Z")])
        f = pd.Series(0.001, index=pd.date_range("2024-01-01T00:00Z", periods=3, freq="8h"))
        avg = funding_avg_per_8h(f, bars)
        self.assertTrue(np.isnan(avg.iloc[0]))
        self.assertEqual(list(apply_crowding(pd.Series([1.0], index=bars), avg, 0.0003)), [1.0])


if __name__ == "__main__":
    unittest.main()

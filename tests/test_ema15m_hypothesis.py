from __future__ import annotations

import unittest

from orderflow_edge_lab.ema15m_hypothesis import _add_ema15m_bias, _deps


class EMA15mHypothesisTests(unittest.TestCase):
    def test_completed_candle_timing_is_causal(self):
        np, pd = _deps()
        idx = pd.date_range("2026-01-01", periods=70 * 15, freq="min", tz="UTC")
        close = 100.0 + np.arange(len(idx)) * 0.001
        d = pd.DataFrame({"close": close}, index=idx)
        before = _add_ema15m_bias(d, pd, np)
        cutoff = 60 * 15
        changed = d.copy()
        changed.loc[idx[cutoff]:, "close"] = 1_000.0
        after = _add_ema15m_bias(changed, pd, np)
        pd.testing.assert_series_equal(
            before["ema15m_20_50_bias"].iloc[:cutoff],
            after["ema15m_20_50_bias"].iloc[:cutoff],
        )
        self.assertTrue(before["ema15m_20_50_bias"].iloc[50 * 15 : cutoff].notna().all())


if __name__ == "__main__":
    unittest.main()

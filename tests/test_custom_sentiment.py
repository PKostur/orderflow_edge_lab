from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.custom_sentiment import (
    extreme_fear_targets,
    fng_known_at,
    fng_series,
    forced_flow_targets,
    sentiment_following_targets,
)


class CustomSentimentTests(unittest.TestCase):
    def test_config_declared_and_contamination_disclosed(self):
        cfg = json.loads(Path("config/custom_sentiment_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["status"], "DECLARED_BEFORE_EVALUATION")
        self.assertIn("CONTAMINATED BY DESIGN", cfg["registration_note"])

    def test_fng_value_is_from_the_previous_day(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
        fng = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0], index=idx)
        known = fng_known_at(fng, idx)
        self.assertTrue(np.isnan(known.iloc[0]))
        self.assertEqual(list(known.iloc[1:]), [10.0, 20.0, 30.0, 40.0])

    def test_fng_parsing(self):
        s = fng_series([{"timestamp": "1704067200", "value": "25"}, {"timestamp": "1703980800", "value": "30"}])
        self.assertEqual(list(s), [30.0, 25.0])
        self.assertEqual(str(s.index[-1].date()), "2024-01-01")

    def test_extreme_fear_enters_at_20_and_leaves_at_50(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
        o = pd.DataFrame(100.0, index=idx, columns=["A", "B"])
        t = extreme_fear_targets(o, pd.Series([30, 18, 40, 49, 55, 20.0], index=idx))
        self.assertEqual(list(t.sum(axis=1).round(6)), [0.0, 1.0, 1.0, 1.0, 0.0, 0.0])  # last day has no next open

    def test_sentiment_following_sides(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="D", tz="UTC")
        o = pd.DataFrame(100.0, index=idx, columns=["A", "B"])
        f = pd.Series([80.0] * 10 + [20.0] * 10, index=idx)
        t = sentiment_following_targets(o, f).sum(axis=1)
        self.assertEqual(t.iloc[8], 1.0)
        self.assertEqual(t.iloc[18], -1.0)

    def test_forced_flow_trades_with_the_trend_after_a_volume_shock(self):
        n = 120
        idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        price = 100 * np.exp(np.cumsum(np.full(n, 0.01) + np.random.default_rng(0).normal(0, 0.005, n)))
        price[100] = price[99] * 0.85  # forced drop on day 99 -> 100
        vol = np.ones(n)
        vol[99] = 10.0  # day 99's volume, known from day 100
        o = pd.DataFrame({"A": price, "B": price * 1.0}, index=idx)
        v = pd.DataFrame({"A": vol, "B": np.ones(n)}, index=idx)
        t = forced_flow_targets(o, v)
        self.assertGreater(t["A"].iloc[100], 0)
        self.assertGreater(t["A"].iloc[102], 0)
        self.assertEqual(t["A"].iloc[103], 0.0)
        self.assertEqual(t["B"].abs().sum(), 0.0)


if __name__ == "__main__":
    unittest.main()

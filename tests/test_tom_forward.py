import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import tom_forward as tf

CONFIG = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "turn_of_month_forward_v1.json").read_text(encoding="utf-8")
)


def _spy(start="2026-01-02", end="2026-12-31", seed=1):
    idx = pd.bdate_range(start, end, tz="UTC")
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(idx))), index=idx, name="SPY")


class TomForwardTests(unittest.TestCase):
    def test_pre_start_days_never_scored(self):
        report = tf.build_report(CONFIG, _spy(), as_of="2026-12-31")
        stamps = list(report["daily_returns"]["tom"])
        self.assertTrue(stamps)
        self.assertTrue(all(t > report["prospective_start_utc"] for t in stamps))
        self.assertEqual(report["forward"]["tom"]["days"], report["forward"]["spy"]["days"])

    def test_status_flips_after_start(self):
        close = _spy()
        pre = tf.build_report(CONFIG, close, as_of="2026-10-12")
        self.assertEqual(pre["status"], "PRE_START")
        self.assertEqual(pre["forward"]["tom"]["days"], 0)
        self.assertEqual(pre["invested_days"], 0)
        self.assertEqual(pre["daily_returns"]["tom"], {})
        post = tf.build_report(CONFIG, close, as_of="2026-11-30")
        self.assertEqual(post["status"], "COLLECTING")
        self.assertGreater(post["forward"]["tom"]["days"], 0)
        self.assertGreater(post["invested_days"], 0)
        self.assertFalse(post["review_window_open"])
        late = tf.build_report(CONFIG, _spy(end="2027-12-31"), as_of="2027-12-31")
        self.assertTrue(late["review_window_open"])

    def test_future_data_ignored(self):
        close = _spy()
        a = tf.build_report(CONFIG, close, as_of="2026-11-10")
        b = tf.build_report(CONFIG, close[close.index <= "2026-11-10"], as_of="2026-11-10")
        self.assertEqual(a["daily_returns"], b["daily_returns"])

    def test_rule_identical_to_search_v1(self):
        close = _spy()
        prices = ss.build_prices({"SPY": close})
        w = ss.weights_R1C4_turn_of_month({"prices": prices}, {"days_before": 1, "days_after": 3})
        expected, _ = ss.backtest(w, ss.asset_returns(prices), 10.0)
        pd.testing.assert_series_equal(tf.tom_net_returns(close), expected)
        # 4 held days per full month: day -1 of the next month end plus days +1..+3 (earn from t-1 weights)
        held = w["SPY"].shift(1).fillna(0.0) > 0
        month = prices.index.to_period("M")
        self.assertEqual(int(held[month == pd.Period("2026-05")].sum()), 3 + 1)

    def test_claims_all_false(self):
        report = tf.build_report(CONFIG, _spy(), as_of="2026-11-30")
        self.assertTrue(report["claims"])
        self.assertFalse(any(report["claims"].values()))
        with self.assertRaises(tf.TomForwardError):
            tf.build_report({**CONFIG, "watch_id": "other"}, _spy(), as_of="2026-11-30")


if __name__ == "__main__":
    unittest.main()

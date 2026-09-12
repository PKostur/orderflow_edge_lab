from __future__ import annotations

import unittest

from orderflow_edge_lab.market_conditions import (
    _bucket_ratio,
    _bucket_spread,
    _bucket_strength,
    _bucket_trade_count,
    _summarize_group,
)


class MarketConditionTests(unittest.TestCase):
    def test_pre_registered_bucket_boundaries(self):
        self.assertEqual(_bucket_spread(1.0), "narrow<=1")
        self.assertEqual(_bucket_spread(2.0), "medium>1<=3")
        self.assertEqual(_bucket_spread(4.0), "wide>3")
        self.assertEqual(_bucket_ratio(2.0, kind="range"), "low<=2")
        self.assertEqual(_bucket_ratio(5.0, kind="range"), "medium>2<=6")
        self.assertEqual(_bucket_ratio(7.0, kind="range"), "high>6")
        self.assertEqual(_bucket_ratio(1.0, kind="return"), "flat<=1")
        self.assertEqual(_bucket_ratio(3.0, kind="return"), "moving>1<=4")
        self.assertEqual(_bucket_ratio(5.0, kind="return"), "strong>4")
        self.assertEqual(_bucket_trade_count(2), "sparse<=2")
        self.assertEqual(_bucket_trade_count(3), "active3-8")
        self.assertEqual(_bucket_trade_count(9), "intense>=9")
        self.assertEqual(_bucket_strength(1.2), "weak1-1.5")
        self.assertEqual(_bucket_strength(2.0), "medium1.5-2.5")
        self.assertEqual(_bucket_strength(3.0), "strong>=2.5")

    def test_screening_readiness_requires_independent_batches(self):
        rows = []
        for batch in ("a", "b", "c"):
            for _ in range(7):
                rows.append({"batch_id": batch, "net_bps": 2.0})
            rows.append({"batch_id": batch, "net_bps": -1.0})
        summary = _summarize_group(rows)
        self.assertGreaterEqual(summary["observations"], 20)
        self.assertEqual(summary["independent_batches"], 3)
        self.assertGreater(summary["net_profit_factor"], 1.0)
        self.assertTrue(summary["screening_condition_ready"])

        two_batches = [row for row in rows if row["batch_id"] != "c"]
        self.assertFalse(_summarize_group(two_batches)["screening_condition_ready"])


if __name__ == "__main__":
    unittest.main()

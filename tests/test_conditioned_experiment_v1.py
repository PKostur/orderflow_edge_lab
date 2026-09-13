from __future__ import annotations

import unittest

from orderflow_edge_lab.conditioned_experiment_v1 import _profit_factor, _state_gate


class ConditionedExperimentV1Tests(unittest.TestCase):
    def test_profit_factor(self) -> None:
        self.assertAlmostEqual(_profit_factor([2.0, -1.0, 3.0, -1.0]), 2.5)
        self.assertEqual(_profit_factor([1.0, 2.0]), "INF")
        self.assertIsNone(_profit_factor([0.0, 0.0]))

    def test_upper_bucket_uses_latest_causal_state(self) -> None:
        mapping = {
            "state_hypothesis": {"feature": "spread_bps"},
            "strategy_state_mapping": {
                "selected_raw_feature_bucket": "upper",
                "feature_thresholds": {"lower": 1.0, "upper": 2.0},
            },
        }
        market_state = {
            "sampling": {"sample_seconds": 5},
            "observations": [
                {"observed_at_ns": 10_000_000_000, "features": {"spread_bps": 2.5}},
                {"observed_at_ns": 15_000_000_000, "features": {"spread_bps": 1.5}},
            ],
        }
        qualifies, metadata = _state_gate(mapping, market_state)
        self.assertTrue(qualifies({"signal_observed_at_ns": 12_000_000_000}))
        self.assertFalse(qualifies({"signal_observed_at_ns": 16_000_000_000}))
        self.assertFalse(qualifies({"signal_observed_at_ns": 21_000_000_001}))
        self.assertEqual(metadata["max_state_staleness_seconds"], 5)

    def test_lower_bucket(self) -> None:
        mapping = {
            "state_hypothesis": {"feature": "top_depth_notional"},
            "strategy_state_mapping": {
                "selected_raw_feature_bucket": "lower",
                "feature_thresholds": {"lower": 100.0, "upper": 200.0},
            },
        }
        market_state = {
            "sampling": {"sample_seconds": 5},
            "observations": [
                {"observed_at_ns": 1_000_000_000, "features": {"top_depth_notional": 90.0}},
            ],
        }
        qualifies, _ = _state_gate(mapping, market_state)
        self.assertTrue(qualifies({"signal_observed_at_ns": 1_000_000_000}))


if __name__ == "__main__":
    unittest.main()

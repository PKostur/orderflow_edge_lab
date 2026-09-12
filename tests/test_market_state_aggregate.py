from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.market_state_aggregate import MarketStateAggregateError, aggregate_market_state_reports


class MarketStateAggregateTests(unittest.TestCase):
    def _report(self, root: Path, batch: int, *, batch_id: str | None = None) -> Path:
        observations = []
        for index in range(40):
            a = float(index)
            b = index * 0.9 + (index % 5) * 0.3 + batch * 0.01
            c = float((index * 7 + batch * 3) % 17)
            target = index * 1.5 + (index % 4) * 0.4 + batch * 0.1
            observations.append(
                {
                    "features": {"feature_a": a, "feature_b": b, "feature_c": c},
                    "targets": {"signed_return_bps_15s": target},
                }
            )
        payload = {
            "schema_version": 1,
            "experiment": "regime_research_v1_market_state_scan",
            "batch_id": batch_id or f"batch-{batch}",
            "associations": [
                {
                    "research_family": "signed_direction_or_continuation",
                    "feature": "feature_a",
                    "target": "signed_return_bps_15s",
                    "observations": 40,
                    "spearman": 0.62 + batch * 0.01,
                },
                {
                    "research_family": "signed_direction_or_continuation",
                    "feature": "feature_b",
                    "target": "signed_return_bps_15s",
                    "observations": 40,
                    "spearman": 0.58 + batch * 0.01,
                },
                {
                    "research_family": "signed_direction_or_continuation",
                    "feature": "feature_c",
                    "target": "signed_return_bps_15s",
                    "observations": 40,
                    "spearman": -0.10 + batch * 0.01,
                },
            ],
            "feature_redundancy": {
                "pairs": [
                    {
                        "left_feature": "feature_a",
                        "right_feature": "feature_b",
                        "observations": 40,
                        "spearman": 0.91 + batch * 0.01,
                    },
                    {
                        "left_feature": "feature_a",
                        "right_feature": "feature_c",
                        "observations": 40,
                        "spearman": 0.12,
                    },
                ]
            },
            "observations": observations,
        }
        path = root / f"report_{batch}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_aggregates_by_independent_batch_and_controls_redundancy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = [self._report(root, batch) for batch in range(3)]
            report = aggregate_market_state_reports(
                paths,
                minimum_independent_batches=3,
                minimum_association_observations=20,
                redundancy_abs_spearman_threshold=0.80,
            )
        self.assertEqual(report["experiment"], "regime_research_v1_market_state_aggregate")
        self.assertEqual(report["independent_batch_count"], 3)
        self.assertEqual(report["dependence_cluster"], "capture batch")
        stable = [row for row in report["association_summary"] if row["feature"] == "feature_a"][0]
        self.assertTrue(stable["stable_sign_across_batches"])
        self.assertEqual(stable["dominant_sign"], "positive")
        self.assertIn(["feature_a", "feature_b"], report["feature_redundancy"]["clusters"])
        self.assertEqual(report["feature_redundancy"]["representatives"]["cluster_1"], "feature_a")
        incremental = [row for row in report["incremental_information"] if row["feature"] == "feature_b"]
        self.assertEqual(len(incremental), 1)
        self.assertEqual(incremental[0]["control_feature"], "feature_a")
        self.assertFalse(report["claims"]["strategy_pnl_used"])
        self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])

    def test_duplicate_batch_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self._report(root, 0, batch_id="same-batch")
            second = self._report(root, 1, batch_id="same-batch")
            with self.assertRaises(MarketStateAggregateError):
                aggregate_market_state_reports([first, second], minimum_independent_batches=2)


if __name__ == "__main__":
    unittest.main()

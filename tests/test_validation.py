from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.validation import build_validation_report


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Path(self.tmp.name) / "registry.json"
        self.observations = Path(self.tmp.name) / "observations.jsonl"
        self.candidate = {"candidate_id": "P1", "timeframe": "1m", "setup_family": "test",
                          "direction": "long", "path": ["S2"],
                          "numeric_filters": [{"field": "rvol", "op": ">=", "value": 1.0}],
                          "spent_through": "2026-08-22T18:01:00Z", "frozen_at": "2026-09-01T00:00:00Z",
                          "minimum_events": 1, "minimum_active_days": 1}
        self.registry.write_text(json.dumps({"candidates": [self.candidate]}))
        # Synthetic fixtures exercise auditing only; the report can never certify them.
        self.row = {"observation_id": "test-1", **{k: self.candidate[k] for k in
                    ("candidate_id", "timeframe", "setup_family", "direction", "path", "numeric_filters")},
                    "event_time": "2026-09-02T00:00:00Z", "outcome_time": "2026-09-02T00:05:00Z",
                    "features": {"rvol": 1.1}, "source_kind": "real_market", "gross_return_r": 2.0,
                    "cost_r": 0.2, "cost_model_id": "fixture-v1",
                    "cost_components_r": {"fees": 0.05, "slippage": 0.10, "spread": 0.05, "other": 0.0}}

    def audit(self, rows=None, coverage="2026-09-10T00:00:00Z"):
        self.observations.write_text("\n".join(json.dumps(row) for row in (rows if rows is not None else [self.row])))
        return build_validation_report(self.registry, self.observations, observed_through=coverage,
                                       now=datetime(2026, 9, 11, tzinfo=timezone.utc))

    def test_report_hashes_inputs_deducts_costs_and_never_certifies_edge(self):
        report = self.audit()
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["observations_sha256"], hashlib.sha256(self.observations.read_bytes()).hexdigest())
        self.assertAlmostEqual(report["candidates"][0]["summary"]["mean_r"], 1.8)
        self.assertTrue(report["candidates"][0]["windows"][0]["complete"])
        self.assertFalse(report["candidates"][0]["windows"][-1]["complete"])
        self.assertEqual(report["candidates"][0]["cost_provenance"]["model_ids"], ["fixture-v1"])
        self.assertAlmostEqual(report["candidates"][0]["cost_provenance"]["mean_cost_r"], 0.2)
        self.assertFalse(report["deployment_eligible"])
        self.assertFalse(report["verified_out_of_sample_evidence"])

    def test_dependence_diagnostics_expose_overlapping_bursts_and_daily_clusters(self):
        row2 = deepcopy(self.row)
        row2.update(observation_id="test-2", event_time="2026-09-02T00:01:00Z",
                    outcome_time="2026-09-02T00:06:00Z", gross_return_r=-0.8)
        row3 = deepcopy(self.row)
        row3.update(observation_id="test-3", event_time="2026-09-03T00:00:00Z",
                    outcome_time="2026-09-03T00:05:00Z", gross_return_r=1.2)
        report = self.audit([self.row, row2, row3])
        candidate = report["candidates"][0]
        self.assertEqual(candidate["dependence"]["active_days"], 2)
        self.assertEqual(candidate["dependence"]["overlap_count"], 1)
        self.assertEqual(candidate["dependence"]["max_concurrent_outcomes"], 2)
        self.assertEqual(candidate["dependence"]["daily_cluster_summary"]["n"], 2)
        self.assertAlmostEqual(candidate["summary"]["mean_r"], 0.6)
        self.assertAlmostEqual(candidate["dependence"]["daily_cluster_summary"]["mean_r"], 0.7)
        self.assertFalse(report["verified_out_of_sample_evidence"])

    def test_modified_rules_invalid_costs_and_unfresh_events_rejected(self):
        changes = ({"path": []}, {"numeric_filters": []}, {"features": {"rvol": 0.9}},
                   {"direction": "short"}, {"event_time": "2026-08-25T00:00:00Z"},
                   {"outcome_time": "2026-09-11T00:00:00Z"}, {"source_kind": "synthetic"},
                   {"cost_r": -1}, {"gross_return_r": float("nan")}, {"cost_r": True},
                   {"cost_model_id": ""}, {"cost_components_r": {"fees": 0.1}},
                   {"cost_components_r": {"fees": -0.05, "slippage": 0.2, "spread": 0.05, "other": 0.0}},
                   {"cost_components_r": {"fees": 0.01, "slippage": 0.01, "spread": 0.01, "other": 0.0}},
                   {"cost_r": 0.0, "cost_components_r": {"fees": 0.0, "slippage": 0.0, "spread": 0.0, "other": 0.0}})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.audit([{**self.row, **change}])

    def test_multiple_cost_models_are_exposed_not_silently_blended(self):
        row2 = deepcopy(self.row)
        row2.update(observation_id="test-2", event_time="2026-09-03T00:00:00Z",
                    outcome_time="2026-09-03T00:05:00Z", cost_model_id="fixture-stress-v2",
                    cost_r=0.4, cost_components_r={"fees": 0.05, "slippage": 0.25, "spread": 0.10, "other": 0.0})
        report = self.audit([self.row, row2])
        provenance = report["candidates"][0]["cost_provenance"]
        self.assertEqual(provenance["model_ids"], ["fixture-stress-v2", "fixture-v1"])
        self.assertEqual(provenance["observations"], 2)
        self.assertAlmostEqual(provenance["min_cost_r"], 0.2)
        self.assertAlmostEqual(provenance["mean_cost_r"], 0.3)
        self.assertAlmostEqual(provenance["max_cost_r"], 0.4)

    def test_duplicate_and_out_of_order_records_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.audit([self.row, self.row])
        earlier = {**self.row, "observation_id": "test-2", "event_time": "2026-09-01T01:00:00Z"}
        with self.assertRaisesRegex(ValueError, "chronological"):
            self.audit([self.row, earlier])

    def test_future_coverage_and_duplicate_registry_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "future"):
            self.audit(coverage="2026-09-12T00:00:00Z")
        self.registry.write_text(json.dumps({"candidates": [self.candidate, self.candidate]}))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.audit()

    def test_empty_input_preserves_empty_windows_without_evidence(self):
        report = self.audit([])
        self.assertEqual(report["observation_count"], 0)
        self.assertTrue(all(not w["complete"] for w in report["candidates"][0]["windows"]))
        self.assertEqual(report["candidates"][0]["dependence"]["active_days"], 0)
        self.assertEqual(report["candidates"][0]["dependence"]["overlap_count"], 0)
        self.assertEqual(report["candidates"][0]["cost_provenance"]["model_ids"], [])
        self.assertIsNone(report["candidates"][0]["cost_provenance"]["mean_cost_r"])

    def test_duplicate_json_keys_rejected(self):
        self.observations.write_text('{"candidate_id":"P1","candidate_id":"P2"}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            build_validation_report(self.registry, self.observations, observed_through="2026-09-10T00:00:00Z")

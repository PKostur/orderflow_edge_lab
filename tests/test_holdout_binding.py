import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.candidate_freeze import build_candidate_freeze
from orderflow_edge_lab.holdout_audit import HoldoutAuditError, build_holdout_audit, verify_holdout_audit
from orderflow_edge_lab.promotion_binding import assess_bound_promotion
from orderflow_edge_lab.research_protocol import build_research_freeze
from orderflow_edge_lab.trial_ledger import append_holdout_trial, new_trial_ledger


class HoldoutBindingTests(unittest.TestCase):
    def fixture(self, root: Path):
        source = root / "source.csv"
        source.write_bytes(b"immutable-market-data")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()

        audit = {
            "schema_version": 2,
            "source_file": str(source),
            "source_sha256": source_sha,
            "rows": 100,
            "symbols": ["NQ"],
            "timestamps": {
                "minimum": "2026-01-01T00:00:00+00:00",
                "maximum": "2026-03-31T23:59:59+00:00",
            },
            "research_eligibility": {"trade_flow": True, "bbo_ofi": True},
        }
        audit_path = root / "audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        research = build_research_freeze(
            [(audit_path, audit)],
            discovery_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 2, 28, tzinfo=timezone.utc),
            holdout_end=datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc),
            embargo_seconds=60,
            protocol_name="binding-test",
        )
        research_path = root / "research.json"
        research_path.write_text(json.dumps(research), encoding="utf-8")

        candidate = {
            "candidate_id": "P1",
            "timeframe": "1m",
            "setup_family": "ofi",
            "direction": "long",
            "path": ["signal", "entry"],
            "numeric_filters": [],
        }
        registry = {"candidates": [candidate]}
        registry_path = root / "candidates.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        freeze = build_candidate_freeze(
            registry_path,
            research_path,
            candidate_ids=["P1"],
            now=datetime(2026, 2, 20, tzinfo=timezone.utc),
        )
        freeze_path = root / "candidate-freeze.json"
        freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
        return source, source_sha, registry_path, freeze_path, freeze

    def write_observations(self, root: Path, source_sha: str, *, event="2026-03-10T12:00:00+00:00"):
        rows = [{
            "candidate_id": "P1",
            "observation_id": "obs-1",
            "event_time": event,
            "outcome_time": "2026-03-10T12:05:00+00:00",
            "source_provenance": {"dataset_sha256": source_sha, "record_id": "r1"},
        }]
        path = root / "observations.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def write_ledger(self, root: Path, holdout: dict):
        ledger = new_trial_ledger(
            family_name="binding-test-family",
            alpha=0.05,
            now=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        ledger = append_holdout_trial(
            ledger,
            holdout,
            now=datetime(2026, 4, 1, 0, 1, tzinfo=timezone.utc),
        )
        path = root / "trial-ledger.json"
        path.write_text(json.dumps(ledger), encoding="utf-8")
        return path, ledger

    def test_holdout_audit_binds_source_and_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, source_sha, _, freeze_path, _ = self.fixture(root)
            observations = self.write_observations(root, source_sha)
            manifest = build_holdout_audit(
                observations,
                freeze_path,
                "P1",
                source_files=[source],
                now=datetime(2026, 4, 1, tzinfo=timezone.utc),
            )
            self.assertTrue(verify_holdout_audit(manifest))
            self.assertTrue(manifest["claims"]["holdout_partition_respected"])
            self.assertTrue(manifest["claims"]["source_bytes_reverified"])
            self.assertFalse(manifest["claims"]["verified_out_of_sample_evidence"])
            self.assertEqual(manifest["observations"]["candidate_rows"], 1)

    def test_holdout_event_before_frozen_boundary_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, source_sha, _, freeze_path, _ = self.fixture(root)
            observations = self.write_observations(root, source_sha, event="2026-02-10T12:00:00+00:00")
            with self.assertRaisesRegex(HoldoutAuditError, "outside frozen holdout"):
                build_holdout_audit(observations, freeze_path, "P1", source_files=[source])

    def test_changed_source_bytes_fail_holdout_reverification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, source_sha, _, freeze_path, _ = self.fixture(root)
            observations = self.write_observations(root, source_sha)
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(HoldoutAuditError, "dataset hashes"):
                build_holdout_audit(observations, freeze_path, "P1", source_files=[source])

    def test_promotion_binding_matches_exact_observations_registry_and_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, source_sha, registry_path, freeze_path, _ = self.fixture(root)
            observations = self.write_observations(root, source_sha)
            holdout = build_holdout_audit(observations, freeze_path, "P1", source_files=[source])
            holdout_path = root / "holdout.json"
            holdout_path.write_text(json.dumps(holdout), encoding="utf-8")
            ledger_path, _ = self.write_ledger(root, holdout)

            report = {
                "schema_version": 7,
                "deployment_eligible": True,
                "verified_out_of_sample_evidence": True,
                "causal_window_summaries": True,
                "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
                "observations_sha256": hashlib.sha256(observations.read_bytes()).hexdigest(),
                "observation_count": 1,
                "source_verification": {
                    "verified_against_local_files": True,
                    "files": [{"path": str(source), "sha256": source_sha}],
                },
                "candidates": [{
                    "candidate_id": "P1",
                    "windows": [{
                        "complete": True,
                        "matured_event_count": 1,
                        "matured_active_days": 1,
                        "summary": {"n": 1},
                    }],
                    "summary": {"n": 1},
                    "source_provenance": {"unique_records": 1},
                    "return_provenance": {"observations_recomputed": 1},
                    "cost_provenance": {"observations": 1},
                }],
            }
            report_path = root / "validation.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            economics_path = root / "economics.json"
            economics_path.write_text(json.dumps({"account_equity": 10000}), encoding="utf-8")

            assessment, reasons = assess_bound_promotion(
                report_path, "P1", economics_path, freeze_path, holdout_path, ledger_path
            )
            self.assertTrue(assessment.promotable)
            self.assertEqual(reasons, ())

            report["observations_sha256"] = "0" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            assessment, reasons = assess_bound_promotion(
                report_path, "P1", economics_path, freeze_path, holdout_path, ledger_path
            )
            self.assertTrue(assessment.promotable)
            self.assertIn("validation_observations_sha256_mismatch", reasons)

    def test_promotion_rejects_holdout_not_counted_in_trial_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, source_sha, registry_path, freeze_path, _ = self.fixture(root)
            observations = self.write_observations(root, source_sha)
            holdout = build_holdout_audit(observations, freeze_path, "P1", source_files=[source])
            holdout_path = root / "holdout.json"
            holdout_path.write_text(json.dumps(holdout), encoding="utf-8")
            ledger = new_trial_ledger(family_name="binding-test-family", alpha=0.05)
            ledger_path = root / "trial-ledger.json"
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

            report = {
                "schema_version": 7,
                "deployment_eligible": True,
                "verified_out_of_sample_evidence": True,
                "causal_window_summaries": True,
                "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
                "observations_sha256": hashlib.sha256(observations.read_bytes()).hexdigest(),
                "observation_count": 1,
                "source_verification": {"verified_against_local_files": True, "files": [{"path": str(source), "sha256": source_sha}]},
                "candidates": [{
                    "candidate_id": "P1",
                    "windows": [{"complete": True, "matured_event_count": 1, "matured_active_days": 1, "summary": {"n": 1}}],
                    "summary": {"n": 1},
                    "source_provenance": {"unique_records": 1},
                    "return_provenance": {"observations_recomputed": 1},
                    "cost_provenance": {"observations": 1},
                }],
            }
            report_path = root / "validation.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            economics_path = root / "economics.json"
            economics_path.write_text(json.dumps({"account_equity": 10000}), encoding="utf-8")

            assessment, reasons = assess_bound_promotion(
                report_path, "P1", economics_path, freeze_path, holdout_path, ledger_path
            )
            self.assertTrue(assessment.promotable)
            self.assertIn("holdout_trial_not_uniquely_counted", reasons)


if __name__ == "__main__":
    unittest.main()

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.candidate_freeze import (
    CandidateFreezeError,
    build_candidate_freeze,
    reverify_candidate_freeze,
    verify_candidate_freeze,
)
from orderflow_edge_lab.research_protocol import build_research_freeze


class CandidateFreezeTests(unittest.TestCase):
    def fixture(self, root: Path):
        audit_path = root / "audit.json"
        audit = {
            "schema_version": 2,
            "source_file": "source.csv",
            "source_sha256": "a" * 64,
            "rows": 100,
            "symbols": ["NQ"],
            "timestamps": {
                "minimum": "2026-01-01T00:00:00+00:00",
                "maximum": "2026-03-31T23:59:59+00:00",
            },
            "research_eligibility": {"trade_flow": True, "bbo_ofi": True},
        }
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        research = build_research_freeze(
            [(audit_path, audit)],
            discovery_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 2, 28, tzinfo=timezone.utc),
            holdout_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            embargo_seconds=60,
            protocol_name="test",
        )
        research_path = root / "research-freeze.json"
        research_path.write_text(json.dumps(research), encoding="utf-8")
        registry = {
            "candidates": [
                {"candidate_id": "A", "timeframe": "1m", "setup_family": "ofi"},
                {"candidate_id": "B", "timeframe": "5m", "setup_family": "cvd"},
            ]
        }
        registry_path = root / "candidates.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        return registry_path, research_path

    def test_build_and_reverify_candidate_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_path, research_path = self.fixture(Path(directory))
            manifest = build_candidate_freeze(
                registry_path,
                research_path,
                candidate_ids=["A"],
                now=datetime(2026, 2, 20, tzinfo=timezone.utc),
            )
            self.assertTrue(verify_candidate_freeze(manifest))
            self.assertEqual([row["candidate_id"] for row in manifest["candidates"]], ["A"])
            self.assertFalse(manifest["claims"]["verified_out_of_sample_evidence"])
            self.assertFalse(manifest["claims"]["profitable_edge_established"])
            ok, reasons = reverify_candidate_freeze(manifest)
            self.assertTrue(ok)
            self.assertEqual(reasons, ())

    def test_registry_change_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path, research_path = self.fixture(root)
            manifest = build_candidate_freeze(registry_path, research_path)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["candidates"][0]["setup_family"] = "changed"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            ok, reasons = reverify_candidate_freeze(manifest)
            self.assertFalse(ok)
            self.assertIn("candidate_registry_sha256_mismatch", reasons)

    def test_research_freeze_change_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path, research_path = self.fixture(root)
            manifest = build_candidate_freeze(registry_path, research_path)
            research = json.loads(research_path.read_text(encoding="utf-8"))
            research["protocol_name"] = "tampered"
            research_path.write_text(json.dumps(research), encoding="utf-8")
            ok, reasons = reverify_candidate_freeze(manifest)
            self.assertFalse(ok)
            self.assertIn("research_freeze_manifest_invalid", reasons)

    def test_unknown_candidate_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_path, research_path = self.fixture(Path(directory))
            with self.assertRaises(CandidateFreezeError):
                build_candidate_freeze(registry_path, research_path, candidate_ids=["missing"])

    def test_manifest_tampering_fails_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_path, research_path = self.fixture(Path(directory))
            manifest = build_candidate_freeze(registry_path, research_path)
            manifest["candidates"][0]["candidate_id"] = "tampered"
            self.assertFalse(verify_candidate_freeze(manifest))


if __name__ == "__main__":
    unittest.main()

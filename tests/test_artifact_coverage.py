"""Tests for the artifact retention and coverage audit."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.artifact_coverage import (
    ArtifactCoverageError,
    audit_coverage,
    coverage_markdown,
    load_inventory,
    load_requirements,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _requirements(**overrides) -> dict:
    entry = {
        "requirement_id": "req-1",
        "lane": "lane-1",
        "artifact_name": "artifact-a",
        "must_remain_retrievable_through_utc": "2026-10-23T00:00:00Z",
        "max_age_hours": 24.0,
    }
    entry.update(overrides)
    return {
        "schema_version": 1,
        "protocol_name": "test-requirements",
        "requirements": [entry],
    }


def _artifact(name: str = "artifact-a", *, age_hours: float = 1.0, expires_in_hours: float = 720.0) -> dict:
    created = NOW - timedelta(hours=age_hours)
    return {
        "name": name,
        "id": 12345,
        "expired": False,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(hours=expires_in_hours)).isoformat().replace("+00:00", "Z"),
        "size_in_bytes": 1024,
    }


class RequirementsLoadingTests(unittest.TestCase):
    def test_missing_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "req.json"
            payload = _requirements()
            del payload["requirements"][0]["artifact_name"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ArtifactCoverageError, "missing key"):
                load_requirements(path)

    def test_duplicate_requirement_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "req.json"
            payload = _requirements()
            payload["requirements"].append(dict(payload["requirements"][0]))
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ArtifactCoverageError, "duplicate requirement_id"):
                load_requirements(path)

    def test_naive_timestamp_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "req.json"
            payload = _requirements(must_remain_retrievable_through_utc="2026-10-23T00:00:00")
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ArtifactCoverageError, "UTC offset"):
                load_requirements(path)

    def test_shipped_requirements_file_is_valid(self):
        requirements = load_requirements(Path("config/evidence_retention_requirements_v1.json"))
        self.assertGreaterEqual(len(requirements["requirements"]), 1)
        self.assertFalse(requirements["claims"]["counts_prospective_batches"])


class InventoryLoadingTests(unittest.TestCase):
    def test_gh_api_shaped_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inv.json"
            path.write_text(json.dumps({"total_count": 1, "artifacts": [_artifact()]}), encoding="utf-8")
            self.assertEqual(len(load_inventory(path)), 1)

    def test_bare_list_and_jsonlines(self):
        with tempfile.TemporaryDirectory() as directory:
            listed = Path(directory) / "list.json"
            listed.write_text(json.dumps([_artifact()]), encoding="utf-8")
            self.assertEqual(len(load_inventory(listed)), 1)
            lines = Path(directory) / "list.jsonl"
            lines.write_text(json.dumps(_artifact()) + "\n\n" + json.dumps(_artifact()), encoding="utf-8")
            self.assertEqual(len(load_inventory(lines)), 2)

    def test_missing_and_malformed_sources_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ArtifactCoverageError, "not found"):
                load_inventory(Path(directory) / "nope.json")
            broken = Path(directory) / "broken.jsonl"
            broken.write_text("{not json}\n", encoding="utf-8")
            with self.assertRaisesRegex(ArtifactCoverageError, "line 1"):
                load_inventory(broken)

    def test_empty_inventory_file_is_empty_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.json"
            path.write_text("   \n", encoding="utf-8")
            self.assertEqual(load_inventory(path), [])


class AuditTests(unittest.TestCase):
    def test_satisfied_requirement(self):
        report = audit_coverage(_requirements(), [_artifact()], now=NOW)
        self.assertTrue(report["coverage_ok"])
        self.assertEqual(report["requirements_satisfied"], 1)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["highest_severity"], "info")
        self.assertTrue(report["requirements"][0]["retention_covers_required_through"])

    def test_missing_artifact_is_an_error(self):
        report = audit_coverage(_requirements(), [_artifact("other")], now=NOW)
        self.assertFalse(report["coverage_ok"])
        self.assertEqual(report["requirements_open"], 1)
        self.assertEqual(report["findings"][0]["code"], "artifact_missing")
        self.assertEqual(report["findings"][0]["severity"], "error")

    def test_expired_artifact_does_not_count(self):
        expired = dict(_artifact(), expired=True)
        report = audit_coverage(_requirements(), [expired], now=NOW)
        self.assertEqual(report["findings"][0]["code"], "artifact_missing")

    def test_retention_shorter_than_required_through_is_an_error(self):
        report = audit_coverage(_requirements(), [_artifact(expires_in_hours=48.0)], now=NOW)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("artifact_expires_before_required_through", codes)
        self.assertFalse(report["coverage_ok"])

    def test_stale_artifact_is_a_warning_not_a_failure(self):
        report = audit_coverage(_requirements(), [_artifact(age_hours=30.0)], now=NOW)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("artifact_stale", codes)
        self.assertTrue(report["coverage_ok"])
        self.assertEqual(report["highest_severity"], "warning")

    def test_rederivation_horizon_shortfall_is_flagged(self):
        requirement = _requirements(
            recomputable_anchor_utc="2026-06-01T00:00:00Z",
            rederivation_horizon_days=30,
        )
        report = audit_coverage(requirement, [_artifact()], now=NOW)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("rederivation_horizon_exceeded", codes)
        self.assertFalse(report["requirements"][0]["required_through_inside_derivation_horizon"])

    def test_local_paths_are_hashed_and_missing_ones_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "present.json").write_text("{}", encoding="utf-8")
            requirement = _requirements(local_paths=["present.json", "absent.json"])
            report = audit_coverage(requirement, [_artifact()], now=NOW, repo_root=root)
            entry = report["requirements"][0]
            self.assertEqual(entry["local_paths_missing"], ["absent.json"])
            self.assertEqual(
                entry["local_paths_present"][0]["sha256"],
                hashlib.sha256(b"{}").hexdigest(),
            )
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("local_artifact_missing", codes)

    def test_empty_inventory_is_reported_not_silent(self):
        report = audit_coverage(_requirements(), [], now=NOW)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("empty_inventory", codes)
        self.assertIn("artifact_missing", codes)

    def test_claims_self_hash_and_determinism(self):
        first = audit_coverage(_requirements(), [_artifact()], now=NOW)
        second = audit_coverage(_requirements(), [_artifact()], now=NOW)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        claims = first["claims"]
        self.assertFalse(claims["counts_prospective_batches"])
        self.assertFalse(claims["computes_strategy_verdicts"])
        self.assertFalse(claims["extends_or_deletes_artifacts"])
        self.assertFalse(claims["live_order_transmission_supported"])
        canonical = json.dumps(
            {key: value for key, value in first.items() if key != "report_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), first["report_sha256"])

    def test_markdown_renders_requirement_and_findings(self):
        text = coverage_markdown(audit_coverage(_requirements(), [_artifact("other")], now=NOW))
        self.assertIn("artifact-a", text)
        self.assertIn("artifact_missing", text)


if __name__ == "__main__":
    unittest.main()

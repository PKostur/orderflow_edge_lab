import copy
import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.inspection_registry import (
    InspectionRegistryError,
    append_entry,
    entries_digest,
    load_registry,
    registry_markdown,
    validate_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(**overrides):
    entry = {
        "hypothesis_id": "h1",
        "family": "test_family",
        "statement": "test statement",
        "evidence_kind": "prospective",
        "registered_at_utc": "2026-09-22T18:10:00Z",
        "status": "REGISTERED",
        "data_spent": False,
        "id_reusable": True,
        "canonical_record": "config/session_watch_cvd_lny_v1.json",
    }
    entry.update(overrides)
    return entry


def _registry(entries, *, digest=None):
    return {
        "schema_version": 1,
        "version": "test-registry",
        "entries": entries,
        "registry_sha256": digest if digest is not None else entries_digest(list(entries)),
    }


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = REPO_ROOT

    def test_valid_registry_and_spent_windows(self):
        report = validate_registry(_registry([_entry()]), repo_root=self.root)
        self.assertTrue(report["valid"])
        self.assertEqual(report["spent_windows"], [])
        self.assertEqual(report["registered_count"], 1)

    def test_duplicate_identifier_is_an_error(self):
        report = validate_registry(_registry([_entry(), _entry()]), repo_root=self.root)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("hypothesis_id_duplicate", codes)
        self.assertFalse(report["valid"])

    def test_terminal_identifier_cannot_be_reusable(self):
        report = validate_registry(
            _registry([_entry(status="FALSIFIED", data_spent=True, id_reusable=True)]), repo_root=self.root
        )
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("terminal_id_marked_reusable", codes)

    def test_data_spent_must_follow_the_status(self):
        evaluated = validate_registry(
            _registry([_entry(status="EVALUATED", data_spent=False, id_reusable=False)]), repo_root=self.root
        )
        self.assertIn("data_spent_inconsistent", {f["code"] for f in evaluated["findings"]})

        registered = validate_registry(
            _registry([_entry(status="REGISTERED", data_spent=True)]), repo_root=self.root
        )
        self.assertIn("data_spent_before_outcome", {f["code"] for f in registered["findings"]})
        self.assertEqual(registered["highest_severity"], "warning")

    def test_invalid_status_and_kind(self):
        report = validate_registry(
            _registry([_entry(status="MAYBE", evidence_kind="vibes")]), repo_root=self.root
        )
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("status_invalid", codes)
        self.assertIn("evidence_kind_invalid", codes)

    def test_missing_required_field_and_record(self):
        entry = _entry()
        del entry["family"]
        entry["canonical_record"] = "docs/absent.md"
        report = validate_registry(_registry([entry]), repo_root=self.root)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("entry_invalid", codes)
        self.assertIn("canonical_record_missing", codes)

    def test_digest_mismatch_is_an_error(self):
        report = validate_registry(_registry([_entry()], digest="0" * 64), repo_root=self.root)
        self.assertIn("registry_sha256_mismatch", {f["code"] for f in report["findings"]})
        self.assertFalse(report["registry_sha256_matches"])

    def test_load_validation(self):
        with self.assertRaises(InspectionRegistryError):
            load_registry(Path("does/not/exist.json"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "registry.json"
            target.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
            with self.assertRaises(InspectionRegistryError):
                load_registry(target)

    def test_markdown_and_determinism(self):
        registry = _registry([_entry(status="CLOSED", data_spent=True, id_reusable=False)])
        first = validate_registry(registry, repo_root=self.root)
        second = validate_registry(registry, repo_root=self.root)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertFalse(any(first["claims"].values()))
        text = registry_markdown(first)
        self.assertIn("Hypothesis inspection registry", text)
        self.assertIn("CLOSED", text)


class AppendTests(unittest.TestCase):
    def test_append_adds_an_entry_and_refreshes_the_digest(self):
        registry = _registry([_entry()])
        updated = append_entry(registry, _entry(hypothesis_id="h2", status="REGISTERED"))
        self.assertEqual(len(updated["entries"]), 2)
        self.assertEqual(updated["registry_sha256"], entries_digest(updated["entries"]))
        report = validate_registry(updated, repo_root=REPO_ROOT)
        self.assertTrue(report["registry_sha256_matches"])

    def test_append_refuses_a_duplicate_identifier(self):
        registry = _registry([_entry()])
        with self.assertRaisesRegex(InspectionRegistryError, "already registered"):
            append_entry(registry, _entry())

    def test_append_requires_an_identifier(self):
        with self.assertRaises(InspectionRegistryError):
            append_entry(_registry([_entry()]), _entry(hypothesis_id=""))


class RealRegistryTests(unittest.TestCase):
    """Contract test against the committed registry."""

    def setUp(self):
        self.registry = load_registry(REPO_ROOT / "config" / "hypothesis_inspection_registry_v1.json")
        self.report = validate_registry(self.registry, repo_root=REPO_ROOT)

    def test_registry_is_intact(self):
        self.assertTrue(self.report["valid"], msg=json.dumps(self.report["findings"], indent=2))
        self.assertTrue(self.report["registry_sha256_matches"])
        self.assertEqual(self.report["entries_total"], 10)

    def test_terminal_and_open_lanes(self):
        self.assertEqual(self.report["terminal_count"], 5)
        self.assertEqual(self.report["registered_count"], 2)
        open_ids = {
            entry["hypothesis_id"] for entry in self.report["entries"] if entry["status"] == "REGISTERED"
        }
        self.assertEqual(
            open_ids,
            {"session_w3_cvd_lny_wide_range_btc_against", "evidence_v2_cross_strategy_session_forward_v1"},
        )
        for entry in self.report["entries"]:
            if entry["status"] in ("FALSIFIED", "CLOSED"):
                self.assertFalse(entry["id_reusable"])

    def test_spent_windows_cover_the_falsified_lanes(self):
        spent = {record["hypothesis_id"] for record in self.report["spent_windows"]}
        self.assertIn("session_w1_aligned_short_asia_opening", spent)
        self.assertIn("session_w2_aligned_btc_short_asia_opening", spent)
        self.assertIn("ema15m_ema20_50_remembered_tradingview", spent)
        self.assertNotIn("session_w3_cvd_lny_wide_range_btc_against", spent)

    def test_canonical_records_resolve(self):
        for entry in self.report["entries"]:
            self.assertTrue(
                entry["canonical_record_exists"],
                msg=f"{entry['hypothesis_id']} points at a missing record",
            )

    def test_copy_with_a_dropped_entry_is_detected(self):
        tampered = copy.deepcopy(self.registry)
        tampered["entries"] = tampered["entries"][:-1]
        report = validate_registry(tampered, repo_root=REPO_ROOT)
        self.assertFalse(report["registry_sha256_matches"])


if __name__ == "__main__":
    unittest.main()

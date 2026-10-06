"""Adversarial tests for the opt-in v2 forward-operations overlays.

The fixtures are local/offline only: no GitHub API, market-data collector,
schedule, workflow dispatch, external storage, or strategy calculation occurs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from orderflow_edge_lab.contracts_v2 import CLOSED_OPEN, build_file_identity, build_utc_interval
from orderflow_edge_lab.forward_operations_v2 import (
    ForwardOperationsError,
    assess_forward_operations_heartbeat_v2,
    audit_retention_producer_contract_v2,
    build_forward_operations_registry_v2,
    build_retention_inventory_v2,
    build_source_checkpoint_v2,
    build_universe_availability_ledger_v2,
    locate_checkpoint_by_report_sha256_v2,
)
from orderflow_edge_lab.ops_digest import build_ops_digest

ROOT = Path(__file__).resolve().parents[1]
CLOCK_PATH = ROOT / "config/prospective_review_clock_v1.json"
OVERLAY_PATH = ROOT / "config/forward_retention_overlay_v2.json"
REGISTRY_TEMPLATE_PATH = ROOT / "config/forward_operations_registry_template_v2.json"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _identity(root: Path, name: str, content: bytes) -> dict:
    path = root / name
    path.write_bytes(content)
    return build_file_identity(path, logical_name=name)


def _source(ident: dict, *, observed: bool = True, reason: str = "fixture_missing") -> dict:
    return {
        "availability": "OBSERVED" if observed else "MISSING",
        "source_identity": ident if observed else None,
        "reason": None if observed else reason,
    }


class RetentionInventoryTests(unittest.TestCase):
    def test_all_nonterminal_clock_ids_are_mapped_deterministically_with_blocked_external_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identities = {
                "clock_config": _identity(root, "clock.json", CLOCK_PATH.read_bytes()),
                "operational_template": _identity(root, "overlay.json", OVERLAY_PATH.read_bytes()),
            }
            first = build_retention_inventory_v2(
                _json(CLOCK_PATH), _json(OVERLAY_PATH), source_identities=identities, generated_at_utc="2026-10-06T12:00:00Z"
            )
            second = build_retention_inventory_v2(
                _json(CLOCK_PATH), _json(OVERLAY_PATH), source_identities=identities, generated_at_utc="2026-10-06T12:00:00Z"
            )
        self.assertEqual(first, second)
        self.assertEqual(len(first["watches"]), 15)
        self.assertEqual(first["coverage"]["status"], "COMPLETE")
        self.assertTrue(all(row["required_through_utc"] > row["earliest_possible_review_utc"] for row in first["watches"]))
        self.assertTrue(all(row["retention_status"] == "EXTERNAL_IMMUTABLE_COPY_UNVERIFIED" for row in first["watches"]))
        self.assertFalse(first["non_authority_claims"]["external_storage_verified"])

    def test_missing_watch_mapping_fails_closed_and_current_producers_show_activation_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay = _json(OVERLAY_PATH)
            overlay["watches"].pop()
            identities = {
                "clock_config": _identity(root, "clock.json", CLOCK_PATH.read_bytes()),
                "operational_template": _identity(root, "overlay.json", json.dumps(overlay).encode()),
            }
            with self.assertRaisesRegex(ForwardOperationsError, "omits nonterminal"):
                build_retention_inventory_v2(_json(CLOCK_PATH), overlay, source_identities=identities, generated_at_utc="2026-10-06T12:00:00Z")

            inventory = build_retention_inventory_v2(
                _json(CLOCK_PATH), _json(OVERLAY_PATH),
                source_identities={
                    "clock_config": _identity(root, "clock-2.json", CLOCK_PATH.read_bytes()),
                    "operational_template": _identity(root, "overlay-2.json", OVERLAY_PATH.read_bytes()),
                },
                generated_at_utc="2026-10-06T12:00:00Z",
            )
            audit = audit_retention_producer_contract_v2(inventory, repo_root=ROOT)
        self.assertFalse(audit["contract_ok"])
        self.assertIn("required_artifact_not_uploaded", {item["code"] for item in audit["findings"]})
        self.assertIn("producer_retention_not_explicit", {item["code"] for item in audit["findings"]})


class AvailabilityLedgerTests(unittest.TestCase):
    def test_single_symbol_failure_is_data_incomplete_and_recovery_links_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = _identity(root, "universe.json", b'{"symbols":["BTC","ETH"]}')
            price = _identity(root, "price.json", b"price")
            funding = _identity(root, "funding.json", b"funding")
            interval = build_utc_interval("2026-10-06T00:00:00Z", "2026-10-07T00:00:00Z", convention=CLOSED_OPEN)
            failed = build_universe_availability_ledger_v2(
                watch_id="frozen-universe",
                checkpoint_id="first",
                observed_at_utc="2026-10-06T12:00:00Z",
                interval=interval,
                expected_symbols=["BTC", "ETH"],
                symbol_rows=[
                    {"symbol": "BTC", "price": _source(price), "funding": _source(funding), "warmup_sufficient": True, "first_completed_boundary_utc": "2026-10-06T00:00:00Z", "last_completed_boundary_utc": "2026-10-06T08:00:00Z", "error_class": None},
                    {"symbol": "ETH", "price": _source(price), "funding": _source(funding, observed=False, reason="adapter_timeout"), "warmup_sufficient": False, "first_completed_boundary_utc": None, "last_completed_boundary_utc": None, "error_class": "TimeoutError"},
                ],
                universe_identity=universe,
            )
            original = json.dumps(failed, sort_keys=True)
            recovered = build_universe_availability_ledger_v2(
                watch_id="frozen-universe",
                checkpoint_id="second",
                observed_at_utc="2026-10-06T20:00:00Z",
                interval=interval,
                expected_symbols=["BTC", "ETH"],
                symbol_rows=[
                    {"symbol": symbol, "price": _source(price), "funding": _source(funding), "warmup_sufficient": True, "first_completed_boundary_utc": "2026-10-06T00:00:00Z", "last_completed_boundary_utc": "2026-10-06T16:00:00Z", "error_class": None}
                    for symbol in ("BTC", "ETH")
                ],
                universe_identity=universe,
                previous_checkpoint=failed,
            )
        self.assertEqual(failed["coverage_status"], "DATA_INCOMPLETE")
        self.assertLess(failed["coverage_fraction"], 1.0)
        self.assertEqual(recovered["coverage_status"], "COMPLETE")
        self.assertEqual(recovered["coverage_fraction"], 1.0)
        self.assertEqual(recovered["previous_checkpoint"]["checkpoint_sha256"], failed["ledger_sha256"])
        self.assertEqual(json.dumps(failed, sort_keys=True), original)
        self.assertTrue(failed["original_report_preserved"])


class CheckpointTests(unittest.TestCase):
    def _checkpoint_inputs(self, root: Path, source_identity: dict, *, boundaries: list[str], fetched: str, previous=None) -> dict:
        return {
            "watch_id": "watch-a",
            "checkpoint_id": "checkpoint-2" if previous else "checkpoint-1",
            "fetched_at_utc": fetched,
            "bar_seconds": 28800,
            "expected_boundaries_utc": ["2026-10-06T00:00:00Z", "2026-10-06T08:00:00Z", "2026-10-06T16:00:00Z"],
            "sources": [
                {"source_id": "funding:BTC", "symbol": "BTC", "kind": "funding", "availability": "OBSERVED", "source_identity": source_identity, "reason": None, "observed_boundaries_utc": boundaries},
                {"source_id": "price:BTC", "symbol": "BTC", "kind": "price", "availability": "OBSERVED", "source_identity": source_identity, "reason": None, "observed_boundaries_utc": boundaries},
            ],
            "report_identity": _identity(root, "report.json", b"report"),
            "config_identity": _identity(root, "config.json", b"config"),
            "code_identity": _identity(root, "code.py", b"code"),
            "previous_checkpoint": previous,
        }

    def test_open_boundary_excluded_and_missing_closed_boundary_is_checkpointed_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _identity(root, "source-a.json", b"source-a")
            gap = build_source_checkpoint_v2(**self._checkpoint_inputs(root, source, boundaries=["2026-10-06T00:00:00Z"], fetched="2026-10-06T20:00:00Z"))
        self.assertEqual(gap["checkpoint_status"], "DATA_GAP")
        self.assertEqual(gap["open_boundaries_excluded_utc"], ["2026-10-06T16:00:00Z"])
        self.assertIn("funding:BTC@2026-10-06T08:00:00Z", gap["coverage"]["missing_observation_ids"])
        self.assertTrue(gap["original_report_preserved"])

    def test_revision_links_predecessor_and_formal_review_can_locate_original_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _identity(root, "source-a.json", b"source-a")
            first = build_source_checkpoint_v2(**self._checkpoint_inputs(root, source_a, boundaries=["2026-10-06T00:00:00Z"], fetched="2026-10-06T09:00:00Z"))
            source_b = _identity(root, "source-b.json", b"changed historical row")
            second = build_source_checkpoint_v2(**self._checkpoint_inputs(root, source_b, boundaries=["2026-10-06T00:00:00Z"], fetched="2026-10-06T09:00:00Z", previous=first))
            report_hash = next(item["sha256"] for item in first["source_set"]["sources"] if item["source_id"] == "report")
            found = locate_checkpoint_by_report_sha256_v2([first, second], report_hash)
        self.assertEqual(first["checkpoint_status"], "COMPLETE")
        self.assertEqual(second["checkpoint_status"], "REVISED_SOURCE")
        self.assertEqual(len(second["revision_links"]), 2)
        self.assertEqual(found[0]["checkpoint_sha256"], first["checkpoint_sha256"])
        self.assertEqual(found[1]["checkpoint_sha256"], second["checkpoint_sha256"])


class RegistryHeartbeatTests(unittest.TestCase):
    def _registry(self, root: Path) -> dict:
        clock = {
            "watches": [
                {"watch_id": "active", "prospective_start_utc": "2026-10-01T00:00:00Z", "review_gate": {"type": "calendar_days", "minimum_days": 1}},
                {"watch_id": "future", "prospective_start_utc": "2026-11-01T00:00:00Z", "review_gate": {"type": "calendar_days", "minimum_days": 1}},
            ]
        }
        template = {"watches": [
            {"watch_id": "active", "producer_workflow": ".github/workflows/a.yml", "producer_ref": "main", "dispatcher": "existing", "artifact_name": "a", "report_parser": "v2", "cadence_seconds": 3600, "grace_seconds": 600, "boundary_seconds": 3600},
            {"watch_id": "future", "producer_workflow": ".github/workflows/f.yml", "producer_ref": "main", "dispatcher": "existing", "artifact_name": "f", "report_parser": "v2", "cadence_seconds": 3600, "grace_seconds": 600, "boundary_seconds": 3600},
        ]}
        return build_forward_operations_registry_v2(
            clock, template,
            source_identities={"clock_config": _identity(root, "clock.json", b"clock"), "operational_template": _identity(root, "template.json", b"template")},
            generated_at_utc="2026-10-06T12:00:00Z",
        )

    def test_missing_child_is_watch_specific_error_while_prestart_has_no_slo(self):
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = assess_forward_operations_heartbeat_v2(self._registry(Path(directory)), [], now_utc="2026-10-06T12:00:00Z")
        states = {item["watch_id"]: item["state"] for item in heartbeat["watch_statuses"]}
        self.assertEqual(states["active"], "NO_SUCCESSFUL_CHILD_RUN")
        self.assertEqual(states["future"], "PRESTART_NO_SLO")
        self.assertEqual(heartbeat["operational_check_conclusion"], "FAIL")

    def test_active_run_never_dispatches_duplicate_and_nonadvancing_boundary_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = assess_forward_operations_heartbeat_v2(
                self._registry(Path(directory)),
                [{"watch_id": "active", "active_run": True, "last_successful_run_utc": "2026-10-06T11:55:00Z", "artifact_created_at_utc": "2026-10-06T11:55:00Z", "report_as_of_utc": "2026-10-06T11:55:00Z", "latest_completed_boundary_utc": "2026-10-06T08:00:00Z"}],
                now_utc="2026-10-06T12:00:00Z",
            )
        active = next(item for item in heartbeat["watch_statuses"] if item["watch_id"] == "active")
        self.assertEqual(active["recovery_dispatch"], "SUPPRESSED_ACTIVE_RUN")
        self.assertIn("nonadvancing_completed_boundary", active["error_codes"])
        self.assertIn("active_run_no_duplicate_dispatch", {item["code"] for item in heartbeat["findings"]})
        self.assertFalse(heartbeat["claims"]["dispatches_workflows"])


class DigestOperationalHealthTests(unittest.TestCase):
    def test_inventory_failure_and_coverage_error_fail_health_after_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "ledger.json"
            manifest.write_text(json.dumps({"batch_count": 0, "updated_at_utc": "2026-10-06T11:45:00Z"}), encoding="utf-8")
            digest = build_ops_digest(
                clock_config=CLOCK_PATH,
                data_dir=root / "absent",
                ledger_manifest=manifest,
                now=NOW,
                inventory_acquisition={"status": "FAILED", "pages_fetched": 0, "retrieved_at_utc": "2026-10-06T12:00:00Z", "error": "403 actions:read"},
                coverage_report={"requirements_total": 1, "requirements_satisfied": 0, "coverage_ok": False, "report_sha256": "a" * 64, "findings": [{"severity": "error", "code": "artifact_missing", "requirement_id": "watch/report", "detail": "gone"}]},
            )
        self.assertEqual(digest["inventory_acquisition"]["status"], "FAILED")
        self.assertEqual(digest["operational_check_conclusion"], "FAIL")
        self.assertIn("inventory_acquisition_failed", {item["code"] for item in digest["alerts"]})
        self.assertFalse(digest["claims"]["computes_strategy_verdicts"])

    def test_stale_ledger_fails_by_timestamp_not_batch_count_and_fresh_no_growth_is_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            ledger.write_text(json.dumps({"batch_count": 157, "updated_at_utc": "2026-10-06T08:00:00Z"}), encoding="utf-8")
            stale = build_ops_digest(clock_config=CLOCK_PATH, data_dir=root / "absent", ledger_manifest=ledger, now=NOW, ledger_heartbeat_cadence_hours=2, ledger_heartbeat_grace_hours=1)
            ledger.write_text(json.dumps({"batch_count": 157, "updated_at_utc": "2026-10-06T11:45:00Z"}), encoding="utf-8")
            fresh = build_ops_digest(clock_config=CLOCK_PATH, data_dir=root / "absent", ledger_manifest=ledger, now=NOW, ledger_heartbeat_cadence_hours=2, ledger_heartbeat_grace_hours=1)
        self.assertIn("ledger_heartbeat_stale", {item["code"] for item in stale["alerts"]})
        self.assertNotIn("ledger_heartbeat_stale", {item["code"] for item in fresh["alerts"]})
        self.assertEqual(fresh["ledger"]["batch_count"], 157)
        self.assertIsNotNone(fresh["ledger"]["manifest_sha256"])

    def test_malformed_readable_ledger_time_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            ledger.write_text(json.dumps({"batch_count": 1, "updated_at_utc": "2026-10-06T11:45:00"}), encoding="utf-8")
            digest = build_ops_digest(clock_config=CLOCK_PATH, data_dir=root / "absent", ledger_manifest=ledger, now=NOW)
        self.assertIn("ledger_manifest_invalid", {item["code"] for item in digest["alerts"]})
        self.assertEqual(digest["operational_check_conclusion"], "FAIL")


class ModuleCliTests(unittest.TestCase):
    def test_module_cli_builds_inventory_exclusively(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            command = [
                sys.executable, "-m", "orderflow_edge_lab.cli.forward_operations_v2", "retention-inventory",
                "--clock", str(CLOCK_PATH), "--overlay", str(OVERLAY_PATH), "--generated-at", "2026-10-06T12:00:00Z", "--output", str(output),
            ]
            first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(payload["schema"], "orderflow_edge_lab.forward_retention_inventory.v2")


class ExistingWorkflowWiringTests(unittest.TestCase):
    def test_digest_workflow_records_inventory_failure_and_health_gate_after_upload(self):
        workflow = (ROOT / ".github/workflows/wait-window-ops-digest-v1.yml").read_text(encoding="utf-8")
        self.assertIn("inventory_acquisition.json", workflow)
        self.assertNotIn("artifact_inventory.jsonl || true", workflow)
        upload_index = workflow.index("- name: Upload evidence")
        gate_index = workflow.index("- name: Fail confirmed operational health errors after diagnostics upload")
        self.assertGreater(gate_index, upload_index)
        self.assertIn("if: always()", workflow[gate_index: gate_index + 160])
        self.assertIn("operational_check_conclusion", workflow)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.contracts_v2 import canonical_json_sha256
from orderflow_edge_lab.data_integrity_v2 import DataIntegrityV2Error, legacy_inspect_replay_v2, require_prospective_aggregation_eligible_v2
from orderflow_edge_lab.governance_v2 import build_release_profile_v2, load_policy_config, verify_release_profile_v2
from orderflow_edge_lab.release_gates_v2 import (
    MANDATORY_RELEASE_GATES, complete_v2_suite, generated_map_parity, isolated_install_console_smoke, protected_inventory_parity,
)

ROOT = Path(__file__).resolve().parents[1]


def rehash(report):
    report.pop("report_sha256", None)
    report["report_sha256"] = canonical_json_sha256(report)
    return report


class MandatoryReleaseRepairTests(unittest.TestCase):
    def test_actual_protected_inventory_all_535_match(self):
        passed, evidence = protected_inventory_parity(ROOT)
        self.assertTrue(passed, evidence)
        self.assertEqual(evidence["files_matching"], 535)

    def test_modified_protected_bytes_are_reported_and_tampered_inventory_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir()
            shutil.copy2(ROOT / "config/protected_inventory_v2.json", root / "config/protected_inventory_v2.json")
            target = root / "src/orderflow_edge_lab/cli/main.py"
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / "src/orderflow_edge_lab/cli/main.py").read_bytes()+b"\n# forbidden drift\n")
            passed, evidence = protected_inventory_parity(root)
            self.assertFalse(passed)
            row = next(item for item in evidence["mismatches"] if item["path"] == "src/orderflow_edge_lab/cli/main.py")
            self.assertIn("observed_sha256", row)
            (root / "config/protected_inventory_v2.json").write_text("{}\n")
            passed, evidence = protected_inventory_parity(root)
            self.assertFalse(passed)
            self.assertEqual(evidence["error"], "protected_inventory_identity_mismatch")

    def test_real_generated_map_gate_rejects_stale_json_or_markdown(self):
        config = load_policy_config(ROOT / "config/multi_agents_v2.json")
        self.assertTrue(generated_map_parity(ROOT, config)[0])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ["config/multi_agents_v2.json", "docs/governance_map_v2.json", "docs/GOVERNANCE_MAP_V2.md"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, path)
            (root / "docs/governance_map_v2.json").write_text("{}")
            passed, evidence = generated_map_parity(root, config)
            self.assertFalse(passed)
            self.assertFalse(evidence["parity"]["json_map_matches"])
            shutil.copy2(ROOT / "docs/governance_map_v2.json", root / "docs/governance_map_v2.json")
            (root / "docs/GOVERNANCE_MAP_V2.md").write_text("stale")
            self.assertFalse(generated_map_parity(root, config)[0])

    def test_full_v2_discovery_catches_any_failing_module_and_rejects_zero_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tests").mkdir()
            (root / "tests/__init__.py").write_text("")
            (root / "tests/test_v2_hidden.py").write_text("import unittest\nclass Hidden(unittest.TestCase):\n def test_not_in_registry(self):\n  self.fail('must block release')\n")
            passed, evidence = complete_v2_suite(root)
            self.assertFalse(passed)
            self.assertEqual(evidence["tests_run"], 1)
            self.assertIn("must block release", evidence["output_tail"])
            (root / "tests/test_v2_hidden.py").write_text("# no tests\n")
            passed, evidence = complete_v2_suite(root)
            self.assertFalse(passed)
            self.assertEqual(evidence["tests_run"], 0)

    def test_mandatory_failure_blocks_even_warning_only_policy_and_cannot_be_removed(self):
        config = load_policy_config(ROOT / "config/multi_agents_v2.json")
        config.pop("config_sha256")
        config["release_manager"]["block_on"] = ["warning"]
        with patch("orderflow_edge_lab.governance_v2._check", return_value=(True, {"fixture": True})), patch(
            "orderflow_edge_lab.governance_v2.run_mandatory_release_gate", return_value=(False, {"error": "deliberate_adversarial_failure"})
        ) as runner:
            report = build_release_profile_v2(ROOT, config)
        self.assertEqual(runner.call_count, len(MANDATORY_RELEASE_GATES))
        self.assertFalse(report["release_manager"]["release_eligible"])
        self.assertEqual(report["release_manager"]["status"], "blocked")
        self.assertEqual(len(report["release_manager"]["failed_required_checks"]), 4)
        self.assertTrue(verify_release_profile_v2(report))
        forged = deepcopy(report)
        forged["release_manager"].update(release_eligible=True, status="reviewable")
        self.assertFalse(verify_release_profile_v2(rehash(forged)))
        removed = deepcopy(report)
        removed["required_checks"] = [item for item in removed["required_checks"] if not item.startswith("mandatory_release:")]
        removed["checks"] = [item for item in removed["checks"] if not item["check_id"].startswith("mandatory_release:")]
        self.assertFalse(verify_release_profile_v2(rehash(removed)))

    def test_install_gate_fails_without_required_packaging_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            passed, evidence = isolated_install_console_smoke(Path(temp))
            self.assertFalse(passed)
            self.assertEqual(evidence["error"], "packaging_inputs_missing_or_unsafe")

    def test_activation_cannot_be_forged_even_with_recomputed_report_hash(self):
        report = build_release_profile_v2(ROOT, load_policy_config(ROOT / "config/multi_agents_v2.json"), profile="advisory")
        self.assertFalse(report["release_manager"]["activation_eligible"])
        report["release_manager"]["activation_eligible"] = True
        self.assertFalse(verify_release_profile_v2(rehash(report)))


class InspectionAndEntrypointRepairTests(unittest.TestCase):
    def test_v3_receipt_inspection_is_unverified_even_without_terminal_and_cannot_aggregate(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw.jsonl"
            output = Path(temp) / "inspect.jsonl"
            records = [{"record_type": "session", "schema_version": 3},
                       {"record_type": "raw_frame_received", "payload": {"event_type": "depth", "symbol": "A", "received_at_ns": 1}},
                       {"record_type": "raw_frame_received", "payload": {"event_type": "subscription_ack"}}]
            raw.write_text("".join(json.dumps(row)+"\n" for row in records))
            result = legacy_inspect_replay_v2(raw, output)
            self.assertEqual(result["features_emitted"], 1)
            self.assertEqual(result["session"]["verification_status"], "legacy_unverified")
            self.assertEqual(result["session"]["inspection_adapter"], "unverified_v3_receipt_payloads")
            self.assertFalse(result["session"]["prospective_aggregation_eligible"])
            with self.assertRaises(DataIntegrityV2Error):
                require_prospective_aggregation_eligible_v2(result["session"])
            with self.assertRaisesRegex(DataIntegrityV2Error, "overwrite"):
                legacy_inspect_replay_v2(raw, output)

    def test_unknown_inspection_schema_is_rejected_before_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw.jsonl"
            output = Path(temp) / "inspect.jsonl"
            raw.write_text(json.dumps({"record_type": "session", "schema_version": 4})+"\n")
            with self.assertRaisesRegex(DataIntegrityV2Error, "unsupported inspection"):
                legacy_inspect_replay_v2(raw, output)
            self.assertFalse(output.exists())

    def test_paper_wrappers_python_module_help_produces_usage_not_silent_noop(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        for module in ["paper_execution_v2", "paper_replay_v2"]:
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-m", "orderflow_edge_lab.cli."+module, "--help"],
                                        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()

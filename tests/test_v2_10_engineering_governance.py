from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from orderflow_edge_lab.command_registry_v2 import CommandRegistryError, load_command_registry, validate_command_metadata
from orderflow_edge_lab.governance_v2 import (
    GovernanceV2Error,
    build_control_plane_status_v2,
    build_governance_map_v2,
    build_release_profile_v2,
    evaluate_release_policy,
    load_control_plane_contract_v2,
    load_policy_config,
    render_governance_map_markdown,
    validate_policy_config,
    verify_control_plane_status_v2,
    verify_release_profile_v2,
)

ROOT = Path(__file__).resolve().parents[1]


def _fixture_reports() -> tuple[dict, dict, dict, dict]:
    shadow = {"analysis": "universal_session_alignment_prospective_shadow", "watch_id": "watch", "status": "ACCUMULATING",
              "prospective_start_utc": "2026-09-24T00:00:00+00:00", "as_of_utc": "2026-09-24T18:00:00+00:00",
              "evidence_progress": {"all_strategies_ready": False}, "reports": [{"audit_id": "DON8", "ready_for_review": False,
              "evidence_progress": {"completed_trade_count": 0, "open_post_start_snapshot_count": 0, "completed_observed_symbol_count": 0}}]}
    decision = {"analysis": "jev_research_decision_layer_v1", "decision_id": "d1", "provider": "offline_deterministic",
                "provider_resolution": "offline", "model": "none", "state": {"watch_id": "watch"},
                "policy": {"selected_action": "collect_more_evidence", "selection_source": "offline"}}
    action = {"analysis": "jev_research_action_v1", "watch_id": "watch", "decision_id": "d1",
              "authority_boundary": {"changes_frozen_shadow": False, "changes_strategy_rules": False, "changes_positions": False,
                                     "transmits_orders": False, "authorizes_promotion": False, "authorizes_leverage": False},
              "result": {"status": "ACCUMULATE_UNCHANGED"}}
    operational = {"analysis": "universal_shadow_operational_monitor_v1", "watch_id": "watch",
                   "latest_execution_boundary_utc": "2026-09-24T16:00:00+00:00", "execution_boundaries_since_start_including_start": 3,
                   "claims": {"not_prospective_evidence": True}, "strategies": [{"audit_id": "DON8", "current_long_symbol_count": 1,
                   "current_short_symbol_count": 0, "current_flat_symbol_count": 0, "carried_pre_start_position_count": 1,
                   "post_start_position_change_count": 0, "median_position_age_hours": 72.0, "symbols_with_post_start_change": []}]}
    return shadow, decision, action, operational


class GovernanceProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_policy_config(ROOT / "config/multi_agents_v2.json")

    def test_release_has_every_required_check_once_and_is_verifiable(self):
        report = build_release_profile_v2(ROOT, self.config, profile="release")
        self.assertTrue(verify_release_profile_v2(report))
        self.assertEqual(report["release_manager"]["status"], "reviewable")
        self.assertEqual(set(report["required_checks"]), set(report["checks_executed"]))
        self.assertEqual(len(report["required_checks"]), len(report["checks_executed"]))
        self.assertEqual(report["checks_skipped_required"], 0)
        self.assertTrue(all(item["evidence_sha256"] for item in report["checks"]))

    def test_advisory_cannot_be_reviewable_even_when_hashed(self):
        report = build_release_profile_v2(ROOT, self.config, profile="advisory")
        self.assertTrue(verify_release_profile_v2(report))
        self.assertEqual(report["release_manager"]["status"], "not_release_eligible")
        self.assertGreater(report["checks_skipped_required"], 0)
        self.assertFalse(report["release_manager"]["release_eligible"])

    def test_synthetic_authority_holdout_and_targeted_check_violations_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src/orderflow_edge_lab").mkdir(parents=True)
            (root / "pyproject.toml").write_text("dependencies = ['ccxt']\n", encoding="utf-8")
            (root / "src/orderflow_edge_lab/promotion_binding.py").write_text("holdout only", encoding="utf-8")
            policy = {"schema_version": 2, "analysis": "orderflow_edge_lab.multi_agent_policy.v2", "config_id": "synthetic",
                      "agents": [
                        {"id": "execution_safety", "focus": "safety", "logical_role": "test", "required_paths": ["pyproject.toml"], "forbidden_claims": [],
                         "checks": [{"id": "paths", "kind": "path_exists", "severity": "error", "release_only": False, "paths": ["pyproject.toml"]},
                                    {"id": "authority", "kind": "dependency_absent", "severity": "critical", "release_only": False, "dependencies": ["ccxt"]}]},
                        {"id": "research_validity", "focus": "validity", "logical_role": "test", "required_paths": ["src/orderflow_edge_lab/promotion_binding.py"], "forbidden_claims": [],
                         "checks": [{"id": "paths", "kind": "path_exists", "severity": "error", "release_only": False, "paths": ["src/orderflow_edge_lab/promotion_binding.py"]},
                                    {"id": "binding", "kind": "path_contains", "severity": "error", "release_only": False, "paths": ["src/orderflow_edge_lab/promotion_binding.py"], "tokens": ["holdout", "trial_ledger"]}]},
                        {"id": "reliability_observability", "focus": "tests", "logical_role": "test", "required_paths": ["tests/target.py"], "forbidden_claims": [],
                         "checks": [{"id": "targeted", "kind": "path_exists", "severity": "error", "release_only": True, "paths": ["tests/target.py"]}]}
                      ], "release_manager": {"block_on": ["critical", "error"], "require_agents": ["execution_safety", "research_validity", "reliability_observability"]}}
            report = build_release_profile_v2(root, policy)
            failures = set(report["release_manager"]["failed_required_checks"])
            self.assertTrue({"execution_safety:authority", "research_validity:binding", "reliability_observability:targeted"} <= failures)
            self.assertEqual(report["release_manager"]["status"], "blocked")

    def test_declared_warning_policy_not_hard_coded(self):
        warning = [{"severity": "warning", "code": "fixture"}]
        self.assertTrue(evaluate_release_policy(warning, ["warning"])["blocked"])
        self.assertFalse(evaluate_release_policy(warning, ["error"])["blocked"])

    def test_invalid_policy_is_stably_rejected_before_dispatch(self):
        raw = json.loads((ROOT / "config/multi_agents_v2.json").read_text(encoding="utf-8"))
        raw["agents"][1]["id"] = raw["agents"][0]["id"]
        with self.assertRaisesRegex(GovernanceV2Error, "duplicate_agent_id"):
            validate_policy_config(raw)
        raw = json.loads((ROOT / "config/multi_agents_v2.json").read_text(encoding="utf-8"))
        raw["agents"][0]["required_paths"] = ["../escape"]
        with self.assertRaisesRegex(GovernanceV2Error, "unsafe_relative_path"):
            validate_policy_config(raw)
        raw = json.loads((ROOT / "config/multi_agents_v2.json").read_text(encoding="utf-8"))
        raw["release_manager"]["block_on"] = ["catastrophic"]
        with self.assertRaisesRegex(GovernanceV2Error, "unknown_severity"):
            validate_policy_config(raw)


class ControlPlaneContractTests(unittest.TestCase):
    def test_contract_bound_output_has_exact_inputs_and_tamper_detection(self):
        result = build_control_plane_status_v2(*_fixture_reports(), load_control_plane_contract_v2(ROOT / "config/research_control_plane_v2.json"))
        self.assertTrue(verify_control_plane_status_v2(result))
        self.assertEqual(list(result["input_sha256"]), ["action", "decision", "operational", "shadow"])
        self.assertEqual(len(result["input_sha256"]), 4)
        result["status"]["claims"]["live_trading_authorized"] = True
        self.assertFalse(verify_control_plane_status_v2(result))

    def test_forged_authority_and_contract_mutation_are_rejected(self):
        reports = list(_fixture_reports())
        reports[2]["authority_boundary"]["transmits_orders"] = True
        with self.assertRaisesRegex(GovernanceV2Error, "authority_boundary_violated"):
            build_control_plane_status_v2(*reports, load_control_plane_contract_v2(ROOT / "config/research_control_plane_v2.json"))
        contract = load_control_plane_contract_v2(ROOT / "config/research_control_plane_v2.json")
        contract["stage_order"] = contract["stage_order"][:-1]
        with self.assertRaisesRegex(GovernanceV2Error, "contract_hash_mismatch|invalid_control_stages"):
            build_control_plane_status_v2(*_fixture_reports(), contract)


class RegistryAndMapTests(unittest.TestCase):
    def test_command_registry_matches_metadata_and_all_cli_modules(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        modules = {path.stem for path in (ROOT / "src/orderflow_edge_lab/cli").glob("*.py") if path.stem != "__init__"}
        counts = validate_command_metadata(project["scripts"], project.get("gui-scripts", {}), modules)
        self.assertGreater(counts["flat"], 0)
        self.assertIn("orderflow-governance-v2", {entry["name"] for entry in load_command_registry()["commands"]})
        wrong = dict(project["scripts"])
        wrong["orderflow-probe"] = "orderflow_edge_lab.cli.validate:main"
        with self.assertRaises(CommandRegistryError):
            validate_command_metadata(wrong, project.get("gui-scripts", {}), modules)
        with self.assertRaises(CommandRegistryError):
            validate_command_metadata(project["scripts"], project.get("gui-scripts", {}), modules | {"unclassified"})

    def test_committed_governance_map_is_generated_from_registry(self):
        generated = build_governance_map_v2(load_policy_config(ROOT / "config/multi_agents_v2.json"))
        committed = json.loads((ROOT / "docs/governance_map_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, generated)
        self.assertEqual((ROOT / "docs/GOVERNANCE_MAP_V2.md").read_text(encoding="utf-8"), render_governance_map_markdown(generated))
        mutated = copy.deepcopy(generated)
        mutated["deterministic_agents"][0]["agent_id"] = "removed_agent"
        self.assertNotEqual(mutated, committed)


if __name__ == "__main__":
    unittest.main()

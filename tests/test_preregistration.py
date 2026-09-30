import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.preregistration import (
    STATUS_GATES_ONLY,
    STATUS_METRICS_WITHOUT_THRESHOLDS,
    STATUS_PRE_REGISTERED,
    STATUS_REVIEW_RULE_THRESHOLDS,
    PreregistrationError,
    audit_preregistration,
    describe_decision_rule,
    load_registry,
    preregistration_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _canonical_rule():
    return {
        "decision_rule": {
            "metric": "net_mean_bps",
            "direction": ">",
            "threshold": 0.0,
            "inconclusive_when": "the clustered interval includes zero",
        },
        "trial_family": "session_family_v2",
        "design": {
            "dependence_cluster": "capture batch",
            "design_effect_bps": 8.0,
            "design_units": "batches at the frozen gate",
        },
    }


class DescribeDecisionRuleTests(unittest.TestCase):
    def test_canonical_rule_is_pre_registered(self):
        described = describe_decision_rule(_canonical_rule())
        self.assertEqual(described["decision_rule_status"], STATUS_PRE_REGISTERED)
        self.assertEqual(described["decision_rule_shape"], "canonical_decision_rule")
        self.assertTrue(described["has_pre_registered_decision_rule"])
        self.assertEqual(described["trial_family"], "session_family_v2")
        self.assertEqual(described["missing_design_fields"], [])

    def test_incomplete_canonical_rule_is_reported(self):
        described = describe_decision_rule({"decision_rule": {"metric": "x"}})
        self.assertEqual(described["decision_rule_status"], "incomplete_decision_rule")
        self.assertIn("threshold", described["missing_decision_rule_fields"])
        self.assertFalse(described["has_pre_registered_decision_rule"])

    def test_review_rule_thresholds_are_accepted(self):
        described = describe_decision_rule(
            {
                "review_rule": {
                    "no_early_promotion": True,
                    "profit_factor_requires_above": 1.0,
                    "positive_batch_fraction_requires_above": 0.5,
                    "primary_endpoint_requires_positive_cumulative_net_at_4bps": True,
                },
                "primary_review_metrics": ["cumulative_net_bps", "profit_factor"],
            }
        )
        self.assertEqual(described["decision_rule_status"], STATUS_REVIEW_RULE_THRESHOLDS)
        self.assertTrue(described["has_pre_registered_decision_rule"])
        self.assertEqual(described["declared_thresholds"]["profit_factor_requires_above"], 1.0)

    def test_numeric_gates_without_outcome_thresholds_are_not_a_decision_rule(self):
        described = describe_decision_rule(
            {
                "prospective_review_requirement": {
                    "minimum_new_independent_batches": 10,
                    "minimum_new_calendar_days": 5,
                    "evaluate": ["profit_factor", "max_drawdown"],
                }
            }
        )
        self.assertEqual(described["decision_rule_status"], STATUS_GATES_ONLY)
        self.assertFalse(described["has_pre_registered_decision_rule"])
        self.assertEqual(
            described["declared_data_volume_gates"]["prospective_review_requirement.minimum_new_independent_batches"],
            10.0,
        )
        self.assertEqual(described["declared_thresholds"], {})

    def test_metrics_without_any_numeric_content_are_reported(self):
        described = describe_decision_rule({"reporting": {"metrics": ["a", "b"], "review_after_calendar_days": 30}})
        self.assertEqual(described["decision_rule_status"], STATUS_METRICS_WITHOUT_THRESHOLDS)
        self.assertEqual(described["declared_data_volume_gates"], {})
        self.assertEqual(described["declared_metrics"], ["a", "b"])

    def test_absent_rule_is_reported(self):
        described = describe_decision_rule({})
        self.assertEqual(described["decision_rule_status"], "no_decision_rule_declared")
        self.assertEqual(described["decision_rule_shape"], "absent")


class AuditTests(unittest.TestCase):
    def _registry(self, entry, *, config):
        return {
            "schema_version": 1,
            "version": "test",
            "requirements": {"required_trial_family": True},
            "watches": [entry],
            "_config": config,
        }

    def test_unfrozen_gap_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "watch.json").write_text(
                json.dumps({"reporting": {"metrics": ["a"]}}), encoding="utf-8"
            )
            registry = self._registry(
                {"watch_id": "W", "config_path": "config/watch.json"},
                config={},
            )
            report = audit_preregistration(registry, repo_root=root)
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("decision_rule_missing", codes)
            self.assertIn("trial_family_missing", codes)
            self.assertFalse(report["audit_ok"])

    def test_frozen_gap_is_a_documented_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "watch.json").write_text(
                json.dumps({"reporting": {"metrics": ["a"]}}), encoding="utf-8"
            )
            registry = self._registry(
                {
                    "watch_id": "W",
                    "config_path": "config/watch.json",
                    "frozen": True,
                    "acknowledged_gap": {
                        "reason": "window already open",
                        "recorded_at_utc": "2026-09-30T00:00:00Z",
                        "canonical_record": "docs/x.md",
                    },
                },
                config={},
            )
            report = audit_preregistration(registry, repo_root=root)
            severities = {finding["code"]: finding["severity"] for finding in report["findings"]}
            self.assertEqual(severities["decision_rule_missing_in_frozen_watch"], "warning")
            self.assertEqual(severities["acknowledged_gap_recorded"], "info")
            self.assertTrue(report["audit_ok"])
            self.assertEqual(report["acknowledged_gap_count"], 1)

    def test_compliant_watch_produces_no_gap_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config" / "watch.json").write_text(json.dumps(_canonical_rule()), encoding="utf-8")
            registry = self._registry(
                {"watch_id": "W", "config_path": "config/watch.json", "frozen": True},
                config={},
            )
            report = audit_preregistration(registry, repo_root=root)
            self.assertTrue(report["audit_ok"])
            self.assertEqual(report["compliant_count"], 1)
            self.assertEqual([f for f in report["findings"] if f["severity"] == "error"], [])

    def test_missing_config_and_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = {
                "schema_version": 1,
                "version": "test",
                "watches": [
                    {"watch_id": "W", "config_path": "config/nope.json"},
                    {"watch_id": "W", "config_path": "config/nope.json"},
                ],
            }
            report = audit_preregistration(registry, repo_root=root)
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("config_missing", codes)
            self.assertIn("registry_entry_duplicate", codes)
            self.assertFalse(report["audit_ok"])

    def test_determinism_and_self_hash(self):
        registry = load_registry(REPO_ROOT / "config" / "preregistration_registry_v1.json")
        first = audit_preregistration(registry, repo_root=REPO_ROOT)
        second = audit_preregistration(registry, repo_root=REPO_ROOT)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_registry_validation(self):
        with self.assertRaises(PreregistrationError):
            load_registry(Path("does/not/exist.json"))
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text(json.dumps({"schema_version": 2, "watches": []}), encoding="utf-8")
            with self.assertRaises(PreregistrationError):
                load_registry(bad)


class RealRegistryTests(unittest.TestCase):
    """Contract test against the committed registry and watch configs."""

    def setUp(self):
        self.report = audit_preregistration(
            load_registry(REPO_ROOT / "config" / "preregistration_registry_v1.json"),
            repo_root=REPO_ROOT,
        )
        self.by_id = {entry["watch_id"]: entry for entry in self.report["watches"]}

    def test_audit_is_clean_and_every_gap_is_acknowledged(self):
        self.assertTrue(self.report["audit_ok"])
        self.assertEqual(self.report["highest_severity"], "warning")
        self.assertEqual(self.report["watches_total"], 4)  # DON8, W3 development gates, W3, LSK
        self.assertEqual(self.report["frozen_watch_count"], 4)
        self.assertEqual(self.report["acknowledged_gap_count"], 3)

    def test_don8_watch_declares_metrics_without_thresholds(self):
        entry = self.by_id["evidence_v2_cross_strategy_session_forward_v1"]
        self.assertEqual(entry["decision_rule_status"], STATUS_METRICS_WITHOUT_THRESHOLDS)
        self.assertEqual(entry["declared_thresholds"], {})
        self.assertFalse(entry["has_pre_registered_decision_rule"])
        self.assertIn("per_symbol_contribution_bps", entry["declared_metrics"])
        self.assertTrue(entry["acknowledged_gap"])

    def test_w3_watch_carries_numeric_thresholds(self):
        entry = self.by_id["WATCH_CVD_LNY_WIDE_RANGE_BTC_AGAINST_V1"]
        self.assertEqual(entry["decision_rule_status"], STATUS_REVIEW_RULE_THRESHOLDS)
        self.assertTrue(entry["has_pre_registered_decision_rule"])
        self.assertEqual(entry["declared_thresholds"]["profit_factor_requires_above"], 1.0)
        self.assertEqual(entry["declared_thresholds"]["positive_batch_fraction_requires_above"], 0.5)

    def test_session_watch_gates_are_dependence_guards_not_thresholds(self):
        entry = self.by_id["session_development_watch_v1"]
        self.assertEqual(entry["decision_rule_status"], STATUS_GATES_ONLY)
        self.assertIn("declared_data_volume_gates", entry)
        self.assertTrue(any("minimum_new_independent_batches" in key for key in entry["declared_data_volume_gates"]))

    def test_markdown_renders_thresholds_and_requirements(self):
        text = preregistration_markdown(self.report)
        self.assertIn("profit_factor_requires_above=1.0", text)
        self.assertIn("review_rule_numeric_thresholds", text)
        self.assertIn("declared_metrics_only", text)
        self.assertIn("Requirements for watches frozen after this registry", text)


if __name__ == "__main__":
    unittest.main()

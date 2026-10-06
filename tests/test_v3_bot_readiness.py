from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.bot_readiness_v3 import (
    INPUT_SCHEMA,
    NON_AUTHORITY_CLAIMS,
    BotReadinessV3Error,
    build_bot_readiness_report_v3,
    build_report_from_input_v3,
    build_source_provenance_v3,
    main,
    validate_bot_readiness_report_v3,
)


AS_OF = "2027-03-28T12:00:00Z"


def complete_facts():
    return {
        "research_governance": {"frozen_protocol": True, "trial_ledger_bound": True},
        "causal_rules_version": "candidate-v4",
        "causal_rules_executable": True,
        "candidate_frozen_before_new_evidence": True,
        "point_in_time_qualified": True,
        "benchmark_control_declared": True,
        "no_trade_control_declared": True,
        "venue_cost_funding_convention": {"round_trip_cost_bps": 4.0, "funding_convention": "observed venue funding at scheduled interval"},
        "cross_validation": {"chronological": True, "purged": True, "regime_aware": True, "outcome_separated": True},
        "portfolio_limits": {"max_gross_exposure": 0.25, "max_symbol_weight": 0.10},
        "loss_budget": {"amount": 100.0, "currency": "USD", "breach_action": "halt and escalate"},
        "finite_replay": {
            "bounded_start_utc": "2027-03-27T00:00:00Z",
            "bounded_end_utc": "2027-03-28T00:00:00Z",
            "no_order_routing": True,
            "simulated_decisions_no_human": True,
        },
        "restart_replay": {"exactly_once_verified": True, "recovery_rehearsed": True},
        "unattended_fault_controls": {
            "fail_closed": True,
            "stale_source_reject": True,
            "loss_budget_halt": True,
            "human_alert_escalation": True,
        },
        "detached_storage": {"detached_copy_verified": True, "recovery_rehearsed": True, "clock_synchronized": True},
        "user_operated_read_only": True,
        "order_submission_capability": False,
        "qualified_recording": True,
        "recording_point_in_time_verified": True,
        "independent_review": {"review_completed": True, "reviewer_independent": True},
        "operational_risk_security_review": {
            "operations_reviewed": True,
            "risk_reviewed": True,
            "security_reviewed": True,
        },
        "broker_integration_conformance_design": {
            "design_only": True,
            "executable_transmission": False,
            "transaction_payloads_present": False,
        },
    }


def source(*, observed_at_utc=AS_OF, evidence=None, facts=None):
    evidence = evidence or {check: "PASS" for check in (
        "research_governance",
        "versioned_causal_rules",
        "candidate_freeze_before_new_evidence",
        "point_in_time_qualified_data",
        "benchmark_and_no_trade_controls",
        "nonzero_friction_and_venue_conventions",
        "purged_chronological_regime_cross_validation",
        "portfolio_limits_and_loss_budget",
        "finite_autonomous_paper_replay",
        "restart_replay_exactly_once",
        "unattended_fault_controls",
        "detached_storage_recovery_clock",
        "user_operated_read_only_analysis",
        "qualified_recording",
        "independent_promotion_review",
        "operational_risk_security_review",
        "broker_integration_conformance_design",
    )}
    return build_source_provenance_v3(
        source_id="qualified-evidence-001",
        source_type="paper_replay",
        observed_at_utc=observed_at_utc,
        evidence=evidence,
        facts=complete_facts() if facts is None else facts,
    )


class BotReadinessV3Tests(unittest.TestCase):
    def report(self, sources, *, target="S1_FINITE_AUTONOMOUS_PAPER_REPLAY", checks=("finite_autonomous_paper_replay",), age=86400):
        return build_bot_readiness_report_v3(
            sources,
            target_stage=target,
            required_checks=checks,
            assessment_id="readiness-fixture",
            as_of_utc=AS_OF,
            max_source_age_seconds=age,
        )

    def states(self, report):
        return {item["check_id"]: item for item in report["check_states"]}

    def test_empty_provenance_fails_closed_and_never_issues_study_verdicts(self):
        report = self.report([])
        self.assertEqual(report["stage_state"], "PAPER_ENGINEERING_BLOCKED")
        self.assertTrue(all(item["status"] == "MISSING" for item in report["check_states"]))
        self.assertEqual(report["non_authority_claims"], NON_AUTHORITY_CLAIMS)
        self.assertFalse(report["actual_live_capability"])
        self.assertFalse(report["live_order_transmission_supported"])
        self.assertFalse(report["strategy_promotion_authorized"])
        self.assertFalse(report["profitable_edge_established"])
        self.assertFalse(report["verified_out_of_sample_evidence"])
        self.assertEqual(report["watch_verdicts"]["DON8"], "NOT_ISSUED_BY_V3")
        self.assertEqual(report["watch_verdicts"]["W3"], "NOT_ISSUED_BY_V3")
        self.assertEqual(report["watch_verdicts"]["W1"], "TERMINAL_FALSIFIED_NO_RESCUE")
        self.assertTrue(any(item["earliest_review_utc"] == "2027-03-28T00:00:00Z" for item in report["watch_calendar"]))

    def test_complete_s1_evidence_is_paper_engineering_only_not_edge_or_live_authority(self):
        report = self.report([source()])
        self.assertEqual(report["stage_state"], "PAPER_ENGINEERING_READY_LOCAL_ONLY")
        self.assertTrue(all(item["status"] == "PASS" for item in report["check_states"]))
        self.assertEqual(report["non_authority_claims"], NON_AUTHORITY_CLAIMS)
        self.assertFalse(report["non_authority_claims"]["promotion_authorized"])
        self.assertFalse(report["non_authority_claims"]["live_order_transmission_supported"])
        self.assertFalse(report["profitable_edge_established"])
        self.assertFalse(report["verified_out_of_sample_evidence"])
        self.assertEqual(validate_bot_readiness_report_v3(report), report)

    def test_stale_source_and_missing_structured_facts_fail_closed(self):
        stale = source(observed_at_utc="2027-03-27T00:00:00Z")
        report = self.report([stale], age=60)
        self.assertEqual(self.states(report)["finite_autonomous_paper_replay"]["status"], "STALE")
        incomplete = complete_facts()
        incomplete["venue_cost_funding_convention"] = {"round_trip_cost_bps": 0, "funding_convention": ""}
        report = self.report([source(facts=incomplete)])
        self.assertEqual(self.states(report)["nonzero_friction_and_venue_conventions"]["status"], "FAIL")
        self.assertIn("nonzero_friction_and_venue_conventions:fail", report["gaps"])

    def test_unknown_required_check_and_mismatched_provenance_hash_fail_closed(self):
        report = self.report([source()], checks=("finite_autonomous_paper_replay", "future_magic_check"))
        self.assertEqual(self.states(report)["future_magic_check"]["status"], "UNKNOWN")
        self.assertEqual(report["stage_state"], "PAPER_ENGINEERING_BLOCKED")
        corrupted = source()
        corrupted["facts"]["point_in_time_qualified"] = False
        with self.assertRaisesRegex(BotReadinessV3Error, "source_sha256"):
            self.report([corrupted])

    def test_report_self_hash_and_all_false_claims_detect_mutation(self):
        report = self.report([source()])
        bad_hash = deepcopy(report)
        bad_hash["gaps"].append("forged")
        with self.assertRaisesRegex(BotReadinessV3Error, "report_sha256"):
            validate_bot_readiness_report_v3(bad_hash)
        bad_claim = deepcopy(report)
        bad_claim["non_authority_claims"]["strategy_promotion_authorized"] = True
        with self.assertRaisesRegex(BotReadinessV3Error, "non_authority_claims"):
            validate_bot_readiness_report_v3(bad_claim)
        bad_live = deepcopy(report)
        bad_live["actual_live_capability"] = True
        with self.assertRaisesRegex(BotReadinessV3Error, "actual_live_capability"):
            validate_bot_readiness_report_v3(bad_live)

    def test_input_schema_rejects_caller_authority_boolean_instead_of_accepting_it(self):
        assessment = {
            "schema": INPUT_SCHEMA,
            "assessment_id": "strict-input",
            "target_stage": "S0_RESEARCH",
            "as_of_utc": AS_OF,
            "max_source_age_seconds": 60,
            "required_checks": ["research_governance"],
            "source_provenance": [],
            "promotion_authorized": True,
        }
        with self.assertRaisesRegex(BotReadinessV3Error, "unsupported shape"):
            build_report_from_input_v3(assessment)

    def test_s3_design_only_review_can_never_open_live_capability(self):
        report = self.report([source()], target="S3_INDEPENDENT_REVIEW", checks=("broker_integration_conformance_design",))
        self.assertEqual(report["stage_state"], "REVIEW_RECORDS_COMPLETE_NO_AUTHORITY")
        self.assertFalse(report["actual_live_capability"])
        self.assertFalse(report["strategy_promotion_authorized"])
        self.assertEqual(self.states(report)["broker_integration_conformance_design"]["status"], "PASS")


class BotReadinessV3CliTests(unittest.TestCase):
    def test_cli_builds_source_assesses_writes_and_validates_local_json_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsigned = {
                "source_id": "cli-source",
                "source_type": "paper_replay",
                "observed_at_utc": AS_OF,
                "evidence": {"research_governance": "PASS"},
                "facts": {"research_governance": {"frozen_protocol": True, "trial_ledger_bound": True}},
            }
            unsigned_path = root / "unsigned.json"
            unsigned_path.write_text(json.dumps(unsigned), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(["build-source", "--input", str(unsigned_path)]), 0)
            provenance = json.loads(stdout.getvalue())
            readiness_input = {
                "schema": INPUT_SCHEMA,
                "assessment_id": "cli-assessment",
                "target_stage": "S0_RESEARCH",
                "as_of_utc": AS_OF,
                "max_source_age_seconds": 60,
                "required_checks": ["research_governance"],
                "source_provenance": [provenance],
            }
            input_path = root / "input.json"
            report_path = root / "report.json"
            input_path.write_text(json.dumps(readiness_input), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(["assess", "--input", str(input_path), "--output", str(report_path)]), 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["stage_state"], "RESEARCH_CONTROLS_INCOMPLETE")
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(["validate", "--input", str(report_path)]), 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "VALID")

    def test_cli_invalid_input_reports_error_and_never_emits_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("[]", encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["assess", "--input", str(path)]), 2)
            self.assertIn('"status": "INVALID"', stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

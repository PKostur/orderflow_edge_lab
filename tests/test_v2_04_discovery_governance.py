import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.contracts_v2 import (
    build_canonical_source_set, build_coverage_result, build_utc_interval,
    observed_value, missing_value,
)
from orderflow_edge_lab.discovery_governance_v2 import (
    DiscoveryGovernanceV2Error, append_family_ledger_event_v2,
    build_benchmark_assessment_v2, build_benchmark_policy_v2,
    build_candidate_freeze_v2, build_cluster_contract_v2, build_cluster_inference_v2,
    build_cluster_matrix_v2, build_economics_eligibility_v2,
    build_evaluation_binding_v2, build_family_declaration_v2, build_family_ledger_v2,
    build_friction_policy_v2, build_graduation_binding_v2, build_graduation_policy_v2,
    close_family_v2, main, verify_candidate_freeze_v2, verify_family_closure_v2,
    verify_graduation_binding_v2,
)

H = "a" * 64


def source_set():
    return build_canonical_source_set([{"source_id": "fixture-data", "size_bytes": 1, "sha256": H}])


def candidate(candidate_id):
    return {
        "candidate_id": candidate_id,
        "candidate_spec_sha256": ("b" if candidate_id == "A" else "c") * 64,
        "candidate_created_at_utc": "2026-01-01T00:00:00Z",
    }


def declaration():
    return build_family_declaration_v2(
        family_id="family-v2", family_created_at_utc="2026-01-01T00:00:00Z",
        scope={"independence": "D0"}, variant_axes=[{"axis": "threshold"}],
        cost_cases=[{"name": "baseline"}], adaptive_decision_rules=[],
        source_set=source_set(), family_policy_sha256="d" * 64,
    )


def event(kind, candidate_id, at, *, status=None, artifact=None, inspected=None, zero=False):
    return {
        "event_id": f"{kind}-{candidate_id}-{at}", "event_type": kind,
        "candidate_identity": candidate(candidate_id), "recorded_at_utc": at,
        "declared_run_scope_sha256": "e" * 64, "terminal_status": status,
        "result_artifact_sha256": artifact, "result_inspected_at_utc": inspected,
        "zero_trade": zero,
    }


def closed_ledger():
    ledger = build_family_ledger_v2(declaration())
    ledger = append_family_ledger_event_v2(ledger, event("RUN_DECLARED", "A", "2026-01-01T01:00:00Z"))
    ledger = append_family_ledger_event_v2(ledger, event("RUN_DECLARED", "B", "2026-01-01T01:01:00Z"))
    ledger = append_family_ledger_event_v2(ledger, event("RUN_TERMINAL", "A", "2026-01-01T02:00:00Z", status="COMPLETED", artifact="f" * 64, inspected="2026-01-01T02:01:00Z"))
    ledger = append_family_ledger_event_v2(ledger, event("RUN_TERMINAL", "B", "2026-01-01T02:00:00Z", status="FALSIFIED", artifact="1" * 64, inspected="2026-01-01T02:01:00Z", zero=True))
    return ledger


def closure():
    return close_family_v2(closed_ledger(), selected_candidate_identity=candidate("A"), selection_rule_sha256="2" * 64, closure_policy_sha256="3" * 64)


def coverage(missing=False):
    interval = build_utc_interval("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", convention="CLOSED_OPEN")
    return build_coverage_result("quote", interval, [
        {"observation_id": f"q{i}", "observation": missing_value("no quote") if missing and i == 0 else observed_value(1.0)}
        for i in range(4)
    ])


def economics(*, status="clears_declared_screen", values=(5.0, 5.0, 5.0, 5.0), declared=6.0, missing=False):
    policy = build_friction_policy_v2(
        policy_id="p", selected_quantile=0.9, minimum_usable_coverage_fraction=0.75,
        maximum_skipped_fraction=0.25, minimum_usable_quotes_per_required_stratum=1,
        required_strata=["normal"], execution_horizon="1m", fee_provenance_sha256="4" * 64,
    )
    rows = []
    for i, value in enumerate(values):
        rows.append({"quote_id": f"q{i}", "stratum": "normal", "status": "MISSING" if missing and i == 0 else "USABLE", "round_trip_cost_bps": None if missing and i == 0 else value})
    return build_economics_eligibility_v2(source_set=source_set(), friction_policy=policy, quote_coverage=coverage(missing), quote_observations=rows, screen_status=status, report_integrity_ok=True, declared_round_trip_cost_bps=declared, gross_headroom_bps=20.0)


def matrix_and_inference():
    close = closure()
    contract = build_cluster_contract_v2(
        policy_id="clusters", cluster_definition="capture_batch", dataset_manifest_sha256="5" * 64,
        source_set=source_set(), minimum_completed_clusters=4, cscv_partitions=4,
        reality_check_resamples=100, block_length=1, seed=7,
    )
    rows = []
    for cluster in range(4):
        rows += [
            {"candidate_identity": candidate("A"), "cluster_id": f"c{cluster}", "cluster_definition": "capture_batch", "dataset_manifest_sha256": "5" * 64, "net_return_bps": 4.0 + cluster},
            {"candidate_identity": candidate("B"), "cluster_id": f"c{cluster}", "cluster_definition": "capture_batch", "dataset_manifest_sha256": "5" * 64, "net_return_bps": -1.0},
        ]
    matrix = build_cluster_matrix_v2(rows, cluster_contract=contract, family_closure=close)
    return close, matrix, build_cluster_inference_v2(matrix), rows


class LedgerClosureTests(unittest.TestCase):
    def test_preinspection_hash_chain_and_all_sibling_closure(self):
        ledger = closed_ledger()
        close = closure()
        self.assertEqual(close["closure_status"], "CLOSED_VERIFIED")
        self.assertEqual({m["terminal_status"] for m in close["members"]}, {"COMPLETED", "FALSIFIED"})
        self.assertTrue(next(m for m in close["members"] if m["candidate_identity"]["candidate_id"] == "B")["zero_trade"])
        with self.assertRaises(DiscoveryGovernanceV2Error):
            append_family_ledger_event_v2(build_family_ledger_v2(declaration()), event("RUN_TERMINAL", "A", "2026-01-01T02:00:00Z", status="COMPLETED", artifact="f" * 64, inspected="2026-01-01T02:01:00Z"))
        later = append_family_ledger_event_v2(ledger, event("RUN_DECLARED", "C", "2026-01-01T03:00:00Z"))
        with self.assertRaises(DiscoveryGovernanceV2Error):
            verify_family_closure_v2(close, family_ledger=later)

    def test_abandoned_is_visible_and_unterminated_blocks_closure(self):
        ledger = build_family_ledger_v2(declaration())
        ledger = append_family_ledger_event_v2(ledger, event("RUN_DECLARED", "A", "2026-01-01T01:00:00Z"))
        incomplete = close_family_v2(ledger, selected_candidate_identity=candidate("A"), selection_rule_sha256="2" * 64, closure_policy_sha256="3" * 64)
        self.assertEqual(incomplete["closure_status"], "CLOSURE_INCOMPLETE")
        ledger = append_family_ledger_event_v2(ledger, event("RUN_TERMINAL", "A", "2026-01-01T02:00:00Z", status="ABANDONED", inspected="2026-01-01T02:01:00Z"))
        self.assertEqual(ledger["entries"][-1]["terminal_status"], "ABANDONED")
        ledger = closed_ledger()
        ledger = append_family_ledger_event_v2(ledger, event("RUN_DECLARED", "C", "2026-01-01T03:00:00Z"))
        ledger = append_family_ledger_event_v2(ledger, event("RUN_TERMINAL", "C", "2026-01-01T04:00:00Z", status="ABANDONED", inspected="2026-01-01T04:01:00Z"))
        close = close_family_v2(ledger, selected_candidate_identity=candidate("A"), selection_rule_sha256="2" * 64, closure_policy_sha256="3" * 64)
        self.assertEqual(close["closure_status"], "CLOSED_VERIFIED")
        self.assertIn("ABANDONED", {row["terminal_status"] for row in close["members"]})

    def test_module_cli_help_is_executable(self):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = "src"
        completed = subprocess.run(
            [sys.executable, "-m", "orderflow_edge_lab.discovery_governance_v2", "--help"],
            capture_output=True,
            check=False,
            cwd=Path(__file__).parents[1],
            env=environment,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("append-ledger", completed.stdout)


class EconomicsTests(unittest.TestCase):
    def test_failed_indeterminate_missing_and_conservative_floor_are_ineligible(self):
        self.assertFalse(economics(status="fails_declared_screen")["economics_eligible"])
        self.assertFalse(economics(status="indeterminate")["economics_eligible"])
        self.assertFalse(economics(missing=True)["friction_evidence_eligible"])
        report = economics(values=(1.0, 1.0, 100.0, 100.0), declared=10.0)
        self.assertEqual(report["required_round_trip_cost_floor_bps"], 100.0)
        self.assertFalse(report["economics_eligible"])
        strict = build_friction_policy_v2(
            policy_id="strict", selected_quantile=.9, minimum_usable_coverage_fraction=.5,
            maximum_skipped_fraction=0.0, minimum_usable_quotes_per_required_stratum=1,
            required_strata=["normal"], execution_horizon="1m", fee_provenance_sha256="4" * 64,
        )
        skipped = build_economics_eligibility_v2(
            source_set=source_set(), friction_policy=strict, quote_coverage=coverage(),
            quote_observations=[
                {"quote_id": "q0", "stratum": "normal", "status": "SKIPPED", "round_trip_cost_bps": None},
                *[{"quote_id": f"q{i}", "stratum": "normal", "status": "USABLE", "round_trip_cost_bps": 5.0} for i in range(1, 4)],
            ], screen_status="clears_declared_screen", report_integrity_ok=True,
            declared_round_trip_cost_bps=6.0, gross_headroom_bps=20.0,
        )
        self.assertFalse(skipped["friction_evidence_eligible"])
        changed_quantile = build_friction_policy_v2(
            policy_id="strict", selected_quantile=.5, minimum_usable_coverage_fraction=.5,
            maximum_skipped_fraction=0.0, minimum_usable_quotes_per_required_stratum=1,
            required_strata=["normal"], execution_horizon="1m", fee_provenance_sha256="4" * 64,
        )
        self.assertNotEqual(strict["friction_policy_sha256"], changed_quantile["friction_policy_sha256"])

    def test_economics_cli_keeps_report_only_but_require_clear_returns_three(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            payload = {
                "source_set": source_set(), "friction_policy": build_friction_policy_v2(policy_id="p", selected_quantile=.9, minimum_usable_coverage_fraction=.75, maximum_skipped_fraction=.25, minimum_usable_quotes_per_required_stratum=1, required_strata=["normal"], execution_horizon="1m", fee_provenance_sha256="4" * 64), "quote_coverage": coverage(), "quote_observations": [{"quote_id": f"q{i}", "stratum": "normal", "status": "USABLE", "round_trip_cost_bps": 5.0} for i in range(4)], "screen_status": "fails_declared_screen", "report_integrity_ok": True, "declared_round_trip_cost_bps": 6.0, "gross_headroom_bps": 20.0,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(main(["economics", str(path)]), 0)
            self.assertEqual(main(["economics", str(path), "--require-clear"]), 3)


class ClusterBenchmarkGraduationTests(unittest.TestCase):
    def test_clusters_are_rectangular_and_duplicate_subevents_do_not_raise_effective_n(self):
        close, matrix, inference, rows = matrix_and_inference()
        self.assertTrue(inference["inference_eligible"])
        duplicated = build_cluster_matrix_v2(rows + [rows[0]], cluster_contract=matrix["cluster_contract"], family_closure=close)
        self.assertEqual(matrix["effective_cluster_count"], duplicated["effective_cluster_count"])
        bad = list(rows); bad[0] = {**bad[0], "cluster_definition": "day"}
        with self.assertRaises(DiscoveryGovernanceV2Error):
            build_cluster_matrix_v2(bad, cluster_contract=matrix["cluster_contract"], family_closure=close)

    def test_benchmark_explained_return_fails_and_prevents_graduation_and_freeze(self):
        close, matrix, inference, _ = matrix_and_inference()
        policy = build_benchmark_policy_v2(policy_id="bm", benchmark_id="market", formula="same returns", rationale="market exposure", applicability="REQUIRED", requires_positive_incremental_return=True)
        aligned = []
        for row in matrix["matrix"]:
            value = next(cell["cluster_net_return_bps"] for cell in row["candidate_values"] if cell["candidate_identity"]["candidate_id"] == "A")
            aligned.append({"cluster_id": row["cluster_id"], "candidate_net_return_bps": value, "benchmark_net_return_bps": value, "accounting_identity_sha256": "6" * 64, "cost_identity_sha256": "7" * 64, "funding_identity_sha256": "8" * 64})
        benchmark = build_benchmark_assessment_v2(family_closure=close, cluster_matrix=matrix, benchmark_policy=policy, aligned_observations=aligned)
        self.assertFalse(benchmark["benchmark_eligible"])
        evaluation = build_evaluation_binding_v2(candidate_identity=candidate("A"), source_set=source_set(), candidate_result_sha256="9" * 64, dataset_manifest_sha256="5" * 64, code_revision_sha256="0" * 64, gate_config_sha256="a" * 64, controls_sha256="b" * 64, hard_gates={"controls": True, "lookahead": True})
        policy = build_graduation_policy_v2(policy_id="g", required_gate_names=["controls", "lookahead"], allowed_not_applicable_gate_names=[])
        grad = build_graduation_binding_v2(family_closure=close, evaluation_binding=evaluation, economics_eligibility=economics(), cluster_inference=inference, benchmark_assessment=benchmark, graduation_policy=policy)
        self.assertEqual(grad["terminal_state"], "FALSIFIED")
        with self.assertRaises(DiscoveryGovernanceV2Error):
            build_candidate_freeze_v2(graduations=[grad], freeze_created_at_utc="2026-01-02T00:00:00Z", freeze_policy_sha256="c" * 64)

    def test_eligible_graduation_is_the_only_v2_freeze_route_and_tampering_fails(self):
        close, matrix, inference, _ = matrix_and_inference()
        policy = build_benchmark_policy_v2(policy_id="bm", benchmark_id="market", formula="aligned", rationale="beta", applicability="REQUIRED", requires_positive_incremental_return=True)
        aligned = []
        for row in matrix["matrix"]:
            value = next(cell["cluster_net_return_bps"] for cell in row["candidate_values"] if cell["candidate_identity"]["candidate_id"] == "A")
            aligned.append({"cluster_id": row["cluster_id"], "candidate_net_return_bps": value, "benchmark_net_return_bps": 1.0, "accounting_identity_sha256": "6" * 64, "cost_identity_sha256": "7" * 64, "funding_identity_sha256": "8" * 64})
        benchmark = build_benchmark_assessment_v2(family_closure=close, cluster_matrix=matrix, benchmark_policy=policy, aligned_observations=aligned)
        evaluation = build_evaluation_binding_v2(candidate_identity=candidate("A"), source_set=source_set(), candidate_result_sha256="9" * 64, dataset_manifest_sha256="5" * 64, code_revision_sha256="0" * 64, gate_config_sha256="a" * 64, controls_sha256="b" * 64, hard_gates={"controls": True, "lookahead": True})
        policy = build_graduation_policy_v2(policy_id="g", required_gate_names=["controls", "lookahead"], allowed_not_applicable_gate_names=[])
        grad = build_graduation_binding_v2(family_closure=close, evaluation_binding=evaluation, economics_eligibility=economics(), cluster_inference=inference, benchmark_assessment=benchmark, graduation_policy=policy)
        self.assertEqual(grad["terminal_state"], "REPLICATION_PENDING")
        frozen = build_candidate_freeze_v2(graduations=[grad], freeze_created_at_utc="2026-01-02T00:00:00Z", freeze_policy_sha256="c" * 64)
        self.assertTrue(verify_candidate_freeze_v2(frozen))
        grad["candidate_identity"]["candidate_id"] = "registry-bypass"
        with self.assertRaises(DiscoveryGovernanceV2Error):
            verify_graduation_binding_v2(grad)


if __name__ == "__main__":
    unittest.main()

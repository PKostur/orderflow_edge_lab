from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    build_canonical_source_set,
    build_coverage_result,
    build_file_identity,
    build_manifest_result,
    build_source_record,
    build_utc_interval,
    observed_value,
)
from orderflow_edge_lab.validation_binding_v2 import (
    ValidationBindingError,
    append_family_trial_v2,
    bind_validation_promotion_v2,
    bind_evaluation_identity_v2,
    build_cluster_power_design_v2,
    build_evaluation_identity_v2,
    build_evaluation_input_manifest_v2,
    build_family_freeze_v2,
    build_formal_cohort_definition_v2,
    build_formal_cohort_v2,
    build_forward_report_evidence_v2,
    build_run_ledger_v2,
    build_watch_inventory_v2,
    create_family_ledger_v2,
    main,
    powered_mde_v2,
    qualify_legacy_precision_v2,
    validate_family_ledger_v2,
    verify_validation_source_set_v2,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


POLICY = h("frozen-policy")


class raises:
    """Tiny dependency-free replacement for the two expected-error assertions."""

    def __init__(self, expected: type[Exception], match: str) -> None:
        self.expected = expected
        self.match = match

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, traceback: object) -> bool:
        if kind is None or error is None:
            raise AssertionError(f"expected {self.expected.__name__}")
        if not issubclass(kind, self.expected) or self.match not in str(error):
            return False
        return True


def source_set(tmp_path: Path, *names: str) -> tuple[dict, list[dict]]:
    records, paths = [], []
    for name in names:
        file = tmp_path / name
        file.write_text(f"sealed:{name}", encoding="utf-8")
        records.append(build_source_record(name, build_file_identity(file, logical_name=name)))
        paths.append({"source_id": name, "path": str(file)})
    return build_canonical_source_set(records), paths


def family_definition() -> dict:
    return {
        "family_id": "family-v2",
        "candidate_members": [
            {"candidate_id": "a", "candidate_spec_sha256": h("a-spec"), "candidate_freeze_sha256": h("a-freeze")},
            {"candidate_id": "b", "candidate_spec_sha256": h("b-spec"), "candidate_freeze_sha256": h("b-freeze")},
        ],
        "planned_order": ["a", "b"],
        "spending_plan": [{"candidate_id": "a", "allocated_alpha": 0.02}, {"candidate_id": "b", "allocated_alpha": 0.02}],
        "family_wise_alpha": 0.05,
        "tail": "TWO_SIDED",
        "direction": "positive",
        "decision_metric": "mean_return_bps",
        "cluster_power_design_sha256": h("design"),
        "evaluation_evidence_root_sha256": h("root"),
        "discovery_family_manifest_sha256": h("stage04-family"),
        "graduation_binding_sha256": h("stage04-graduation"),
        "holdout_boundary_utc": "2027-02-01T00:00:00Z",
        "committed_at_utc": "2027-01-01T00:00:00Z",
        "policy_sha256": POLICY,
    }


def test_f1_exact_source_set_and_cli_fail_closed(tmp_path: Path) -> None:
    sealed, paths = source_set(tmp_path, "a.json", "b.json")
    report_other, _ = source_set(tmp_path, "other.json")
    mismatch = verify_validation_source_set_v2(sealed, report_other, paths, policy_sha256=POLICY)
    assert mismatch["outcome"] == "INCOMPLETE"
    assert "validation_source_set_mismatch" in mismatch["attributes"]["reasons"]

    ok = verify_validation_source_set_v2(sealed, sealed, paths, policy_sha256=POLICY)
    assert ok["outcome"] == "DIAGNOSTIC_ONLY"
    assert ok["attributes"]["source_files_reverified"] is True
    (tmp_path / "a.json").write_text("changed byte", encoding="utf-8")
    changed = verify_validation_source_set_v2(sealed, sealed, paths, policy_sha256=POLICY)
    assert changed["outcome"] == "INCOMPLETE"
    assert "validation_source_bytes_not_reverified" in changed["attributes"]["reasons"]

    # The module CLI is a real output path and returns nonzero for ineligible bytes.
    for name, value in (("holdout.json", sealed), ("report.json", report_other), ("paths.json", {"paths": paths})):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "source-result_v2.json"
    assert main(["verify-source-set", "--holdout-source-set", str(tmp_path / "holdout.json"), "--report-source-set", str(tmp_path / "report.json"), "--reverification-paths", str(tmp_path / "paths.json"), "--policy-sha256", POLICY, "--output", str(output)]) == 1
    assert json.loads(output.read_text())["outcome"] == "INCOMPLETE"


def test_f2_formal_cohort_blocks_sparse_duplicate_and_unscheduled_returns(tmp_path: Path) -> None:
    sources, _ = source_set(tmp_path, "forward-input.json")
    definition = build_formal_cohort_definition_v2({
        "schema": "orderflow_edge_lab.formal_cohort_definition.v2", "watch_id": "watch", "scoring_interval": build_utc_interval("2027-01-01T00:00:00Z", "2027-01-03T00:00:00Z", convention=CLOSED_OPEN),
        "expected_scoring_dates_utc": ["2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z"],
        "scheduled_runs": [{"run_id": "r1", "scheduled_at_utc": "2027-01-01T01:00:00Z", "scoring_date_utc": "2027-01-01T00:00:00Z"}, {"run_id": "r2", "scheduled_at_utc": "2027-01-02T01:00:00Z", "scoring_date_utc": "2027-01-02T00:00:00Z"}],
        "report_schema": "producer.report.v2", "producer_identity_sha256": h("producer"), "evaluation_evidence_root_sha256": h("root"), "policy_sha256": POLICY,
    })
    report = build_forward_report_evidence_v2({
        "schema": "producer.report.v2", "watch_id": "watch", "report_schema": "producer.report.v2", "as_of_utc": "2027-01-03T00:00:00Z", "producer_identity_sha256": h("producer"), "evaluation_evidence_root_sha256": h("root"), "source_set": sources,
        "returns": [{"scoring_date_utc": "2027-01-01T00:00:00Z", "observation": observed_value(0.0)}],
    })
    ledger = build_run_ledger_v2({"schema": "producer.run_ledger.v2", "watch_id": "watch", "producer_identity_sha256": h("producer"), "runs": [{"run_id": "r1", "scheduled_at_utc": "2027-01-01T01:00:00Z", "conclusion": "SUCCESS"}]})
    sparse = build_formal_cohort_v2(definition, report, ledger, as_of_utc="2027-01-03T00:00:00Z")
    assert sparse["outcome"] == "INCOMPLETE"
    assert sparse["attributes"]["scoring_permitted"] is False
    assert "formal_cohort_return_coverage_incomplete" in sparse["attributes"]["reasons"]
    assert "formal_cohort_scheduled_run_missing" in sparse["attributes"]["reasons"]

    duplicate_report = dict(report)
    duplicate_report["returns"] = [*report["returns"], {"scoring_date_utc": "2027-01-01T00:00:00+00:00", "observation": observed_value(1.0)}]
    duplicate_report = build_forward_report_evidence_v2({key: value for key, value in duplicate_report.items() if key != "report_content_sha256"})
    duplicate = build_formal_cohort_v2(definition, duplicate_report, ledger, as_of_utc="2027-01-03T00:00:00Z")
    assert "formal_cohort_duplicate_normalized_return_date" in duplicate["attributes"]["reasons"]


def test_f3_family_freeze_preholdout_hash_chain_and_nonmember_rejection(tmp_path: Path) -> None:
    sources, _ = source_set(tmp_path, "family.json")
    freeze = build_family_freeze_v2(family_definition(), source_set=sources)
    ledger = create_family_ledger_v2(freeze, created_at_utc="2027-01-15T00:00:00Z")
    ledger = append_family_trial_v2(freeze, ledger, {"candidate_id": "a", "candidate_spec_sha256": h("a-spec"), "candidate_freeze_sha256": h("a-freeze"), "holdout_audit_sha256": h("a-audit"), "validation_report_sha256": h("a-report"), "evaluation_evidence_root_sha256": h("root")}, recorded_at_utc="2027-02-03T00:00:00Z")
    assert validate_family_ledger_v2(freeze, ledger)["outcome"] == "DIAGNOSTIC_ONLY"
    with raises(ValidationBindingError, "next precommitted"):
        append_family_trial_v2(freeze, ledger, {"candidate_id": "x", "candidate_spec_sha256": h("x"), "candidate_freeze_sha256": h("x2"), "holdout_audit_sha256": h("x3"), "validation_report_sha256": h("x4"), "evaluation_evidence_root_sha256": h("root")}, recorded_at_utc="2027-02-03T00:00:00Z")
    with raises(ValidationBindingError, "before the holdout"):
        create_family_ledger_v2(freeze, created_at_utc="2027-02-01T00:00:00Z")
    two_entries = append_family_trial_v2(freeze, ledger, {"candidate_id": "b", "candidate_spec_sha256": h("b-spec"), "candidate_freeze_sha256": h("b-freeze"), "holdout_audit_sha256": h("b-audit"), "validation_report_sha256": h("b-report"), "evaluation_evidence_root_sha256": h("root")}, recorded_at_utc="2027-02-04T00:00:00Z")
    reordered = dict(two_entries)
    reordered["entries"] = list(reversed(two_entries["entries"]))
    assert validate_family_ledger_v2(freeze, reordered)["outcome"] == "INCOMPLETE"


def test_f4_authoritative_inventory_reveals_legacy_and_rejects_unmapped_successor(tmp_path: Path) -> None:
    config = tmp_path / "config.json"; config.write_text("{}", encoding="utf-8")
    identity = build_file_identity(config, logical_name="config.json")
    sources, _ = source_set(tmp_path, "inventory.json", "registry.json")
    inv = {"schema": "orderflow_edge_lab.watch_inventory.v2", "records": [
        {"watch_id": "legacy", "config_path": "config.json", "config_identity": identity, "frozen_at_utc": "2027-01-01T00:00:00Z", "protocol_version": "v1", "state": "OPEN", "expected_review_artifact_id": "legacy-review", "watch_class": "LEGACY"},
        {"watch_id": "new", "config_path": "config.json", "config_identity": identity, "frozen_at_utc": "2027-01-01T00:00:00Z", "protocol_version": "v2", "state": "PRE_START", "expected_review_artifact_id": "new-review", "watch_class": "SUCCESSOR"},
    ]}
    registry = {"schema": "orderflow_edge_lab.watch_registry.v2", "records": []}
    result = build_watch_inventory_v2(inv, registry, sources, policy_sha256=POLICY)
    assert result["outcome"] == "INCOMPLETE"
    assert "inventory_watch_unregistered" in result["attributes"]["reasons"]
    assert {row["status"] for row in result["attributes"]["records"]} >= {"legacy_unregistered", "unregistered"}


def test_f5_evaluator_identity_reverification_and_root_are_deterministic(tmp_path: Path) -> None:
    code = tmp_path / "score.py"; code.write_text("score=1\n", encoding="utf-8")
    config = tmp_path / "eval.json"; config.write_text("{}", encoding="utf-8")
    lock = tmp_path / "lock.txt"; lock.write_text("pkg==1\n", encoding="utf-8")
    inputs, _ = source_set(tmp_path, "input.json")
    code_set = build_canonical_source_set([build_source_record("score.py", build_file_identity(code, logical_name="score.py"))])
    config_set = build_canonical_source_set([build_source_record("eval.json", build_file_identity(config, logical_name="eval.json"))])
    identity = build_evaluation_identity_v2({"implementation_version": "scorer-v2", "git_commit": "commit-A", "git_tree_sha256": h("tree-A"), "evaluator_source_set": code_set, "dependency_lock_identity": build_file_identity(lock, logical_name="lock.txt"), "config_source_set": config_set, "runtime": {"python": "3.11"}, "command": ["evaluate-v2"], "frozen_at_utc": "2027-01-01T00:00:00Z", "window_start_utc": "2027-02-01T00:00:00Z", "policy_sha256": POLICY})
    manifest = build_evaluation_input_manifest_v2(inputs, {"acquisition": h("acq")})
    context = {"git_commit": "commit-A", "git_tree_sha256": h("tree-A"), "runtime": {"python": "3.11"}, "command": ["evaluate-v2"]}
    ok = bind_evaluation_identity_v2(identity, manifest, [{"source_id": "score.py", "path": str(code)}], str(lock), [{"source_id": "eval.json", "path": str(config)}], context)
    assert ok["outcome"] == "DIAGNOSTIC_ONLY"
    assert len(ok["attributes"]["evidence_graph_root_sha256"]) == 64
    assert bind_evaluation_identity_v2(identity, manifest, [{"source_id": "score.py", "path": str(code)}], str(lock), [{"source_id": "eval.json", "path": str(config)}], context)["attributes"]["evidence_graph_root_sha256"] == ok["attributes"]["evidence_graph_root_sha256"]
    code.write_text("score=2\n", encoding="utf-8")
    changed = bind_evaluation_identity_v2(identity, manifest, [{"source_id": "score.py", "path": str(code)}], str(lock), [{"source_id": "eval.json", "path": str(config)}], context)
    assert changed["outcome"] == "INCOMPLETE"
    assert "evaluator_source_bytes_not_reverified" in changed["attributes"]["reasons"]


def test_f6_powered_mde_uses_power_and_legacy_stays_posthoc(tmp_path: Path) -> None:
    sources, _ = source_set(tmp_path, "design.json")
    raw = {"design_id": "day-cluster", "cluster_unit": "CAPTURE_DAY", "cluster_construction_rule": "one independent batch per UTC day", "estimand": "mean_bps", "weighting": "equal cluster", "alpha": 0.05, "tail": "TWO_SIDED", "multiplicity_method": "frozen family", "family_freeze_sha256": h("family"), "desired_power": 0.80, "target_effect_bps": 2.0, "expected_cluster_count": 30, "variance_assumption_bps2": 36.0, "variance_source_sha256": h("variance"), "missing_cluster_policy": "incomplete", "committed_at_utc": "2027-01-01T00:00:00Z", "window_start_utc": "2027-02-01T00:00:00Z", "policy_sha256": POLICY}
    design80 = build_cluster_power_design_v2(raw, source_set=sources)
    mde80 = powered_mde_v2(design80)
    design90 = build_cluster_power_design_v2({**raw, "desired_power": 0.90}, source_set=sources)
    assert powered_mde_v2(design90)["attributes"]["powered_mde_bps"] > mde80["attributes"]["powered_mde_bps"]
    assert mde80["attributes"]["cluster_unit"] == "CAPTURE_DAY"
    legacy = qualify_legacy_precision_v2({"minimum_detectable_effect_bps": 1.25}, sources, policy_sha256=POLICY)
    assert legacy["outcome"] == "DIAGNOSTIC_ONLY"
    assert legacy["attributes"]["post_hoc_precision_half_width_bps"] == 1.25
    assert legacy["attributes"]["promotion_usable"] is False


def test_versioned_promotion_binding_consumes_stage04_manifests_and_rejects_substitution(tmp_path: Path) -> None:
    sources, _ = source_set(tmp_path, "integration.json")
    interval = build_utc_interval("2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z", convention=CLOSED_OPEN)
    coverage = build_coverage_result("one_expected_review", interval, [{"observation_id": "review", "observation": observed_value(0.0)}])
    source_gate = build_manifest_result("validation_source_set_reverification_v2", sources, "DIAGNOSTIC_ONLY", policy_sha256=POLICY, attributes={"source_files_reverified": True})
    cohort = build_manifest_result("formal_cohort_pre_scoring_gate_v2", sources, "COMPLETE", coverage=coverage, policy_sha256=POLICY, attributes={"scoring_permitted": True, "evaluation_evidence_root_sha256": h("root")})
    evaluator = build_manifest_result("evaluation_identity_binding_v2", sources, "DIAGNOSTIC_ONLY", policy_sha256=POLICY, attributes={"identity_reverified": True, "evidence_graph_root_sha256": h("root")})
    discovery = build_manifest_result("discovery_family_v2", sources, "COMPLETE", coverage=coverage, policy_sha256=POLICY, attributes={})
    graduation = build_manifest_result("graduation_binding_v2", sources, "COMPLETE", coverage=coverage, policy_sha256=POLICY, attributes={})
    definition = family_definition()
    definition["discovery_family_manifest_sha256"] = discovery["manifest_sha256"]
    definition["graduation_binding_sha256"] = graduation["manifest_sha256"]
    freeze = build_family_freeze_v2(definition, source_set=sources)
    ledger = append_family_trial_v2(freeze, create_family_ledger_v2(freeze, created_at_utc="2027-01-15T00:00:00Z"), {"candidate_id": "a", "candidate_spec_sha256": h("a-spec"), "candidate_freeze_sha256": h("a-freeze"), "holdout_audit_sha256": h("audit"), "validation_report_sha256": h("report"), "evaluation_evidence_root_sha256": h("root")}, recorded_at_utc="2027-02-03T00:00:00Z")
    bound = bind_validation_promotion_v2(candidate_id="a", source_verification=source_gate, formal_cohort=cohort, evaluation_binding=evaluator, family_freeze=freeze, family_ledger=ledger, discovery_family_manifest=discovery, graduation_binding=graduation)
    assert bound["attributes"]["promotion_binding_complete"] is True
    assert bound["attributes"]["promotion_authorization_granted"] is False
    substituted = build_manifest_result("graduation_binding_v2", sources, "COMPLETE", coverage=coverage, policy_sha256=POLICY, attributes={"replacement": True})
    failed = bind_validation_promotion_v2(candidate_id="a", source_verification=source_gate, formal_cohort=cohort, evaluation_binding=evaluator, family_freeze=freeze, family_ledger=ledger, discovery_family_manifest=discovery, graduation_binding=substituted)
    assert failed["attributes"]["promotion_binding_complete"] is False
    assert "graduation_binding_manifest_mismatch" in failed["attributes"]["reasons"]


if __name__ == "__main__":
    functions = [
        test_f1_exact_source_set_and_cli_fail_closed,
        test_f2_formal_cohort_blocks_sparse_duplicate_and_unscheduled_returns,
        test_f3_family_freeze_preholdout_hash_chain_and_nonmember_rejection,
        test_f4_authoritative_inventory_reveals_legacy_and_rejects_unmapped_successor,
        test_f5_evaluator_identity_reverification_and_root_are_deterministic,
        test_f6_powered_mde_uses_power_and_legacy_stays_posthoc,
        test_versioned_promotion_binding_consumes_stage04_manifests_and_rejects_substitution,
    ]
    for function in functions:
        with tempfile.TemporaryDirectory(prefix="orderflow-v2-validation-") as directory:
            function(Path(directory))
        print(f"PASS {function.__name__}")

"""Opt-in v2 bindings for validation evidence and non-promoting review gates.

This module intentionally leaves every legacy audit, registry, formal review,
robustness report, and promotion path untouched.  It is a prospective contract:
callers must freeze successor definitions before their relevant windows begin and
must explicitly wire these gates before any successor scoring or assessment.

All operations are local/offline.  A successful check proves only explicitly
supplied local bytes and canonical object consistency; it does not prove durable
external storage, provider completeness, independent-engine calibration,
profitability, promotion authority, or live-trading capability.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence

from .contracts_v2 import (
    CLOSED_OPEN,
    FILE_IDENTITY_SCHEMA,
    ContractValidationError,
    build_canonical_source_set,
    build_coverage_result,
    build_manifest_result,
    build_source_record,
    build_utc_interval,
    canonical_json_bytes,
    canonical_json_sha256,
    missing_value,
    non_authority_claims,
    observed_value,
    source_sets_equal,
    validate_canonical_source_set,
    validate_coverage_result,
    validate_file_identity,
    validate_manifest_result,
    validate_observation_value,
    validate_utc_interval,
    verify_file_identity,
)

UTC = timezone.utc
VALIDATION_SCHEMA = "orderflow_edge_lab.validation_binding.v2"
FAMILY_FREEZE_SCHEMA = "orderflow_edge_lab.family_freeze.v2"
FAMILY_LEDGER_SCHEMA = "orderflow_edge_lab.family_ledger.v2"
COHORT_DEFINITION_SCHEMA = "orderflow_edge_lab.formal_cohort_definition.v2"
EVALUATION_IDENTITY_SCHEMA = "orderflow_edge_lab.evaluation_identity.v2"
EVALUATION_INPUT_SCHEMA = "orderflow_edge_lab.evaluation_input_manifest.v2"
CLUSTER_POWER_DESIGN_SCHEMA = "orderflow_edge_lab.cluster_power_design.v2"
_HEX = frozenset("0123456789abcdef")


class ValidationBindingError(ValueError):
    """Raised for malformed, ambiguous, or ineligible successor evidence."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValidationBindingError(f"{field} must be an object with string keys")
    return value


def _exact(raw: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(raw) != expected:
        parts: list[str] = []
        missing = sorted(expected - set(raw))
        extra = sorted(set(raw) - expected)
        if missing:
            parts.append("missing=" + ",".join(missing))
        if extra:
            parts.append("extra=" + ",".join(extra))
        raise ValidationBindingError(f"{field} has unsupported shape ({'; '.join(parts)})")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationBindingError(f"{field} must be a nonempty string")
    return value.strip()


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX for char in value.lower()):
        raise ValidationBindingError(f"{field} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _number(value: object, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValidationBindingError(f"{field} must be a finite number")
    normalized = float(value)
    if positive and normalized <= 0:
        raise ValidationBindingError(f"{field} must be positive")
    if nonnegative and normalized < 0:
        raise ValidationBindingError(f"{field} must be nonnegative")
    return normalized


def _probability(value: object, field: str) -> float:
    normalized = _number(value, field, positive=True)
    if normalized >= 1:
        raise ValidationBindingError(f"{field} must be less than 1")
    return normalized


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationBindingError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationBindingError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationBindingError(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_dt(value: object, field: str) -> datetime:
    return datetime.fromisoformat(_utc(value, field).replace("Z", "+00:00"))


def _json_copy(value: object) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc


def _source_set(value: object, field: str = "source_set") -> dict[str, Any]:
    try:
        return validate_canonical_source_set(_mapping(value, field))
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc


def _manifest_result(
    analysis: str,
    source_set: Mapping[str, Any],
    outcome: str,
    policy_sha256: str,
    attributes: Mapping[str, Any],
    *,
    coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a generic foundation manifest with a stage-specific analysis name."""
    # The foundation correctly forbids ``COMPLETE`` without caller-declared
    # temporal coverage.  Source/code/family design checks have no defensible
    # time grid of their own, so they remain diagnostic-only even when every
    # local identity check succeeds.  Their explicit attributes carry the
    # narrow local verification fact; a formal cohort supplies real coverage.
    effective_outcome = outcome
    effective_attributes = dict(_mapping(attributes, "attributes"))
    if outcome == "COMPLETE" and coverage is None:
        effective_outcome = "DIAGNOSTIC_ONLY"
        effective_attributes["complete_temporal_coverage_not_asserted"] = True
    try:
        return build_manifest_result(
            analysis,
            _source_set(source_set),
            effective_outcome,
            coverage=coverage,
            policy_sha256=_sha(policy_sha256, "policy_sha256"),
            attributes=_json_copy(effective_attributes),
        )
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc


def _self_hash(raw: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    unsigned = dict(raw)
    unsigned.pop(hash_field, None)
    return {**unsigned, hash_field: canonical_json_sha256(unsigned)}


def _validate_self_hash(raw: Mapping[str, Any], hash_field: str, field: str) -> None:
    expected = _sha(raw.get(hash_field), f"{field}.{hash_field}")
    unsigned = dict(raw)
    unsigned.pop(hash_field, None)
    if canonical_json_sha256(unsigned) != expected:
        raise ValidationBindingError(f"{field}.{hash_field} does not match canonical object")


def _file_identity_for_source(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": FILE_IDENTITY_SCHEMA,
        "logical_name": source["source_id"],
        "size_bytes": source["size_bytes"],
        "sha256": source["sha256"],
    }


def _reverify_source_paths(source_set: Mapping[str, Any], file_paths: object, label: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Reverify one exact, bijective source-id/path mapping against a source set."""
    normalized = _source_set(source_set)
    expected = {item["source_id"]: item for item in normalized["sources"]}
    if not isinstance(file_paths, list):
        return [], [f"{label}_reverification_paths_missing"]
    supplied: dict[str, str] = {}
    reasons: list[str] = []
    for index, item in enumerate(file_paths):
        if not isinstance(item, Mapping):
            reasons.append(f"{label}_reverification_entry_invalid")
            continue
        if set(item) != {"source_id", "path"}:
            reasons.append(f"{label}_reverification_entry_shape_invalid")
            continue
        try:
            source_id = _string(item.get("source_id"), f"{label}.paths[{index}].source_id")
            path = _string(item.get("path"), f"{label}.paths[{index}].path")
        except ValidationBindingError:
            reasons.append(f"{label}_reverification_entry_invalid")
            continue
        if source_id in supplied:
            reasons.append(f"{label}_reverification_duplicate_source")
        supplied[source_id] = path
    expected_ids = set(expected)
    supplied_ids = set(supplied)
    if expected_ids - supplied_ids:
        reasons.append(f"{label}_reverification_source_missing")
    if supplied_ids - expected_ids:
        reasons.append(f"{label}_reverification_source_extra")
    results: list[dict[str, Any]] = []
    for source_id in sorted(expected_ids & supplied_ids):
        result = verify_file_identity(supplied[source_id], _file_identity_for_source(expected[source_id]))
        results.append({"source_id": source_id, "verification": result})
        if result["status"] != "VERIFIED_LOCAL_BYTES":
            reasons.append(f"{label}_source_bytes_not_reverified")
    return results, list(dict.fromkeys(reasons))


def verify_validation_source_set_v2(
    holdout_source_set: Mapping[str, Any],
    report_source_set: Mapping[str, Any],
    reverification_paths: Sequence[Mapping[str, Any]],
    *,
    policy_sha256: str,
) -> dict[str, Any]:
    """Fail closed unless sealed holdout, report, and promotion-time bytes match.

    There is deliberately no implicit derivation exception.  A future derivation
    graph must be separately frozen and integrated before it can relax this exact
    equality rule.
    """
    holdout = _source_set(holdout_source_set, "holdout_source_set")
    report = _source_set(report_source_set, "report_source_set")
    reasons: list[str] = []
    try:
        equal = source_sets_equal(holdout, report)
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc
    if not equal:
        reasons.append("validation_source_set_mismatch")
    verifications, verification_reasons = _reverify_source_paths(holdout, list(reverification_paths), "validation")
    reasons.extend(verification_reasons)
    outcome = "COMPLETE" if not reasons else "INCOMPLETE"
    return _manifest_result(
        "validation_source_set_reverification_v2",
        holdout,
        outcome,
        policy_sha256,
        {
            "holdout_source_set_sha256": holdout["source_set_sha256"],
            "report_source_set_sha256": report["source_set_sha256"],
            "source_sets_equal": equal,
            "source_files_reverified": not reasons,
            "reverifications": verifications,
            "reasons": list(dict.fromkeys(reasons)),
            "derivation_graph_exception_applied": False,
            "verification_scope": "exact_local_bytes_only",
        },
    )


def _validate_cohort_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(definition, "cohort_definition")
    expected = {
        "schema",
        "watch_id",
        "scoring_interval",
        "expected_scoring_dates_utc",
        "scheduled_runs",
        "report_schema",
        "producer_identity_sha256",
        "evaluation_evidence_root_sha256",
        "policy_sha256",
        "cohort_definition_sha256",
    }
    _exact(raw, expected, "cohort_definition")
    if raw.get("schema") != COHORT_DEFINITION_SCHEMA:
        raise ValidationBindingError("cohort_definition schema is unsupported")
    try:
        interval = validate_utc_interval(_mapping(raw.get("scoring_interval"), "scoring_interval"))
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc
    if interval["convention"] != CLOSED_OPEN:
        raise ValidationBindingError("formal cohort scoring_interval must use CLOSED_OPEN")
    dates = raw.get("expected_scoring_dates_utc")
    if not isinstance(dates, list) or not dates:
        raise ValidationBindingError("expected_scoring_dates_utc must be a nonempty array")
    normalized_dates = [_utc(item, "expected_scoring_dates_utc") for item in dates]
    if normalized_dates != sorted(normalized_dates) or len(normalized_dates) != len(set(normalized_dates)):
        raise ValidationBindingError("expected_scoring_dates_utc must be sorted and unique after UTC normalization")
    start = _utc_dt(interval["start_utc"], "scoring_interval.start_utc")
    end = _utc_dt(interval["end_utc"], "scoring_interval.end_utc")
    if any(not start <= _utc_dt(date, "expected scoring date") < end for date in normalized_dates):
        raise ValidationBindingError("expected scoring dates must lie inside the declared interval")
    runs = raw.get("scheduled_runs")
    if not isinstance(runs, list) or not runs:
        raise ValidationBindingError("scheduled_runs must be a nonempty array")
    normalized_runs: list[dict[str, str]] = []
    for index, run in enumerate(runs):
        item = _mapping(run, f"scheduled_runs[{index}]")
        _exact(item, {"run_id", "scheduled_at_utc", "scoring_date_utc"}, f"scheduled_runs[{index}]")
        normalized_runs.append(
            {
                "run_id": _string(item.get("run_id"), f"scheduled_runs[{index}].run_id"),
                "scheduled_at_utc": _utc(item.get("scheduled_at_utc"), f"scheduled_runs[{index}].scheduled_at_utc"),
                "scoring_date_utc": _utc(item.get("scoring_date_utc"), f"scheduled_runs[{index}].scoring_date_utc"),
            }
        )
    if normalized_runs != sorted(normalized_runs, key=lambda row: row["run_id"]):
        raise ValidationBindingError("scheduled_runs must be sorted by run_id")
    ids = [row["run_id"] for row in normalized_runs]
    if len(ids) != len(set(ids)):
        raise ValidationBindingError("scheduled_runs.run_id values must be unique")
    if any(row["scoring_date_utc"] not in normalized_dates for row in normalized_runs):
        raise ValidationBindingError("each scheduled run must target a declared scoring date")
    normalized = {
        "schema": COHORT_DEFINITION_SCHEMA,
        "watch_id": _string(raw.get("watch_id"), "cohort_definition.watch_id"),
        "scoring_interval": interval,
        "expected_scoring_dates_utc": normalized_dates,
        "scheduled_runs": normalized_runs,
        "report_schema": _string(raw.get("report_schema"), "cohort_definition.report_schema"),
        "producer_identity_sha256": _sha(raw.get("producer_identity_sha256"), "cohort_definition.producer_identity_sha256"),
        "evaluation_evidence_root_sha256": _sha(raw.get("evaluation_evidence_root_sha256"), "cohort_definition.evaluation_evidence_root_sha256"),
        "policy_sha256": _sha(raw.get("policy_sha256"), "cohort_definition.policy_sha256"),
    }
    expected_hash = canonical_json_sha256(normalized)
    if _sha(raw.get("cohort_definition_sha256"), "cohort_definition.cohort_definition_sha256") != expected_hash:
        raise ValidationBindingError("cohort_definition_sha256 does not match canonical definition")
    return {**normalized, "cohort_definition_sha256": expected_hash}


def build_formal_cohort_definition_v2(
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalize a caller-declared expected scoring-calendar/run definition."""
    raw = _mapping(definition, "cohort_definition")
    candidate = dict(raw)
    candidate.pop("cohort_definition_sha256", None)
    return _validate_cohort_definition(
        {**candidate, "cohort_definition_sha256": canonical_json_sha256(_json_copy(candidate))}
    )


def _validate_forward_report(report: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(report, "forward_report")
    expected = {
        "schema",
        "watch_id",
        "report_schema",
        "as_of_utc",
        "producer_identity_sha256",
        "evaluation_evidence_root_sha256",
        "source_set",
        "returns",
        "report_content_sha256",
    }
    _exact(raw, expected, "forward_report")
    returns = raw.get("returns")
    if not isinstance(returns, list):
        raise ValidationBindingError("forward_report.returns must be an array")
    normalized_returns: list[dict[str, Any]] = []
    for index, entry in enumerate(returns):
        item = _mapping(entry, f"forward_report.returns[{index}]")
        _exact(item, {"scoring_date_utc", "observation"}, f"forward_report.returns[{index}]")
        try:
            observation = validate_observation_value(_mapping(item.get("observation"), "return observation"))
        except ContractValidationError as exc:
            raise ValidationBindingError(str(exc)) from exc
        normalized_returns.append(
            {"scoring_date_utc": _utc(item.get("scoring_date_utc"), "return scoring_date_utc"), "observation": observation}
        )
    unsigned = {
        "schema": _string(raw.get("schema"), "forward_report.schema"),
        "watch_id": _string(raw.get("watch_id"), "forward_report.watch_id"),
        "report_schema": _string(raw.get("report_schema"), "forward_report.report_schema"),
        "as_of_utc": _utc(raw.get("as_of_utc"), "forward_report.as_of_utc"),
        "producer_identity_sha256": _sha(raw.get("producer_identity_sha256"), "forward_report.producer_identity_sha256"),
        "evaluation_evidence_root_sha256": _sha(raw.get("evaluation_evidence_root_sha256"), "forward_report.evaluation_evidence_root_sha256"),
        "source_set": _source_set(raw.get("source_set")),
        "returns": normalized_returns,
    }
    expected_hash = canonical_json_sha256(unsigned)
    if _sha(raw.get("report_content_sha256"), "forward_report.report_content_sha256") != expected_hash:
        raise ValidationBindingError("forward_report.report_content_sha256 does not match canonical report")
    return {**unsigned, "report_content_sha256": expected_hash}


def build_forward_report_evidence_v2(report: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize report evidence for a successor forward producer; this does not score it."""
    raw = _mapping(report, "forward_report")
    candidate = dict(raw)
    candidate.pop("report_content_sha256", None)
    returns = candidate.get("returns")
    if isinstance(returns, list):
        normalized_returns: list[dict[str, Any]] = []
        for entry in returns:
            item = _mapping(entry, "forward_report return")
            normalized_returns.append(
                {
                    "scoring_date_utc": _utc(item.get("scoring_date_utc"), "return scoring_date_utc"),
                    "observation": validate_observation_value(_mapping(item.get("observation"), "return observation")),
                }
            )
        candidate["returns"] = normalized_returns
    if "source_set" in candidate:
        candidate["source_set"] = _source_set(candidate["source_set"])
    return _validate_forward_report({**candidate, "report_content_sha256": canonical_json_sha256(_json_copy(candidate))})


def _validate_run_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(ledger, "run_ledger")
    expected = {"schema", "watch_id", "producer_identity_sha256", "runs", "run_ledger_sha256"}
    _exact(raw, expected, "run_ledger")
    runs = raw.get("runs")
    if not isinstance(runs, list):
        raise ValidationBindingError("run_ledger.runs must be an array")
    normalized_runs: list[dict[str, str]] = []
    for index, entry in enumerate(runs):
        item = _mapping(entry, f"run_ledger.runs[{index}]")
        _exact(item, {"run_id", "scheduled_at_utc", "conclusion"}, f"run_ledger.runs[{index}]")
        normalized_runs.append(
            {
                "run_id": _string(item.get("run_id"), f"run_ledger.runs[{index}].run_id"),
                "scheduled_at_utc": _utc(item.get("scheduled_at_utc"), f"run_ledger.runs[{index}].scheduled_at_utc"),
                "conclusion": _string(item.get("conclusion"), f"run_ledger.runs[{index}].conclusion"),
            }
        )
    unsigned = {
        "schema": _string(raw.get("schema"), "run_ledger.schema"),
        "watch_id": _string(raw.get("watch_id"), "run_ledger.watch_id"),
        "producer_identity_sha256": _sha(raw.get("producer_identity_sha256"), "run_ledger.producer_identity_sha256"),
        "runs": normalized_runs,
    }
    expected_hash = canonical_json_sha256(unsigned)
    if _sha(raw.get("run_ledger_sha256"), "run_ledger.run_ledger_sha256") != expected_hash:
        raise ValidationBindingError("run_ledger.run_ledger_sha256 does not match canonical ledger")
    return {**unsigned, "run_ledger_sha256": expected_hash}


def build_run_ledger_v2(ledger: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(ledger, "run_ledger")
    candidate = dict(raw)
    candidate.pop("run_ledger_sha256", None)
    return _validate_run_ledger({**candidate, "run_ledger_sha256": canonical_json_sha256(_json_copy(candidate))})


def build_formal_cohort_v2(
    cohort_definition: Mapping[str, Any],
    forward_report: Mapping[str, Any],
    run_ledger: Mapping[str, Any],
    *,
    as_of_utc: str,
) -> dict[str, Any]:
    """Validate coverage and exact run identity before any criteria are evaluated.

    The returned object deliberately contains no metrics or verdict.  A caller
    may score only when its ``outcome`` is ``COMPLETE`` and
    ``attributes.scoring_permitted`` is true.
    """
    definition = _validate_cohort_definition(cohort_definition)
    report = _validate_forward_report(forward_report)
    ledger = _validate_run_ledger(run_ledger)
    as_of = _utc_dt(as_of_utc, "as_of_utc")
    reasons: list[str] = []
    if report["watch_id"] != definition["watch_id"]:
        reasons.append("formal_cohort_watch_id_mismatch")
    if report["report_schema"] != definition["report_schema"]:
        reasons.append("formal_cohort_report_schema_mismatch")
    if report["producer_identity_sha256"] != definition["producer_identity_sha256"]:
        reasons.append("formal_cohort_producer_identity_mismatch")
    if report["evaluation_evidence_root_sha256"] != definition["evaluation_evidence_root_sha256"]:
        reasons.append("formal_cohort_evaluation_root_mismatch")
    if ledger["watch_id"] != definition["watch_id"]:
        reasons.append("formal_cohort_run_ledger_watch_mismatch")
    if ledger["producer_identity_sha256"] != definition["producer_identity_sha256"]:
        reasons.append("formal_cohort_run_ledger_identity_mismatch")
    interval = definition["scoring_interval"]
    end = _utc_dt(interval["end_utc"], "cohort interval end")
    if as_of < end:
        reasons.append("formal_cohort_horizon_not_yet_complete")
    if _utc_dt(report["as_of_utc"], "report as_of") > as_of:
        reasons.append("formal_cohort_report_after_as_of")

    expected_dates = definition["expected_scoring_dates_utc"]
    observed_by_date: dict[str, dict[str, Any]] = {}
    for entry in report["returns"]:
        date = entry["scoring_date_utc"]
        if date in observed_by_date:
            reasons.append("formal_cohort_duplicate_normalized_return_date")
            continue
        observed_by_date[date] = entry
        if date not in expected_dates:
            reasons.append("formal_cohort_unscheduled_return_date")
        if _utc_dt(date, "return date") > as_of:
            reasons.append("formal_cohort_return_after_as_of")
    coverage_observations = []
    for date in expected_dates:
        entry = observed_by_date.get(date)
        coverage_observations.append(
            {
                "observation_id": date,
                "observation": entry["observation"] if entry is not None else missing_value("scheduled_return_not_present"),
            }
        )
    try:
        coverage = build_coverage_result("formal_cohort_returns_v2", interval, coverage_observations)
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc
    if coverage["status"] != "COMPLETE":
        reasons.append("formal_cohort_return_coverage_incomplete")

    expected_runs = {row["run_id"]: row for row in definition["scheduled_runs"]}
    actual_runs: dict[str, dict[str, str]] = {}
    for row in ledger["runs"]:
        run_id = row["run_id"]
        if run_id in actual_runs:
            reasons.append("formal_cohort_duplicate_run_id")
            continue
        actual_runs[run_id] = row
        expected = expected_runs.get(run_id)
        if expected is None:
            reasons.append("formal_cohort_unscheduled_run")
            continue
        if row["scheduled_at_utc"] != expected["scheduled_at_utc"]:
            reasons.append("formal_cohort_run_schedule_mismatch")
        if row["conclusion"] != "SUCCESS":
            reasons.append("formal_cohort_run_not_successful")
    if set(expected_runs) - set(actual_runs):
        reasons.append("formal_cohort_scheduled_run_missing")
    outcome = "COMPLETE" if not reasons else "INCOMPLETE"
    return _manifest_result(
        "formal_cohort_pre_scoring_gate_v2",
        report["source_set"],
        outcome,
        definition["policy_sha256"],
        {
            "cohort_definition_sha256": definition["cohort_definition_sha256"],
            "forward_report_sha256": report["report_content_sha256"],
            "run_ledger_sha256": ledger["run_ledger_sha256"],
            "evaluation_evidence_root_sha256": definition["evaluation_evidence_root_sha256"],
            "expected_return_dates": len(expected_dates),
            "reported_return_dates": len(report["returns"]),
            "expected_runs": len(expected_runs),
            "reported_runs": len(ledger["runs"]),
            "scoring_permitted": outcome == "COMPLETE",
            "pre_scoring_only": True,
            "reasons": list(dict.fromkeys(reasons)),
        },
        coverage=coverage,
    )


def _validate_family_freeze(freeze: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(freeze, "family_freeze")
    expected = {
        "schema",
        "family_id",
        "candidate_members",
        "planned_order",
        "spending_plan",
        "family_wise_alpha",
        "tail",
        "direction",
        "decision_metric",
        "cluster_power_design_sha256",
        "evaluation_evidence_root_sha256",
        "discovery_family_manifest_sha256",
        "graduation_binding_sha256",
        "holdout_boundary_utc",
        "committed_at_utc",
        "source_set",
        "policy_sha256",
        "non_authority_claims",
        "family_freeze_sha256",
    }
    _exact(raw, expected, "family_freeze")
    if raw.get("schema") != FAMILY_FREEZE_SCHEMA:
        raise ValidationBindingError("family_freeze schema is unsupported")
    members_raw = raw.get("candidate_members")
    if not isinstance(members_raw, list) or not members_raw:
        raise ValidationBindingError("family_freeze.candidate_members must be a nonempty array")
    members: list[dict[str, str]] = []
    for index, item in enumerate(members_raw):
        row = _mapping(item, f"candidate_members[{index}]")
        _exact(row, {"candidate_id", "candidate_spec_sha256", "candidate_freeze_sha256"}, f"candidate_members[{index}]")
        members.append(
            {
                "candidate_id": _string(row.get("candidate_id"), f"candidate_members[{index}].candidate_id"),
                "candidate_spec_sha256": _sha(row.get("candidate_spec_sha256"), f"candidate_members[{index}].candidate_spec_sha256"),
                "candidate_freeze_sha256": _sha(row.get("candidate_freeze_sha256"), f"candidate_members[{index}].candidate_freeze_sha256"),
            }
        )
    if members != sorted(members, key=lambda row: row["candidate_id"]):
        raise ValidationBindingError("family_freeze.candidate_members must be sorted by candidate_id")
    member_ids = [row["candidate_id"] for row in members]
    if len(member_ids) != len(set(member_ids)):
        raise ValidationBindingError("family_freeze candidate_id values must be unique")
    planned = raw.get("planned_order")
    if not isinstance(planned, list) or any(not isinstance(item, str) or not item.strip() for item in planned):
        raise ValidationBindingError("family_freeze.planned_order must be a nonempty string array")
    planned_ids = [item.strip() for item in planned]
    if len(planned_ids) != len(set(planned_ids)) or set(planned_ids) != set(member_ids):
        raise ValidationBindingError("family_freeze.planned_order must contain every candidate exactly once")
    family_alpha = _probability(raw.get("family_wise_alpha"), "family_freeze.family_wise_alpha")
    plan_raw = raw.get("spending_plan")
    if not isinstance(plan_raw, list) or len(plan_raw) != len(planned_ids):
        raise ValidationBindingError("family_freeze.spending_plan must have one allocation per planned candidate")
    plan: list[dict[str, Any]] = []
    for index, item in enumerate(plan_raw):
        row = _mapping(item, f"spending_plan[{index}]")
        _exact(row, {"candidate_id", "allocated_alpha"}, f"spending_plan[{index}]")
        candidate_id = _string(row.get("candidate_id"), f"spending_plan[{index}].candidate_id")
        if candidate_id != planned_ids[index]:
            raise ValidationBindingError("family_freeze.spending_plan order must equal planned_order")
        plan.append({"candidate_id": candidate_id, "allocated_alpha": _probability(row.get("allocated_alpha"), "spending_plan.allocated_alpha")})
    if sum(float(row["allocated_alpha"]) for row in plan) > family_alpha + 1e-15:
        raise ValidationBindingError("family_freeze spending allocations cannot exceed family_wise_alpha")
    committed = _utc(raw.get("committed_at_utc"), "family_freeze.committed_at_utc")
    boundary = _utc(raw.get("holdout_boundary_utc"), "family_freeze.holdout_boundary_utc")
    if _utc_dt(committed, "committed_at_utc") >= _utc_dt(boundary, "holdout_boundary_utc"):
        raise ValidationBindingError("family_freeze must be committed before the holdout boundary")
    if raw.get("tail") not in {"ONE_SIDED", "TWO_SIDED"}:
        raise ValidationBindingError("family_freeze.tail must be ONE_SIDED or TWO_SIDED")
    try:
        claims = non_authority_claims()
        if _mapping(raw.get("non_authority_claims"), "family_freeze.non_authority_claims") != claims:
            raise ValidationBindingError("family_freeze.non_authority_claims must be the mandatory false claim set")
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc
    unsigned = {
        "schema": FAMILY_FREEZE_SCHEMA,
        "family_id": _string(raw.get("family_id"), "family_freeze.family_id"),
        "candidate_members": members,
        "planned_order": planned_ids,
        "spending_plan": plan,
        "family_wise_alpha": family_alpha,
        "tail": raw["tail"],
        "direction": _string(raw.get("direction"), "family_freeze.direction"),
        "decision_metric": _string(raw.get("decision_metric"), "family_freeze.decision_metric"),
        "cluster_power_design_sha256": _sha(raw.get("cluster_power_design_sha256"), "family_freeze.cluster_power_design_sha256"),
        "evaluation_evidence_root_sha256": _sha(raw.get("evaluation_evidence_root_sha256"), "family_freeze.evaluation_evidence_root_sha256"),
        "discovery_family_manifest_sha256": _sha(raw.get("discovery_family_manifest_sha256"), "family_freeze.discovery_family_manifest_sha256"),
        "graduation_binding_sha256": _sha(raw.get("graduation_binding_sha256"), "family_freeze.graduation_binding_sha256"),
        "holdout_boundary_utc": boundary,
        "committed_at_utc": committed,
        "source_set": _source_set(raw.get("source_set")),
        "policy_sha256": _sha(raw.get("policy_sha256"), "family_freeze.policy_sha256"),
        "non_authority_claims": claims,
    }
    expected_hash = canonical_json_sha256(unsigned)
    if _sha(raw.get("family_freeze_sha256"), "family_freeze.family_freeze_sha256") != expected_hash:
        raise ValidationBindingError("family_freeze_sha256 does not match canonical family freeze")
    return {**unsigned, "family_freeze_sha256": expected_hash}


def build_family_freeze_v2(definition: Mapping[str, Any], *, source_set: Mapping[str, Any]) -> dict[str, Any]:
    """Create a pre-holdout candidate-family commitment from caller-declared policy."""
    raw = dict(_mapping(definition, "family_definition"))
    raw.update({"schema": FAMILY_FREEZE_SCHEMA, "source_set": _source_set(source_set), "non_authority_claims": non_authority_claims()})
    raw.pop("family_freeze_sha256", None)
    raw["family_freeze_sha256"] = canonical_json_sha256(raw)
    return _validate_family_freeze(raw)


def create_family_ledger_v2(family_freeze: Mapping[str, Any], *, created_at_utc: str) -> dict[str, Any]:
    """Create a hash-chained ledger only if its genesis predates the holdout boundary."""
    freeze = _validate_family_freeze(family_freeze)
    created = _utc(created_at_utc, "created_at_utc")
    if _utc_dt(created, "created_at_utc") >= _utc_dt(freeze["holdout_boundary_utc"], "holdout_boundary_utc"):
        raise ValidationBindingError("family ledger genesis must be recorded before the holdout boundary")
    unsigned = {
        "schema": FAMILY_LEDGER_SCHEMA,
        "family_id": freeze["family_id"],
        "family_freeze_sha256": freeze["family_freeze_sha256"],
        "created_at_utc": created,
        "entries": [],
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "family_ledger_sha256")


def _validate_family_ledger(freeze: Mapping[str, Any], ledger: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    family = _validate_family_freeze(freeze)
    raw = _mapping(ledger, "family_ledger")
    expected = {"schema", "family_id", "family_freeze_sha256", "created_at_utc", "entries", "non_authority_claims", "family_ledger_sha256"}
    _exact(raw, expected, "family_ledger")
    reasons: list[str] = []
    if raw.get("schema") != FAMILY_LEDGER_SCHEMA:
        reasons.append("family_ledger_schema_invalid")
    if raw.get("family_id") != family["family_id"] or raw.get("family_freeze_sha256") != family["family_freeze_sha256"]:
        reasons.append("family_ledger_family_freeze_mismatch")
    try:
        created = _utc(raw.get("created_at_utc"), "family_ledger.created_at_utc")
        if _utc_dt(created, "ledger created") >= _utc_dt(family["holdout_boundary_utc"], "holdout boundary"):
            reasons.append("family_ledger_created_after_holdout_boundary")
    except ValidationBindingError:
        created = "INVALID"
        reasons.append("family_ledger_created_at_invalid")
    if raw.get("non_authority_claims") != non_authority_claims():
        reasons.append("family_ledger_non_authority_claims_invalid")
    entries_raw = raw.get("entries")
    entries = entries_raw if isinstance(entries_raw, list) else []
    if not isinstance(entries_raw, list):
        reasons.append("family_ledger_entries_invalid")
    previous = "GENESIS"
    members = {item["candidate_id"]: item for item in family["candidate_members"]}
    plan = {item["candidate_id"]: item for item in family["spending_plan"]}
    seen: set[str] = set()
    normalized_entries: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            reasons.append("family_ledger_entry_invalid")
            continue
        expected_entry = {"ordinal", "candidate_id", "candidate_spec_sha256", "candidate_freeze_sha256", "holdout_audit_sha256", "validation_report_sha256", "evaluation_evidence_root_sha256", "recorded_at_utc", "previous_entry_sha256", "entry_sha256"}
        if set(entry) != expected_entry:
            reasons.append("family_ledger_entry_shape_invalid")
            continue
        try:
            normalized = {
                "ordinal": entry.get("ordinal"),
                "candidate_id": _string(entry.get("candidate_id"), "ledger candidate_id"),
                "candidate_spec_sha256": _sha(entry.get("candidate_spec_sha256"), "ledger candidate spec"),
                "candidate_freeze_sha256": _sha(entry.get("candidate_freeze_sha256"), "ledger candidate freeze"),
                "holdout_audit_sha256": _sha(entry.get("holdout_audit_sha256"), "ledger holdout"),
                "validation_report_sha256": _sha(entry.get("validation_report_sha256"), "ledger report"),
                "evaluation_evidence_root_sha256": _sha(entry.get("evaluation_evidence_root_sha256"), "ledger root"),
                "recorded_at_utc": _utc(entry.get("recorded_at_utc"), "ledger recorded_at_utc"),
                "previous_entry_sha256": entry.get("previous_entry_sha256"),
            }
            entry_hash = _sha(entry.get("entry_sha256"), "ledger entry_sha256")
        except ValidationBindingError:
            reasons.append("family_ledger_entry_invalid")
            continue
        if normalized["ordinal"] != ordinal or normalized["candidate_id"] != family["planned_order"][ordinal - 1] if ordinal <= len(family["planned_order"]) else True:
            reasons.append("family_ledger_order_or_ordinal_invalid")
        member = members.get(normalized["candidate_id"])
        if member is None or member["candidate_spec_sha256"] != normalized["candidate_spec_sha256"] or member["candidate_freeze_sha256"] != normalized["candidate_freeze_sha256"]:
            reasons.append("family_ledger_nonmember_or_candidate_mismatch")
        if normalized["candidate_id"] in seen:
            reasons.append("family_ledger_duplicate_candidate")
        seen.add(normalized["candidate_id"])
        if normalized["evaluation_evidence_root_sha256"] != family["evaluation_evidence_root_sha256"]:
            reasons.append("family_ledger_evaluation_root_mismatch")
        if normalized["previous_entry_sha256"] != previous:
            reasons.append("family_ledger_append_chain_broken")
        unsigned_entry = dict(normalized)
        if canonical_json_sha256(unsigned_entry) != entry_hash:
            reasons.append("family_ledger_entry_hash_invalid")
        normalized_entries.append({**normalized, "entry_sha256": entry_hash})
        previous = entry_hash
    unsigned = {
        "schema": raw.get("schema"), "family_id": raw.get("family_id"), "family_freeze_sha256": raw.get("family_freeze_sha256"),
        "created_at_utc": created, "entries": normalized_entries, "non_authority_claims": raw.get("non_authority_claims"),
    }
    try:
        if canonical_json_sha256(unsigned) != _sha(raw.get("family_ledger_sha256"), "family_ledger_sha256"):
            reasons.append("family_ledger_hash_invalid")
    except ValidationBindingError:
        reasons.append("family_ledger_hash_invalid")
    return ({**unsigned, "family_ledger_sha256": raw.get("family_ledger_sha256")}, list(dict.fromkeys(reasons)))


def append_family_trial_v2(family_freeze: Mapping[str, Any], ledger: Mapping[str, Any], trial_evidence: Mapping[str, Any], *, recorded_at_utc: str) -> dict[str, Any]:
    """Append only the next precommitted member to the validated hash chain."""
    family = _validate_family_freeze(family_freeze)
    normalized_ledger, reasons = _validate_family_ledger(family, ledger)
    if reasons:
        raise ValidationBindingError("cannot append to invalid family ledger: " + ", ".join(reasons))
    raw = _mapping(trial_evidence, "trial_evidence")
    expected = {"candidate_id", "candidate_spec_sha256", "candidate_freeze_sha256", "holdout_audit_sha256", "validation_report_sha256", "evaluation_evidence_root_sha256"}
    _exact(raw, expected, "trial_evidence")
    candidate = _string(raw.get("candidate_id"), "trial_evidence.candidate_id")
    ordinal = len(normalized_ledger["entries"]) + 1
    if ordinal > len(family["planned_order"]) or family["planned_order"][ordinal - 1] != candidate:
        raise ValidationBindingError("trial candidate is not the next precommitted family member")
    member = {item["candidate_id"]: item for item in family["candidate_members"]}.get(candidate)
    if member is None or member["candidate_spec_sha256"] != _sha(raw.get("candidate_spec_sha256"), "trial candidate spec") or member["candidate_freeze_sha256"] != _sha(raw.get("candidate_freeze_sha256"), "trial candidate freeze"):
        raise ValidationBindingError("trial evidence does not match precommitted candidate member")
    root = _sha(raw.get("evaluation_evidence_root_sha256"), "trial evaluation root")
    if root != family["evaluation_evidence_root_sha256"]:
        raise ValidationBindingError("trial evidence evaluation root does not match family freeze")
    previous = normalized_ledger["entries"][-1]["entry_sha256"] if normalized_ledger["entries"] else "GENESIS"
    entry_unsigned = {
        "ordinal": ordinal, "candidate_id": candidate, "candidate_spec_sha256": member["candidate_spec_sha256"],
        "candidate_freeze_sha256": member["candidate_freeze_sha256"], "holdout_audit_sha256": _sha(raw.get("holdout_audit_sha256"), "trial holdout"),
        "validation_report_sha256": _sha(raw.get("validation_report_sha256"), "trial report"), "evaluation_evidence_root_sha256": root,
        "recorded_at_utc": _utc(recorded_at_utc, "recorded_at_utc"), "previous_entry_sha256": previous,
    }
    entry = {**entry_unsigned, "entry_sha256": canonical_json_sha256(entry_unsigned)}
    updated = {key: value for key, value in normalized_ledger.items() if key != "family_ledger_sha256"}
    updated["entries"] = [*normalized_ledger["entries"], entry]
    return _self_hash(updated, "family_ledger_sha256")


def validate_family_ledger_v2(family_freeze: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    family = _validate_family_freeze(family_freeze)
    normalized, reasons = _validate_family_ledger(family, ledger)
    return _manifest_result(
        "family_ledger_chain_validation_v2", family["source_set"], "COMPLETE" if not reasons else "INCOMPLETE", family["policy_sha256"],
        {"family_id": family["family_id"], "family_freeze_sha256": family["family_freeze_sha256"], "family_ledger_sha256": normalized.get("family_ledger_sha256"), "entries": len(normalized.get("entries", [])), "full_append_chain_valid": not reasons, "reasons": reasons},
    )


def _validate_evaluation_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(identity, "evaluation_identity")
    expected = {"schema", "implementation_version", "git_commit", "git_tree_sha256", "evaluator_source_set", "dependency_lock_identity", "config_source_set", "runtime", "command", "frozen_at_utc", "window_start_utc", "policy_sha256", "non_authority_claims", "evaluation_identity_sha256"}
    _exact(raw, expected, "evaluation_identity")
    if raw.get("schema") != EVALUATION_IDENTITY_SCHEMA:
        raise ValidationBindingError("evaluation_identity schema is unsupported")
    command = raw.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(value, str) or not value.strip() for value in command):
        raise ValidationBindingError("evaluation_identity.command must be a nonempty string array")
    runtime = _json_copy(_mapping(raw.get("runtime"), "evaluation_identity.runtime"))
    if not runtime:
        raise ValidationBindingError("evaluation_identity.runtime must not be empty")
    frozen = _utc(raw.get("frozen_at_utc"), "evaluation_identity.frozen_at_utc")
    start = _utc(raw.get("window_start_utc"), "evaluation_identity.window_start_utc")
    if _utc_dt(frozen, "frozen_at_utc") >= _utc_dt(start, "window_start_utc"):
        raise ValidationBindingError("evaluation identity must freeze before successor window_start_utc")
    try:
        lock = validate_file_identity(_mapping(raw.get("dependency_lock_identity"), "dependency_lock_identity"))
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc
    unsigned = {
        "schema": EVALUATION_IDENTITY_SCHEMA, "implementation_version": _string(raw.get("implementation_version"), "implementation_version"),
        "git_commit": _string(raw.get("git_commit"), "git_commit"), "git_tree_sha256": _sha(raw.get("git_tree_sha256"), "git_tree_sha256"),
        "evaluator_source_set": _source_set(raw.get("evaluator_source_set")), "dependency_lock_identity": lock, "config_source_set": _source_set(raw.get("config_source_set")),
        "runtime": runtime, "command": [value.strip() for value in command], "frozen_at_utc": frozen, "window_start_utc": start,
        "policy_sha256": _sha(raw.get("policy_sha256"), "policy_sha256"), "non_authority_claims": non_authority_claims(),
    }
    if raw.get("non_authority_claims") != non_authority_claims():
        raise ValidationBindingError("evaluation_identity.non_authority_claims must be mandatory false claims")
    expected_hash = canonical_json_sha256(unsigned)
    if _sha(raw.get("evaluation_identity_sha256"), "evaluation_identity_sha256") != expected_hash:
        raise ValidationBindingError("evaluation_identity_sha256 does not match canonical identity")
    return {**unsigned, "evaluation_identity_sha256": expected_hash}


def build_evaluation_identity_v2(definition: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(_mapping(definition, "evaluation_identity_definition"))
    raw.update({"schema": EVALUATION_IDENTITY_SCHEMA, "non_authority_claims": non_authority_claims()})
    raw.pop("evaluation_identity_sha256", None)
    raw["evaluation_identity_sha256"] = canonical_json_sha256(raw)
    return _validate_evaluation_identity(raw)


def build_evaluation_input_manifest_v2(source_set: Mapping[str, Any], artifact_hashes: Mapping[str, str]) -> dict[str, Any]:
    artifacts = _mapping(artifact_hashes, "artifact_hashes")
    if not artifacts:
        raise ValidationBindingError("artifact_hashes must not be empty")
    normalized = { _string(key, "artifact name"): _sha(value, f"artifact_hashes.{key}") for key, value in artifacts.items() }
    unsigned = {"schema": EVALUATION_INPUT_SCHEMA, "source_set": _source_set(source_set), "artifact_hashes": dict(sorted(normalized.items()))}
    return _self_hash(unsigned, "input_manifest_sha256")


def _validate_input_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(manifest, "input_manifest")
    _exact(raw, {"schema", "source_set", "artifact_hashes", "input_manifest_sha256"}, "input_manifest")
    if raw.get("schema") != EVALUATION_INPUT_SCHEMA:
        raise ValidationBindingError("input_manifest schema is unsupported")
    rebuilt = build_evaluation_input_manifest_v2(raw.get("source_set"), _mapping(raw.get("artifact_hashes"), "artifact_hashes"))
    if raw.get("input_manifest_sha256") != rebuilt["input_manifest_sha256"]:
        raise ValidationBindingError("input_manifest_sha256 does not match canonical manifest")
    return rebuilt


def _combine_source_sets(*sets: Mapping[str, Any], lock: Mapping[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index, source_set in enumerate(sets):
        for source in _source_set(source_set)["sources"]:
            records.append({"source_id": f"set{index}:{source['source_id']}", "size_bytes": source["size_bytes"], "sha256": source["sha256"]})
    records.append(build_source_record("dependency_lock", lock))
    try:
        return build_canonical_source_set(records)
    except ContractValidationError as exc:
        raise ValidationBindingError(str(exc)) from exc


def bind_evaluation_identity_v2(identity: Mapping[str, Any], input_manifest: Mapping[str, Any], evaluator_paths: Sequence[Mapping[str, Any]], dependency_lock_path: str, config_paths: Sequence[Mapping[str, Any]], execution_context: Mapping[str, Any]) -> dict[str, Any]:
    """Reverify immutable code/lock/config bytes and bind them to an input graph root."""
    frozen = _validate_evaluation_identity(identity)
    inputs = _validate_input_manifest(input_manifest)
    evaluator_checks, evaluator_reasons = _reverify_source_paths(frozen["evaluator_source_set"], list(evaluator_paths), "evaluator")
    config_checks, config_reasons = _reverify_source_paths(frozen["config_source_set"], list(config_paths), "config")
    lock_check = verify_file_identity(_string(dependency_lock_path, "dependency_lock_path"), frozen["dependency_lock_identity"])
    reasons = [*evaluator_reasons, *config_reasons]
    if lock_check["status"] != "VERIFIED_LOCAL_BYTES":
        reasons.append("evaluation_dependency_lock_not_reverified")
    context = _mapping(execution_context, "execution_context")
    required_context = {"git_commit", "git_tree_sha256", "runtime", "command"}
    _exact(context, required_context, "execution_context")
    if _string(context.get("git_commit"), "execution_context.git_commit") != frozen["git_commit"]:
        reasons.append("evaluation_git_commit_mismatch")
    if _sha(context.get("git_tree_sha256"), "execution_context.git_tree_sha256") != frozen["git_tree_sha256"]:
        reasons.append("evaluation_git_tree_mismatch")
    if _json_copy(_mapping(context.get("runtime"), "execution_context.runtime")) != frozen["runtime"]:
        reasons.append("evaluation_runtime_mismatch")
    command = context.get("command")
    if not isinstance(command, list) or command != frozen["command"]:
        reasons.append("evaluation_command_mismatch")
    root = canonical_json_sha256({"evaluation_identity_sha256": frozen["evaluation_identity_sha256"], "input_manifest_sha256": inputs["input_manifest_sha256"], "policy_sha256": frozen["policy_sha256"]})
    return _manifest_result(
        "evaluation_identity_binding_v2", _combine_source_sets(inputs["source_set"], frozen["evaluator_source_set"], frozen["config_source_set"], lock=frozen["dependency_lock_identity"]), "COMPLETE" if not reasons else "INCOMPLETE", frozen["policy_sha256"],
        {"evaluation_identity_sha256": frozen["evaluation_identity_sha256"], "input_manifest_sha256": inputs["input_manifest_sha256"], "evidence_graph_root_sha256": root, "identity_reverified": not reasons, "evaluator_reverifications": evaluator_checks, "config_reverifications": config_checks, "dependency_lock_reverification": lock_check, "reasons": list(dict.fromkeys(reasons)), "verification_scope": "local_bytes_and_caller_declared_execution_context_only"},
    )


def build_watch_inventory_v2(inventory: Mapping[str, Any], registry: Mapping[str, Any], source_set: Mapping[str, Any], *, policy_sha256: str) -> dict[str, Any]:
    """Mechanically require one exact successor registry record per inventory watch.

    Existing watches can be declared ``LEGACY`` and are emitted visibly as
    ``legacy_unregistered`` rather than retrofitted into a new rule set.
    """
    inv = _mapping(inventory, "watch_inventory")
    reg = _mapping(registry, "watch_registry")
    _exact(inv, {"schema", "records"}, "watch_inventory")
    _exact(reg, {"schema", "records"}, "watch_registry")
    if inv.get("schema") != "orderflow_edge_lab.watch_inventory.v2" or reg.get("schema") != "orderflow_edge_lab.watch_registry.v2":
        raise ValidationBindingError("inventory and registry must use their v2 schemas")
    records = inv.get("records")
    registry_records = reg.get("records")
    if not isinstance(records, list) or not isinstance(registry_records, list):
        raise ValidationBindingError("inventory and registry records must be arrays")
    expected_inv = {"watch_id", "config_path", "config_identity", "frozen_at_utc", "protocol_version", "state", "expected_review_artifact_id", "watch_class"}
    expected_reg = {"watch_id", "config_path", "config_identity", "freeze_manifest_sha256", "family_freeze_sha256", "cluster_power_design_sha256", "stopping_rule_sha256", "evaluation_identity_sha256", "expected_review_artifact_id", "state"}
    inv_by_id: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    statuses: list[dict[str, str]] = []
    for row in records:
        item = _mapping(row, "inventory record")
        if set(item) != expected_inv:
            raise ValidationBindingError("inventory record has unsupported shape")
        watch_id = _string(item.get("watch_id"), "inventory.watch_id")
        if watch_id in inv_by_id:
            reasons.append("inventory_duplicate_watch_id")
            continue
        try:
            identity = validate_file_identity(_mapping(item.get("config_identity"), "inventory.config_identity"))
        except ContractValidationError as exc:
            raise ValidationBindingError(str(exc)) from exc
        watch_class = item.get("watch_class")
        if watch_class not in {"SUCCESSOR", "LEGACY"}:
            raise ValidationBindingError("inventory.watch_class must be SUCCESSOR or LEGACY")
        inv_by_id[watch_id] = {**item, "watch_id": watch_id, "config_path": _string(item.get("config_path"), "inventory.config_path"), "config_identity": identity, "frozen_at_utc": _utc(item.get("frozen_at_utc"), "inventory.frozen_at_utc"), "protocol_version": _string(item.get("protocol_version"), "inventory.protocol_version"), "state": _string(item.get("state"), "inventory.state"), "expected_review_artifact_id": _string(item.get("expected_review_artifact_id"), "inventory.review artifact")}
    reg_by_id: dict[str, dict[str, Any]] = {}
    for row in registry_records:
        item = _mapping(row, "registry record")
        if set(item) != expected_reg:
            raise ValidationBindingError("registry record has unsupported shape")
        watch_id = _string(item.get("watch_id"), "registry.watch_id")
        if watch_id in reg_by_id:
            reasons.append("registry_duplicate_watch_id")
            continue
        try:
            identity = validate_file_identity(_mapping(item.get("config_identity"), "registry.config_identity"))
        except ContractValidationError as exc:
            raise ValidationBindingError(str(exc)) from exc
        normalized = {**item, "watch_id": watch_id, "config_path": _string(item.get("config_path"), "registry.config_path"), "config_identity": identity, "expected_review_artifact_id": _string(item.get("expected_review_artifact_id"), "registry.review artifact"), "state": _string(item.get("state"), "registry.state")}
        for key in ("freeze_manifest_sha256", "family_freeze_sha256", "cluster_power_design_sha256", "stopping_rule_sha256", "evaluation_identity_sha256"):
            normalized[key] = _sha(item.get(key), f"registry.{key}")
        reg_by_id[watch_id] = normalized
    for watch_id, item in sorted(inv_by_id.items()):
        candidate = reg_by_id.get(watch_id)
        if item["watch_class"] == "LEGACY" and candidate is None:
            statuses.append({"watch_id": watch_id, "status": "legacy_unregistered"})
            continue
        if candidate is None:
            reasons.append("inventory_watch_unregistered")
            statuses.append({"watch_id": watch_id, "status": "unregistered"})
            continue
        if item["watch_class"] == "LEGACY":
            statuses.append({"watch_id": watch_id, "status": "legacy_registered_not_successor_compliant"})
            continue
        equal = candidate["config_path"] == item["config_path"] and candidate["config_identity"] == item["config_identity"] and candidate["expected_review_artifact_id"] == item["expected_review_artifact_id"] and candidate["state"] == item["state"]
        if not equal:
            reasons.append("inventory_registry_alias_or_identity_mismatch")
            statuses.append({"watch_id": watch_id, "status": "mismatch"})
        else:
            statuses.append({"watch_id": watch_id, "status": "successor_mapped_once"})
    if set(reg_by_id) - set(inv_by_id):
        reasons.append("registry_watch_not_in_inventory")
    outcome = "INCOMPLETE" if reasons else ("DIAGNOSTIC_ONLY" if any(row["status"] == "legacy_unregistered" for row in statuses) else "COMPLETE")
    return _manifest_result("watch_registry_hygiene_v2", _source_set(source_set), outcome, policy_sha256, {"records": statuses, "inventory_count": len(inv_by_id), "registry_count": len(reg_by_id), "bijective_successor_mapping": not reasons, "reasons": list(dict.fromkeys(reasons)), "legacy_records_visible": any(row["status"].startswith("legacy_") for row in statuses)})


def _validate_cluster_power_design(design: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(design, "cluster_power_design")
    expected = {"schema", "design_id", "cluster_unit", "cluster_construction_rule", "estimand", "weighting", "alpha", "tail", "multiplicity_method", "family_freeze_sha256", "desired_power", "target_effect_bps", "expected_cluster_count", "variance_assumption_bps2", "variance_source_sha256", "missing_cluster_policy", "committed_at_utc", "window_start_utc", "source_set", "policy_sha256", "non_authority_claims", "cluster_power_design_sha256"}
    _exact(raw, expected, "cluster_power_design")
    if raw.get("schema") != CLUSTER_POWER_DESIGN_SCHEMA:
        raise ValidationBindingError("cluster_power_design schema is unsupported")
    committed = _utc(raw.get("committed_at_utc"), "design.committed_at_utc")
    start = _utc(raw.get("window_start_utc"), "design.window_start_utc")
    if _utc_dt(committed, "design committed") >= _utc_dt(start, "design window start"):
        raise ValidationBindingError("cluster power design must be committed before window_start_utc")
    count = raw.get("expected_cluster_count")
    if type(count) is not int or count < 2:
        raise ValidationBindingError("expected_cluster_count must be an integer of at least 2")
    if raw.get("tail") not in {"ONE_SIDED", "TWO_SIDED"}:
        raise ValidationBindingError("cluster power design tail must be ONE_SIDED or TWO_SIDED")
    if raw.get("non_authority_claims") != non_authority_claims():
        raise ValidationBindingError("cluster power design non_authority_claims must remain false")
    unsigned = {
        "schema": CLUSTER_POWER_DESIGN_SCHEMA, "design_id": _string(raw.get("design_id"), "design_id"), "cluster_unit": _string(raw.get("cluster_unit"), "cluster_unit"), "cluster_construction_rule": _string(raw.get("cluster_construction_rule"), "cluster_construction_rule"), "estimand": _string(raw.get("estimand"), "estimand"), "weighting": _string(raw.get("weighting"), "weighting"), "alpha": _probability(raw.get("alpha"), "alpha"), "tail": raw["tail"], "multiplicity_method": _string(raw.get("multiplicity_method"), "multiplicity_method"), "family_freeze_sha256": _sha(raw.get("family_freeze_sha256"), "family_freeze_sha256"), "desired_power": _probability(raw.get("desired_power"), "desired_power"), "target_effect_bps": _number(raw.get("target_effect_bps"), "target_effect_bps"), "expected_cluster_count": count, "variance_assumption_bps2": _number(raw.get("variance_assumption_bps2"), "variance_assumption_bps2", nonnegative=True), "variance_source_sha256": _sha(raw.get("variance_source_sha256"), "variance_source_sha256"), "missing_cluster_policy": _string(raw.get("missing_cluster_policy"), "missing_cluster_policy"), "committed_at_utc": committed, "window_start_utc": start, "source_set": _source_set(raw.get("source_set")), "policy_sha256": _sha(raw.get("policy_sha256"), "policy_sha256"), "non_authority_claims": non_authority_claims(),
    }
    expected_hash = canonical_json_sha256(unsigned)
    if _sha(raw.get("cluster_power_design_sha256"), "cluster_power_design_sha256") != expected_hash:
        raise ValidationBindingError("cluster_power_design_sha256 does not match canonical design")
    return {**unsigned, "cluster_power_design_sha256": expected_hash}


def build_cluster_power_design_v2(definition: Mapping[str, Any], *, source_set: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(_mapping(definition, "cluster_power_definition"))
    raw.update({"schema": CLUSTER_POWER_DESIGN_SCHEMA, "source_set": _source_set(source_set), "non_authority_claims": non_authority_claims()})
    raw.pop("cluster_power_design_sha256", None)
    raw["cluster_power_design_sha256"] = canonical_json_sha256(raw)
    return _validate_cluster_power_design(raw)


def powered_mde_v2(design: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate conventional normal-approximation MDE with alpha *and* desired power."""
    frozen = _validate_cluster_power_design(design)
    alpha = frozen["alpha"]
    critical_alpha = statistics.NormalDist().inv_cdf(1.0 - alpha / 2.0 if frozen["tail"] == "TWO_SIDED" else 1.0 - alpha)
    critical_power = statistics.NormalDist().inv_cdf(frozen["desired_power"])
    standard_error = math.sqrt(frozen["variance_assumption_bps2"] / frozen["expected_cluster_count"])
    mde = (critical_alpha + critical_power) * standard_error
    return _manifest_result("powered_cluster_mde_v2", frozen["source_set"], "COMPLETE", frozen["policy_sha256"], {"cluster_power_design_sha256": frozen["cluster_power_design_sha256"], "cluster_unit": frozen["cluster_unit"], "expected_cluster_count": frozen["expected_cluster_count"], "alpha": alpha, "tail": frozen["tail"], "desired_power": frozen["desired_power"], "variance_assumption_bps2": frozen["variance_assumption_bps2"], "variance_source_sha256": frozen["variance_source_sha256"], "target_effect_bps": frozen["target_effect_bps"], "powered_mde_bps": mde, "formula": "(z_alpha + z_power) * sqrt(predeclared_variance / expected_clusters)", "legacy_metric_not_used": True})


def qualify_legacy_precision_v2(legacy_metric: Mapping[str, Any], source_set: Mapping[str, Any], *, policy_sha256: str) -> dict[str, Any]:
    """Relabel an existing legacy MDE-style number without changing its value or authority."""
    raw = _mapping(legacy_metric, "legacy_metric")
    value = raw.get("minimum_detectable_effect_bps")
    precision = _number(value, "legacy_metric.minimum_detectable_effect_bps", nonnegative=True) if value is not None else None
    return _manifest_result("legacy_post_hoc_precision_qualification_v2", _source_set(source_set), "DIAGNOSTIC_ONLY", policy_sha256, {"post_hoc_precision_half_width_bps": precision, "legacy_field_name": "minimum_detectable_effect_bps", "powered_design_evidence": False, "promotion_usable": False, "note": "Legacy descriptive outputs are preserved; this qualification does not retrofit alpha, power, or cluster policy."})


def bind_validation_promotion_v2(*, candidate_id: str, source_verification: Mapping[str, Any], formal_cohort: Mapping[str, Any], evaluation_binding: Mapping[str, Any], family_freeze: Mapping[str, Any], family_ledger: Mapping[str, Any], discovery_family_manifest: Mapping[str, Any], graduation_binding: Mapping[str, Any]) -> dict[str, Any]:
    """Bind all successor evidence graph roots without granting promotion authority."""
    candidate = _string(candidate_id, "candidate_id")
    source = validate_manifest_result(_mapping(source_verification, "source_verification"))
    cohort = validate_manifest_result(_mapping(formal_cohort, "formal_cohort"))
    evaluation = validate_manifest_result(_mapping(evaluation_binding, "evaluation_binding"))
    discovery = validate_manifest_result(_mapping(discovery_family_manifest, "discovery_family_manifest"))
    graduation = validate_manifest_result(_mapping(graduation_binding, "graduation_binding"))
    family = _validate_family_freeze(family_freeze)
    ledger, ledger_reasons = _validate_family_ledger(family, family_ledger)
    reasons: list[str] = []
    # Local source/evaluator re-verification has no caller-declared time grid
    # and is intentionally DIAGNOSTIC_ONLY; its positive attributes are the
    # gate.  Cohort coverage and the Stage 04 generic manifests do have
    # coverage/terminal semantics and must be COMPLETE.
    for name, artifact in (("formal_cohort", cohort), ("discovery_family", discovery), ("graduation_binding", graduation)):
        if artifact["outcome"] != "COMPLETE":
            reasons.append(f"{name}_not_complete")
    if source["attributes"].get("source_files_reverified") is not True:
        reasons.append("validation_source_files_not_reverified")
    if evaluation["attributes"].get("identity_reverified") is not True:
        reasons.append("evaluation_identity_not_reverified")
    if cohort["attributes"].get("scoring_permitted") is not True:
        reasons.append("formal_cohort_scoring_not_permitted")
    root = evaluation["attributes"].get("evidence_graph_root_sha256")
    if root != family["evaluation_evidence_root_sha256"] or cohort["attributes"].get("evaluation_evidence_root_sha256") != root:
        reasons.append("evaluation_evidence_graph_root_mismatch")
    if discovery["manifest_sha256"] != family["discovery_family_manifest_sha256"]:
        reasons.append("discovery_family_manifest_mismatch")
    if graduation["manifest_sha256"] != family["graduation_binding_sha256"]:
        reasons.append("graduation_binding_manifest_mismatch")
    reasons.extend(ledger_reasons)
    candidate_entries = [row for row in ledger.get("entries", []) if row.get("candidate_id") == candidate]
    if len(candidate_entries) != 1:
        reasons.append("candidate_trial_not_uniquely_in_family_ledger")
        trial = None
    else:
        trial = candidate_entries[0]
    outcome = "COMPLETE" if not reasons else "INCOMPLETE"
    return _manifest_result("validation_promotion_evidence_binding_v2", source["source_set"], outcome, family["policy_sha256"], {"candidate_id": candidate, "family_id": family["family_id"], "family_freeze_sha256": family["family_freeze_sha256"], "discovery_family_manifest_sha256": discovery["manifest_sha256"], "graduation_binding_sha256": graduation["manifest_sha256"], "evaluation_evidence_graph_root_sha256": root, "trial_ordinal": trial.get("ordinal") if trial else None, "applicable_alpha": next((row["allocated_alpha"] for row in family["spending_plan"] if row["candidate_id"] == candidate), None), "promotion_binding_complete": outcome == "COMPLETE", "promotion_authorization_granted": False, "reasons": list(dict.fromkeys(reasons))})


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationBindingError(f"cannot read JSON object: {path}") from exc
    return _mapping(value, path)


def _write(path: str, value: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, opt-in v2 validation/promotion evidence bindings; never authorizes promotion.")
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("verify-source-set", help="require exact holdout/report source set equality and local byte re-verification")
    p.add_argument("--holdout-source-set", required=True); p.add_argument("--report-source-set", required=True); p.add_argument("--reverification-paths", required=True); p.add_argument("--policy-sha256", required=True); p.add_argument("--output", required=True)
    p = subs.add_parser("formal-cohort", help="validate exact scheduled return/run coverage before any scoring")
    p.add_argument("--definition", required=True); p.add_argument("--report", required=True); p.add_argument("--run-ledger", required=True); p.add_argument("--as-of-utc", required=True); p.add_argument("--output", required=True)
    p = subs.add_parser("bind-evaluator", help="reverify evaluator, lock, config, runtime, and evidence-graph identity")
    p.add_argument("--identity", required=True); p.add_argument("--input-manifest", required=True); p.add_argument("--evaluator-paths", required=True); p.add_argument("--dependency-lock", required=True); p.add_argument("--config-paths", required=True); p.add_argument("--execution-context", required=True); p.add_argument("--output", required=True)
    p = subs.add_parser("watch-inventory", help="audit the authoritative v2 inventory/registry mapping")
    p.add_argument("--inventory", required=True); p.add_argument("--registry", required=True); p.add_argument("--source-set", required=True); p.add_argument("--policy-sha256", required=True); p.add_argument("--output", required=True)
    p = subs.add_parser("power-mde", help="calculate a powered MDE from a frozen v2 cluster design")
    p.add_argument("--design", required=True); p.add_argument("--output", required=True)
    p = subs.add_parser("promotion-binding", help="bind source/cohort/evaluator/family/stage04 evidence without promotion authority")
    p.add_argument("--candidate-id", required=True); p.add_argument("--source-verification", required=True); p.add_argument("--formal-cohort", required=True); p.add_argument("--evaluation-binding", required=True); p.add_argument("--family-freeze", required=True); p.add_argument("--family-ledger", required=True); p.add_argument("--discovery-family-manifest", required=True); p.add_argument("--graduation-binding", required=True); p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-source-set": result = verify_validation_source_set_v2(_load(args.holdout_source_set), _load(args.report_source_set), list(_load(args.reverification_paths).get("paths", [])), policy_sha256=args.policy_sha256)
        elif args.command == "formal-cohort": result = build_formal_cohort_v2(_load(args.definition), _load(args.report), _load(args.run_ledger), as_of_utc=args.as_of_utc)
        elif args.command == "bind-evaluator": result = bind_evaluation_identity_v2(_load(args.identity), _load(args.input_manifest), list(_load(args.evaluator_paths).get("paths", [])), args.dependency_lock, list(_load(args.config_paths).get("paths", [])), _load(args.execution_context))
        elif args.command == "watch-inventory": result = build_watch_inventory_v2(_load(args.inventory), _load(args.registry), _load(args.source_set), policy_sha256=args.policy_sha256)
        elif args.command == "power-mde": result = powered_mde_v2(_load(args.design))
        else: result = bind_validation_promotion_v2(candidate_id=args.candidate_id, source_verification=_load(args.source_verification), formal_cohort=_load(args.formal_cohort), evaluation_binding=_load(args.evaluation_binding), family_freeze=_load(args.family_freeze), family_ledger=_load(args.family_ledger), discovery_family_manifest=_load(args.discovery_family_manifest), graduation_binding=_load(args.graduation_binding))
        _write(args.output, result)
        print(json.dumps({"analysis": result["manifest_type"], "outcome": result["outcome"], "output": args.output}, sort_keys=True))
        return 0 if result["outcome"] == "COMPLETE" else 1
    except (ValidationBindingError, ContractValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

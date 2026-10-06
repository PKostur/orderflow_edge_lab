"""Offline, opt-in v2 discovery-family governance.

This successor never rewrites legacy ledgers/freezes.  It only validates local,
caller-declared JSON evidence and always retains non-authority claims.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
import json
import math
from pathlib import Path
import random
import sys
from statistics import NormalDist, fmean, stdev
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    ContractValidationError, canonical_json_bytes, canonical_json_sha256,
    non_authority_claims, source_sets_equal, validate_canonical_source_set,
    validate_coverage_result,
)

UTC = timezone.utc
FAMILY_DECLARATION_SCHEMA = "orderflow_edge_lab.discovery_family_declaration.v2"
FAMILY_LEDGER_SCHEMA = "orderflow_edge_lab.discovery_family_ledger.v2"
LEDGER_EVENT_SCHEMA = "orderflow_edge_lab.discovery_ledger_event.v2"
FAMILY_CLOSURE_SCHEMA = "orderflow_edge_lab.discovery_family_closure.v2"
FRICTION_POLICY_SCHEMA = "orderflow_edge_lab.discovery_friction_policy.v2"
ECONOMICS_SCHEMA = "orderflow_edge_lab.discovery_economics_eligibility.v2"
CLUSTER_CONTRACT_SCHEMA = "orderflow_edge_lab.discovery_cluster_contract.v2"
CLUSTER_MATRIX_SCHEMA = "orderflow_edge_lab.discovery_cluster_matrix.v2"
CLUSTER_INFERENCE_SCHEMA = "orderflow_edge_lab.discovery_cluster_inference.v2"
BENCHMARK_POLICY_SCHEMA = "orderflow_edge_lab.discovery_benchmark_policy.v2"
BENCHMARK_SCHEMA = "orderflow_edge_lab.discovery_benchmark_assessment.v2"
EVALUATION_SCHEMA = "orderflow_edge_lab.discovery_evaluation_binding.v2"
GRADUATION_POLICY_SCHEMA = "orderflow_edge_lab.discovery_graduation_policy.v2"
GRADUATION_SCHEMA = "orderflow_edge_lab.discovery_graduation_binding.v2"
FREEZE_SCHEMA = "orderflow_edge_lab.discovery_candidate_freeze.v2"
TERMINAL_STATUSES = frozenset({"COMPLETED", "FALSIFIED", "ABANDONED", "INVALID_DATA"})
HEX = frozenset("0123456789abcdef")


class DiscoveryGovernanceV2Error(ValueError):
    """Malformed, incomplete, or ineligible prospective governance evidence."""


def _map(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DiscoveryGovernanceV2Error(f"{field} must be a JSON object with string keys")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        missing, extra = sorted(expected - set(value)), sorted(set(value) - expected)
        raise DiscoveryGovernanceV2Error(f"{field} has unsupported shape (missing={missing}; extra={extra})")


def _str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryGovernanceV2Error(f"{field} must be a nonempty string")
    return value.strip()


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX for c in value.lower()):
        raise DiscoveryGovernanceV2Error(f"{field} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _num(value: object, field: str, lo: float | None = None, hi: float | None = None) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise DiscoveryGovernanceV2Error(f"{field} must be a finite number")
    result = float(value)
    if lo is not None and result < lo or hi is not None and result > hi:
        raise DiscoveryGovernanceV2Error(f"{field} is outside its allowed range")
    return result


def _int(value: object, field: str, lo: int = 0) -> int:
    if type(value) is not int or value < lo:
        raise DiscoveryGovernanceV2Error(f"{field} must be an integer at least {lo}")
    return value


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryGovernanceV2Error(f"{field} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiscoveryGovernanceV2Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DiscoveryGovernanceV2Error(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _json(value: object, field: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except ContractValidationError as exc:
        raise DiscoveryGovernanceV2Error(f"{field} must be ordinary finite JSON") from exc


def _seal(unsigned: Mapping[str, Any], name: str) -> dict[str, Any]:
    clean = _json(dict(unsigned), "object")
    return {**clean, name: canonical_json_sha256(clean)}


def _verify_hash(raw: Mapping[str, Any], name: str, field: str) -> None:
    expected = _sha(raw.get(name), f"{field}.{name}")
    unsigned = dict(raw)
    unsigned.pop(name, None)
    if canonical_json_sha256(unsigned) != expected:
        raise DiscoveryGovernanceV2Error(f"{field}.{name} does not bind canonical content")


def _sorted_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DiscoveryGovernanceV2Error(f"{field} must be a nonempty array")
    output = [_str(item, field) for item in value]
    if output != sorted(output) or len(output) != len(set(output)):
        raise DiscoveryGovernanceV2Error(f"{field} must be sorted and unique")
    return output


def _candidate(value: Mapping[str, Any], field: str = "candidate_identity") -> dict[str, str]:
    raw = _map(value, field)
    _keys(raw, {"candidate_id", "candidate_spec_sha256", "candidate_created_at_utc"}, field)
    return {"candidate_id": _str(raw.get("candidate_id"), f"{field}.candidate_id"),
            "candidate_spec_sha256": _sha(raw.get("candidate_spec_sha256"), f"{field}.candidate_spec_sha256"),
            "candidate_created_at_utc": _utc(raw.get("candidate_created_at_utc"), f"{field}.candidate_created_at_utc")}


def _candidate_key(value: Mapping[str, Any]) -> tuple[str, str]:
    return value["candidate_id"], value["candidate_spec_sha256"]


def build_family_declaration_v2(*, family_id: str, family_created_at_utc: str, scope: Mapping[str, Any],
                                variant_axes: Sequence[Mapping[str, Any]], cost_cases: Sequence[Mapping[str, Any]],
                                adaptive_decision_rules: Sequence[Mapping[str, Any]], source_set: Mapping[str, Any],
                                family_policy_sha256: str) -> dict[str, Any]:
    """Hash an immutable, caller-declared family before prospective runs begin."""
    if not variant_axes or not cost_cases:
        raise DiscoveryGovernanceV2Error("family declaration requires predeclared variant_axes and cost_cases")
    unsigned = {
        "schema": FAMILY_DECLARATION_SCHEMA, "analysis": "prospective_discovery_family_declaration_v2",
        "family_id": _str(family_id, "family_id"), "family_created_at_utc": _utc(family_created_at_utc, "family_created_at_utc"),
        "scope": _json(dict(_map(scope, "scope")), "scope"), "variant_axes": _json(list(variant_axes), "variant_axes"),
        "cost_cases": _json(list(cost_cases), "cost_cases"), "adaptive_decision_rules": _json(list(adaptive_decision_rules), "adaptive_decision_rules"),
        "source_set": validate_canonical_source_set(source_set), "family_policy_sha256": _sha(family_policy_sha256, "family_policy_sha256"),
        "non_authority_claims": non_authority_claims(),
    }
    return _seal(unsigned, "family_declaration_sha256")


def validate_family_declaration_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "family_declaration")
    expected = {"schema", "analysis", "family_id", "family_created_at_utc", "scope", "variant_axes", "cost_cases", "adaptive_decision_rules", "source_set", "family_policy_sha256", "non_authority_claims", "family_declaration_sha256"}
    _keys(raw, expected, "family_declaration")
    if raw.get("schema") != FAMILY_DECLARATION_SCHEMA or raw.get("analysis") != "prospective_discovery_family_declaration_v2":
        raise DiscoveryGovernanceV2Error("unsupported family declaration")
    rebuilt = build_family_declaration_v2(family_id=raw.get("family_id"), family_created_at_utc=raw.get("family_created_at_utc"), scope=_map(raw.get("scope"), "scope"), variant_axes=raw.get("variant_axes"), cost_cases=raw.get("cost_cases"), adaptive_decision_rules=raw.get("adaptive_decision_rules"), source_set=_map(raw.get("source_set"), "source_set"), family_policy_sha256=raw.get("family_policy_sha256"))
    if raw != rebuilt:
        raise DiscoveryGovernanceV2Error("family declaration hash or non-authority claims are invalid")
    return rebuilt


def _event(event: Mapping[str, Any], family: Mapping[str, Any], sequence: int, prior: str | None) -> dict[str, Any]:
    raw = _map(event, "ledger_event_input")
    needed = {"event_id", "event_type", "candidate_identity", "recorded_at_utc", "declared_run_scope_sha256", "terminal_status", "result_artifact_sha256", "result_inspected_at_utc", "zero_trade"}
    _keys(raw, needed, "ledger_event_input")
    kind = raw.get("event_type")
    if kind not in {"RUN_DECLARED", "RUN_TERMINAL"}:
        raise DiscoveryGovernanceV2Error("event_type must be RUN_DECLARED or RUN_TERMINAL")
    out = {"schema": LEDGER_EVENT_SCHEMA, "sequence": sequence, "event_id": _str(raw.get("event_id"), "event_id"), "event_type": kind,
           "family_id": family["family_id"], "family_declaration_sha256": family["family_declaration_sha256"],
           "candidate_identity": _candidate(raw.get("candidate_identity"), "candidate_identity"), "recorded_at_utc": _utc(raw.get("recorded_at_utc"), "recorded_at_utc"),
           "declared_run_scope_sha256": _sha(raw.get("declared_run_scope_sha256"), "declared_run_scope_sha256"),
           "terminal_status": None, "result_artifact_sha256": None, "result_inspected_at_utc": None, "zero_trade": False, "prior_event_sha256": prior}
    if kind == "RUN_DECLARED":
        if any(raw.get(key) is not None for key in ("terminal_status", "result_artifact_sha256", "result_inspected_at_utc")) or raw.get("zero_trade") is not False:
            raise DiscoveryGovernanceV2Error("RUN_DECLARED cannot contain result information")
    else:
        status = raw.get("terminal_status")
        if status not in TERMINAL_STATUSES:
            raise DiscoveryGovernanceV2Error("RUN_TERMINAL requires a supported terminal status")
        artifact = raw.get("result_artifact_sha256")
        if status in {"COMPLETED", "FALSIFIED"} and artifact is None:
            raise DiscoveryGovernanceV2Error("completed/falsified run needs a result artifact hash")
        if artifact is not None:
            artifact = _sha(artifact, "result_artifact_sha256")
        inspected = _utc(raw.get("result_inspected_at_utc"), "result_inspected_at_utc")
        if _dt(out["recorded_at_utc"]) >= _dt(inspected):
            raise DiscoveryGovernanceV2Error("terminal ledger event must be recorded strictly before result inspection")
        if type(raw.get("zero_trade")) is not bool:
            raise DiscoveryGovernanceV2Error("zero_trade must be boolean")
        out.update(terminal_status=status, result_artifact_sha256=artifact, result_inspected_at_utc=inspected, zero_trade=raw["zero_trade"])
    return _seal(out, "event_sha256")


def _ledger(family_declaration: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    family = validate_family_declaration_v2(family_declaration)
    events, declared, terminated, event_ids, prior = [], {}, set(), set(), None
    for index, raw in enumerate(entries):
        entry = _map(raw, "ledger_event")
        if "event_sha256" in entry:
            copied = {key: entry[key] for key in entry if key not in {"schema", "sequence", "family_id", "family_declaration_sha256", "prior_event_sha256", "event_sha256"}}
            normalized = _event(copied, family, index, prior)
            if entry.get("schema") != LEDGER_EVENT_SCHEMA or entry.get("sequence") != index or entry.get("family_id") != family["family_id"] or entry.get("family_declaration_sha256") != family["family_declaration_sha256"] or entry.get("prior_event_sha256") != prior or entry.get("event_sha256") != normalized["event_sha256"]:
                raise DiscoveryGovernanceV2Error("ledger event hash-chain evidence is invalid")
        else:
            normalized = _event(entry, family, index, prior)
        if normalized["event_id"] in event_ids:
            raise DiscoveryGovernanceV2Error("ledger event IDs must be unique")
        event_ids.add(normalized["event_id"])
        key = _candidate_key(normalized["candidate_identity"])
        if normalized["event_type"] == "RUN_DECLARED":
            if key in declared:
                raise DiscoveryGovernanceV2Error("candidate identity cannot be declared twice")
            declared[key] = normalized
        else:
            if key not in declared or key in terminated:
                raise DiscoveryGovernanceV2Error("terminal event needs exactly one previous declaration")
            if normalized["declared_run_scope_sha256"] != declared[key]["declared_run_scope_sha256"]:
                raise DiscoveryGovernanceV2Error("terminal event changed the predeclared run scope")
            if _dt(normalized["recorded_at_utc"]) < _dt(declared[key]["recorded_at_utc"]):
                raise DiscoveryGovernanceV2Error("terminal event precedes declaration")
            terminated.add(key)
        events.append(normalized); prior = normalized["event_sha256"]
    return _seal({"schema": FAMILY_LEDGER_SCHEMA, "analysis": "prospective_append_only_discovery_family_ledger_v2", "family_declaration": family, "entries": events, "entry_count": len(events), "head_event_sha256": prior, "non_authority_claims": non_authority_claims()}, "ledger_sha256")


def build_family_ledger_v2(family_declaration: Mapping[str, Any], entries: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Build an immutable ledger snapshot; an empty snapshot is valid only before runs."""
    return _ledger(family_declaration, [] if entries is None else entries)


def verify_family_ledger_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "family_ledger")
    _keys(raw, {"schema", "analysis", "family_declaration", "entries", "entry_count", "head_event_sha256", "non_authority_claims", "ledger_sha256"}, "family_ledger")
    if raw.get("schema") != FAMILY_LEDGER_SCHEMA or raw.get("analysis") != "prospective_append_only_discovery_family_ledger_v2" or not isinstance(raw.get("entries"), list):
        raise DiscoveryGovernanceV2Error("unsupported family ledger")
    rebuilt = _ledger(_map(raw.get("family_declaration"), "family_declaration"), raw["entries"])
    if raw != rebuilt:
        raise DiscoveryGovernanceV2Error("family ledger hash, chain, or non-authority claims are invalid")
    return rebuilt


def append_family_ledger_event_v2(ledger: Mapping[str, Any], event_input: Mapping[str, Any]) -> dict[str, Any]:
    """Append one event to a verified snapshot; publish returned JSON only to a new exclusive path."""
    prior = verify_family_ledger_v2(ledger)
    next_event = _event(event_input, prior["family_declaration"], prior["entry_count"], prior["head_event_sha256"])
    return _ledger(prior["family_declaration"], [*prior["entries"], next_event])


def _members(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    starts: dict[tuple[str, str], Mapping[str, Any]] = {}
    ends: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in ledger["entries"]:
        key = _candidate_key(entry["candidate_identity"])
        if entry["event_type"] == "RUN_DECLARED":
            starts[key] = entry
        else:
            ends[key] = entry
    output = []
    for key in sorted(starts):
        start, finish = starts[key], ends.get(key)
        output.append({"candidate_identity": start["candidate_identity"], "declared_run_scope_sha256": start["declared_run_scope_sha256"], "declaration_event_sha256": start["event_sha256"], "terminal_event_sha256": finish["event_sha256"] if finish else None, "terminal_status": finish["terminal_status"] if finish else "UNTERMINATED", "result_artifact_sha256": finish["result_artifact_sha256"] if finish else None, "zero_trade": finish["zero_trade"] if finish else None})
    return output


def close_family_v2(family_ledger: Mapping[str, Any], *, selected_candidate_identity: Mapping[str, Any], selection_rule_sha256: str, closure_policy_sha256: str) -> dict[str, Any]:
    """Close only a complete family, retaining every failed/abandoned/invalid sibling."""
    ledger = verify_family_ledger_v2(family_ledger)
    selected = _candidate(selected_candidate_identity, "selected_candidate_identity")
    members = _members(ledger)
    if not members or not any(row["candidate_identity"] == selected for row in members):
        raise DiscoveryGovernanceV2Error("selected candidate must be a predeclared family member")
    unfinished = sorted(row["candidate_identity"]["candidate_id"] for row in members if row["terminal_status"] == "UNTERMINATED")
    selection_completed = any(row["candidate_identity"] == selected and row["terminal_status"] == "COMPLETED" for row in members)
    status = "CLOSED_VERIFIED" if not unfinished and selection_completed else "CLOSURE_INCOMPLETE"
    unsigned = {"schema": FAMILY_CLOSURE_SCHEMA, "analysis": "verified_discovery_family_closure_v2", "family_id": ledger["family_declaration"]["family_id"], "family_declaration_sha256": ledger["family_declaration"]["family_declaration_sha256"], "family_ledger_sha256": ledger["ledger_sha256"], "source_set": ledger["family_declaration"]["source_set"], "selected_candidate_identity": selected, "selection_rule_sha256": _sha(selection_rule_sha256, "selection_rule_sha256"), "closure_policy_sha256": _sha(closure_policy_sha256, "closure_policy_sha256"), "members": members, "member_count": len(members), "terminal_status_counts": dict(sorted(Counter(row["terminal_status"] for row in members).items())), "unterminated_candidate_ids": unfinished, "closure_status": status, "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "closure_sha256")


def verify_family_closure_v2(value: Mapping[str, Any], *, family_ledger: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = _map(value, "family_closure")
    expected = {"schema", "analysis", "family_id", "family_declaration_sha256", "family_ledger_sha256", "source_set", "selected_candidate_identity", "selection_rule_sha256", "closure_policy_sha256", "members", "member_count", "terminal_status_counts", "unterminated_candidate_ids", "closure_status", "non_authority_claims", "closure_sha256"}
    _keys(raw, expected, "family_closure")
    if raw.get("schema") != FAMILY_CLOSURE_SCHEMA or raw.get("analysis") != "verified_discovery_family_closure_v2":
        raise DiscoveryGovernanceV2Error("unsupported family closure")
    _verify_hash(raw, "closure_sha256", "family_closure")
    if raw.get("non_authority_claims") != non_authority_claims():
        raise DiscoveryGovernanceV2Error("closure non-authority claims are invalid")
    source = validate_canonical_source_set(raw.get("source_set")); selected = _candidate(raw.get("selected_candidate_identity"), "selected_candidate_identity")
    for key in ("family_declaration_sha256", "family_ledger_sha256", "selection_rule_sha256", "closure_policy_sha256"):
        _sha(raw.get(key), key)
    members = raw.get("members")
    if not isinstance(members, list) or not members:
        raise DiscoveryGovernanceV2Error("closure members must be a nonempty array")
    checked, unfinished, seen = [], [], set()
    for member in members:
        row = _map(member, "closure member")
        _keys(row, {"candidate_identity", "declared_run_scope_sha256", "declaration_event_sha256", "terminal_event_sha256", "terminal_status", "result_artifact_sha256", "zero_trade"}, "closure member")
        candidate = _candidate(row.get("candidate_identity"), "closure member candidate")
        if _candidate_key(candidate) in seen: raise DiscoveryGovernanceV2Error("duplicate closure candidate identity")
        seen.add(_candidate_key(candidate)); _sha(row.get("declared_run_scope_sha256"), "declared scope"); _sha(row.get("declaration_event_sha256"), "declaration event")
        status = row.get("terminal_status")
        if status == "UNTERMINATED":
            if any(row.get(key) is not None for key in ("terminal_event_sha256", "result_artifact_sha256", "zero_trade")): raise DiscoveryGovernanceV2Error("unterminated member has terminal evidence")
            unfinished.append(candidate["candidate_id"])
        elif status in TERMINAL_STATUSES:
            _sha(row.get("terminal_event_sha256"), "terminal event")
            if status in {"COMPLETED", "FALSIFIED"}: _sha(row.get("result_artifact_sha256"), "result artifact")
            elif row.get("result_artifact_sha256") is not None: _sha(row.get("result_artifact_sha256"), "result artifact")
            if type(row.get("zero_trade")) is not bool: raise DiscoveryGovernanceV2Error("terminal zero_trade must be boolean")
        else: raise DiscoveryGovernanceV2Error("unsupported closure terminal status")
        checked.append(row)
    if raw.get("member_count") != len(checked) or raw.get("terminal_status_counts") != dict(sorted(Counter(row["terminal_status"] for row in checked).items())) or raw.get("unterminated_candidate_ids") != sorted(unfinished):
        raise DiscoveryGovernanceV2Error("closure counts are inconsistent")
    proper = not unfinished and any(row["candidate_identity"] == selected and row["terminal_status"] == "COMPLETED" for row in checked)
    if raw.get("closure_status") != ("CLOSED_VERIFIED" if proper else "CLOSURE_INCOMPLETE"):
        raise DiscoveryGovernanceV2Error("closure status is inconsistent")
    result = _json(raw, "family closure"); result["source_set"] = source
    if family_ledger is not None:
        ledger = verify_family_ledger_v2(family_ledger)
        if ledger["ledger_sha256"] != result["family_ledger_sha256"] or ledger["family_declaration"]["family_declaration_sha256"] != result["family_declaration_sha256"] or not source_sets_equal(ledger["family_declaration"]["source_set"], source) or _members(ledger) != checked:
            raise DiscoveryGovernanceV2Error("closure does not match the exact ledger; post-closure additions are rejected")
    return result


def build_friction_policy_v2(*, policy_id: str, selected_quantile: float, minimum_usable_coverage_fraction: float, maximum_skipped_fraction: float, minimum_usable_quotes_per_required_stratum: int, required_strata: Sequence[str], execution_horizon: str, fee_provenance_sha256: str) -> dict[str, Any]:
    """Make caller-selected coverage, quantile, strata, horizon, and fee identity hash-bound."""
    unsigned = {"schema": FRICTION_POLICY_SCHEMA, "policy_id": _str(policy_id, "policy_id"), "selected_quantile": _num(selected_quantile, "selected_quantile", .5, 1), "minimum_usable_coverage_fraction": _num(minimum_usable_coverage_fraction, "minimum usable coverage", 0, 1), "maximum_skipped_fraction": _num(maximum_skipped_fraction, "maximum skipped", 0, 1), "minimum_usable_quotes_per_required_stratum": _int(minimum_usable_quotes_per_required_stratum, "minimum quotes", 1), "required_strata": _sorted_strings(list(required_strata), "required_strata"), "execution_horizon": _str(execution_horizon, "execution_horizon"), "fee_provenance_sha256": _sha(fee_provenance_sha256, "fee provenance")}
    return _seal(unsigned, "friction_policy_sha256")


def _friction_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "friction_policy")
    needed = {"schema", "policy_id", "selected_quantile", "minimum_usable_coverage_fraction", "maximum_skipped_fraction", "minimum_usable_quotes_per_required_stratum", "required_strata", "execution_horizon", "fee_provenance_sha256", "friction_policy_sha256"}
    _keys(raw, needed, "friction_policy")
    if raw.get("schema") != FRICTION_POLICY_SCHEMA: raise DiscoveryGovernanceV2Error("unsupported friction policy")
    _verify_hash(raw, "friction_policy_sha256", "friction_policy")
    return build_friction_policy_v2(policy_id=raw.get("policy_id"), selected_quantile=raw.get("selected_quantile"), minimum_usable_coverage_fraction=raw.get("minimum_usable_coverage_fraction"), maximum_skipped_fraction=raw.get("maximum_skipped_fraction"), minimum_usable_quotes_per_required_stratum=raw.get("minimum_usable_quotes_per_required_stratum"), required_strata=raw.get("required_strata"), execution_horizon=raw.get("execution_horizon"), fee_provenance_sha256=raw.get("fee_provenance_sha256"))


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values); return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def build_economics_eligibility_v2(*, source_set: Mapping[str, Any], friction_policy: Mapping[str, Any], quote_coverage: Mapping[str, Any], quote_observations: Sequence[Mapping[str, Any]], screen_status: str, report_integrity_ok: bool, declared_round_trip_cost_bps: float, gross_headroom_bps: float) -> dict[str, Any]:
    """Fail closed on failed/indeterminate screens and unusable conservative friction evidence."""
    policy, coverage, sources = _friction_policy(friction_policy), validate_coverage_result(quote_coverage), validate_canonical_source_set(source_set)
    if screen_status not in {"clears_declared_screen", "fails_declared_screen", "indeterminate"} or type(report_integrity_ok) is not bool: raise DiscoveryGovernanceV2Error("invalid economics screen state or report-integrity flag")
    declared, headroom = _num(declared_round_trip_cost_bps, "declared cost", 0), _num(gross_headroom_bps, "gross headroom")
    if not isinstance(quote_observations, Sequence) or isinstance(quote_observations, (str, bytes)) or not quote_observations:
        raise DiscoveryGovernanceV2Error("quote_observations must be a nonempty array covering every expected quote")
    expected = {item["observation_id"]: item["observation"]["availability"] for item in coverage["observations"]}; seen, rows, usable, skipped = set(), [], defaultdict(list), 0
    for item in quote_observations:
        row = _map(item, "quote observation"); _keys(row, {"quote_id", "stratum", "status", "round_trip_cost_bps"}, "quote observation")
        quote_id, stratum, status = _str(row.get("quote_id"), "quote ID"), _str(row.get("stratum"), "stratum"), row.get("status")
        if quote_id in seen or quote_id not in expected: raise DiscoveryGovernanceV2Error("quotes must map exactly one-to-one to coverage observations")
        seen.add(quote_id); cost = row.get("round_trip_cost_bps")
        if status == "USABLE":
            if expected[quote_id] != "OBSERVED": raise DiscoveryGovernanceV2Error("usable quote lacks observed coverage")
            cost = _num(cost, "quote cost", 0); usable[stratum].append(cost)
        elif status == "SKIPPED":
            if expected[quote_id] != "OBSERVED" or cost is not None: raise DiscoveryGovernanceV2Error("skipped quote shape is invalid")
            skipped += 1
        elif status == "MISSING":
            if expected[quote_id] != "MISSING" or cost is not None: raise DiscoveryGovernanceV2Error("missing quote must mirror missing coverage")
            skipped += 1
        else: raise DiscoveryGovernanceV2Error("quote status must be USABLE, SKIPPED, or MISSING")
        rows.append({"quote_id": quote_id, "stratum": stratum, "status": status, "round_trip_cost_bps": cost})
    if seen != set(expected): raise DiscoveryGovernanceV2Error("every expected quote must be explicit")
    rows.sort(key=lambda item: item["quote_id"]); total = len(rows); usable_count = sum(map(len, usable.values())); cov, skip = usable_count / total, skipped / total
    required = {}; missing_stratum = False
    for stratum in policy["required_strata"]:
        values = usable.get(stratum, [])
        required[stratum] = _quantile(values, policy["selected_quantile"]) if len(values) >= policy["minimum_usable_quotes_per_required_stratum"] else None
        missing_stratum |= required[stratum] is None
    floor = max((value for value in required.values() if value is not None), default=None)
    reasons = []
    if coverage["status"] != "COMPLETE": reasons.append("quote_coverage_incomplete")
    if cov < policy["minimum_usable_coverage_fraction"]: reasons.append("usable_quote_coverage_below_policy")
    if skip > policy["maximum_skipped_fraction"]: reasons.append("skipped_quote_fraction_above_policy")
    if missing_stratum: reasons.append("required_friction_stratum_unavailable")
    if screen_status != "clears_declared_screen": reasons.append(f"economics_screen_{screen_status}")
    if not report_integrity_ok: reasons.append("economics_report_integrity_failed")
    if floor is None: reasons.append("conservative_friction_floor_indeterminate")
    elif declared < floor: reasons.append("declared_cost_below_conservative_friction_floor")
    elif headroom <= floor: reasons.append("gross_headroom_does_not_cover_conservative_friction_floor")
    friction_ok = not any(reason in {"quote_coverage_incomplete", "usable_quote_coverage_below_policy", "skipped_quote_fraction_above_policy", "required_friction_stratum_unavailable", "conservative_friction_floor_indeterminate"} for reason in reasons)
    unsigned = {"schema": ECONOMICS_SCHEMA, "analysis": "measured_conservative_friction_economics_eligibility_v2", "source_set": sources, "friction_policy": policy, "quote_coverage": coverage, "quote_observations": rows, "screen_status": screen_status, "report_integrity_ok": report_integrity_ok, "declared_round_trip_cost_bps": declared, "gross_headroom_bps": headroom, "usable_quote_count": usable_count, "expected_quote_count": total, "usable_coverage_fraction": cov, "skipped_quote_fraction": skip, "required_conservative_cost_by_stratum_bps": required, "required_round_trip_cost_floor_bps": floor, "headroom_after_required_floor_bps": headroom-floor if floor is not None else None, "friction_evidence_eligible": friction_ok, "economics_eligible": not reasons, "eligibility_reasons": reasons, "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "economics_eligibility_sha256")


def verify_economics_eligibility_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "economics eligibility")
    needed = {"schema", "analysis", "source_set", "friction_policy", "quote_coverage", "quote_observations", "screen_status", "report_integrity_ok", "declared_round_trip_cost_bps", "gross_headroom_bps", "usable_quote_count", "expected_quote_count", "usable_coverage_fraction", "skipped_quote_fraction", "required_conservative_cost_by_stratum_bps", "required_round_trip_cost_floor_bps", "headroom_after_required_floor_bps", "friction_evidence_eligible", "economics_eligible", "eligibility_reasons", "non_authority_claims", "economics_eligibility_sha256"}
    _keys(raw, needed, "economics eligibility"); _verify_hash(raw, "economics_eligibility_sha256", "economics eligibility")
    rebuilt = build_economics_eligibility_v2(source_set=raw.get("source_set"), friction_policy=raw.get("friction_policy"), quote_coverage=raw.get("quote_coverage"), quote_observations=raw.get("quote_observations"), screen_status=raw.get("screen_status"), report_integrity_ok=raw.get("report_integrity_ok"), declared_round_trip_cost_bps=raw.get("declared_round_trip_cost_bps"), gross_headroom_bps=raw.get("gross_headroom_bps"))
    if raw != rebuilt: raise DiscoveryGovernanceV2Error("economics eligibility is not deterministic or has been altered")
    return rebuilt


def build_cluster_contract_v2(*, policy_id: str, cluster_definition: str, dataset_manifest_sha256: str, source_set: Mapping[str, Any], minimum_completed_clusters: int, cscv_partitions: int, reality_check_resamples: int, block_length: int, seed: int) -> dict[str, Any]:
    """Declare source-bound dependence units and all selection-statistic parameters."""
    partitions = _int(cscv_partitions, "partitions", 4)
    resamples = _int(reality_check_resamples, "resamples", 100)
    if partitions % 2:
        raise DiscoveryGovernanceV2Error("cluster policy needs even >=4 CSCV partitions and >=100 resamples")
    unsigned = {"schema": CLUSTER_CONTRACT_SCHEMA, "policy_id": _str(policy_id, "policy_id"), "cluster_definition": _str(cluster_definition, "cluster_definition"), "dataset_manifest_sha256": _sha(dataset_manifest_sha256, "dataset manifest"), "source_set": validate_canonical_source_set(source_set), "minimum_completed_clusters": _int(minimum_completed_clusters, "minimum clusters", 1), "cscv_partitions": partitions, "reality_check_resamples": resamples, "block_length": _int(block_length, "block length", 1), "seed": _int(seed, "seed")}
    return _seal(unsigned, "cluster_policy_sha256")


def _cluster_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "cluster_contract")
    needed = {"schema", "policy_id", "cluster_definition", "dataset_manifest_sha256", "source_set", "minimum_completed_clusters", "cscv_partitions", "reality_check_resamples", "block_length", "seed", "cluster_policy_sha256"}
    _keys(raw, needed, "cluster_contract")
    if raw.get("schema") != CLUSTER_CONTRACT_SCHEMA: raise DiscoveryGovernanceV2Error("unsupported cluster contract")
    _verify_hash(raw, "cluster_policy_sha256", "cluster_contract")
    return build_cluster_contract_v2(policy_id=raw.get("policy_id"), cluster_definition=raw.get("cluster_definition"), dataset_manifest_sha256=raw.get("dataset_manifest_sha256"), source_set=raw.get("source_set"), minimum_completed_clusters=raw.get("minimum_completed_clusters"), cscv_partitions=raw.get("cscv_partitions"), reality_check_resamples=raw.get("reality_check_resamples"), block_length=raw.get("block_length"), seed=raw.get("seed"))


def build_cluster_matrix_v2(observations: Sequence[Mapping[str, Any]], *, cluster_contract: Mapping[str, Any], family_closure: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate raw rows to declared clusters and reject missing/mixed provenance."""
    contract, closure = _cluster_contract(cluster_contract), verify_family_closure_v2(family_closure)
    if closure["closure_status"] != "CLOSED_VERIFIED" or not source_sets_equal(contract["source_set"], closure["source_set"]):
        raise DiscoveryGovernanceV2Error("cluster input requires a closed family and exact verified source set")
    candidates = {_candidate_key(row["candidate_identity"]): row["candidate_identity"] for row in closure["members"]}
    if not observations: raise DiscoveryGovernanceV2Error("cluster observations must not be empty")
    grouped: dict[tuple[tuple[str, str], str], list[float]] = defaultdict(list)
    for item in observations:
        row = _map(item, "cluster observation"); _keys(row, {"candidate_identity", "cluster_id", "cluster_definition", "dataset_manifest_sha256", "net_return_bps"}, "cluster observation")
        candidate = _candidate(row.get("candidate_identity"), "cluster candidate"); key = _candidate_key(candidate)
        if key not in candidates: raise DiscoveryGovernanceV2Error("cluster candidate is not a closed-family identity")
        if _str(row.get("cluster_definition"), "cluster definition") != contract["cluster_definition"] or _sha(row.get("dataset_manifest_sha256"), "dataset manifest") != contract["dataset_manifest_sha256"]:
            raise DiscoveryGovernanceV2Error("mixed cluster definition or dataset provenance")
        grouped[(key, _str(row.get("cluster_id"), "cluster ID"))].append(_num(row.get("net_return_bps"), "net return"))
    clusters = sorted({cluster for _, cluster in grouped}); candidate_keys = sorted(candidates)
    missing = [
        f"{candidate_id}:{cluster}"
        for candidate_id, spec_sha256 in candidate_keys
        for cluster in clusters
        if ((candidate_id, spec_sha256), cluster) not in grouped
    ]
    if missing: raise DiscoveryGovernanceV2Error("cluster matrix is not rectangular: " + ",".join(missing))
    matrix = []
    for cluster in clusters:
        values = []
        for key in candidate_keys:
            raw_values = grouped[(key, cluster)]
            values.append({"candidate_identity": candidates[key], "cluster_net_return_bps": fmean(raw_values), "raw_subevent_count": len(raw_values)})
        matrix.append({"cluster_id": cluster, "candidate_values": values})
    unsigned = {"schema": CLUSTER_MATRIX_SCHEMA, "analysis": "verified_cluster_provenance_family_matrix_v2", "source_set": closure["source_set"], "family_closure_sha256": closure["closure_sha256"], "family_ledger_sha256": closure["family_ledger_sha256"], "cluster_contract": contract, "matrix": matrix, "raw_observation_count": sum(len(values) for values in grouped.values()), "effective_cluster_count": len(clusters), "candidate_count": len(candidate_keys), "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "cluster_matrix_sha256")


def verify_cluster_matrix_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "cluster matrix")
    needed = {"schema", "analysis", "source_set", "family_closure_sha256", "family_ledger_sha256", "cluster_contract", "matrix", "raw_observation_count", "effective_cluster_count", "candidate_count", "non_authority_claims", "cluster_matrix_sha256"}
    _keys(raw, needed, "cluster matrix")
    if raw.get("schema") != CLUSTER_MATRIX_SCHEMA or raw.get("analysis") != "verified_cluster_provenance_family_matrix_v2": raise DiscoveryGovernanceV2Error("unsupported cluster matrix")
    _verify_hash(raw, "cluster_matrix_sha256", "cluster matrix")
    if raw.get("non_authority_claims") != non_authority_claims(): raise DiscoveryGovernanceV2Error("invalid cluster non-authority claims")
    source, contract = validate_canonical_source_set(raw.get("source_set")), _cluster_contract(raw.get("cluster_contract"))
    if not source_sets_equal(source, contract["source_set"]): raise DiscoveryGovernanceV2Error("matrix source set does not equal cluster provenance")
    _sha(raw.get("family_closure_sha256"), "closure hash"); _sha(raw.get("family_ledger_sha256"), "ledger hash")
    matrix = raw.get("matrix")
    if not isinstance(matrix, list) or not matrix: raise DiscoveryGovernanceV2Error("cluster matrix rows must be nonempty")
    cluster_ids, candidate_keys, raw_count = [], None, 0
    for item in matrix:
        row = _map(item, "matrix row"); _keys(row, {"cluster_id", "candidate_values"}, "matrix row")
        cluster_ids.append(_str(row.get("cluster_id"), "cluster ID")); values = row.get("candidate_values")
        if not isinstance(values, list) or not values: raise DiscoveryGovernanceV2Error("matrix candidate values must be nonempty")
        current = []
        for candidate_row in values:
            cell = _map(candidate_row, "matrix cell"); _keys(cell, {"candidate_identity", "cluster_net_return_bps", "raw_subevent_count"}, "matrix cell")
            current.append(_candidate_key(_candidate(cell.get("candidate_identity"), "matrix candidate"))); _num(cell.get("cluster_net_return_bps"), "cluster net"); raw_count += _int(cell.get("raw_subevent_count"), "raw subevent count", 1)
        if current != sorted(current) or len(current) != len(set(current)): raise DiscoveryGovernanceV2Error("matrix candidate identities must be sorted and unique")
        if candidate_keys is None: candidate_keys = current
        elif candidate_keys != current: raise DiscoveryGovernanceV2Error("matrix must be rectangular")
    if cluster_ids != sorted(cluster_ids) or len(cluster_ids) != len(set(cluster_ids)) or raw.get("raw_observation_count") != raw_count or raw.get("effective_cluster_count") != len(cluster_ids) or raw.get("candidate_count") != len(candidate_keys or []): raise DiscoveryGovernanceV2Error("matrix counts/order are invalid")
    return _json(raw, "cluster matrix")


def _sharpe(values: Sequence[float]) -> float | None:
    if len(values) < 2: return None
    deviation = stdev(values)
    # Infinity is not canonical JSON and would make the self-hash ambiguous.
    # Preserve the metric as explicitly undefined rather than manufacturing an
    # infinitely favorable or unfavorable selection statistic.
    if deviation == 0:
        return None
    return fmean(values) / deviation


def _pbo(columns: Mapping[str, Sequence[float]], partitions: int) -> dict[str, Any] | None:
    names = sorted(columns); n = len(next(iter(columns.values())))
    if len(names) < 2 or n < partitions: return None
    blocks = [[] for _ in range(partitions)]
    for index in range(n): blocks[index * partitions // n].append(index)
    logits = []
    for train_blocks in combinations(range(partitions), partitions//2):
        train = [idx for block in train_blocks for idx in blocks[block]]; test = [idx for block in range(partitions) if block not in train_blocks for idx in blocks[block]]
        train_scores = {name: _sharpe([columns[name][idx] for idx in train]) for name in names}; winner = max(names, key=lambda name: (train_scores[name] if train_scores[name] is not None else -math.inf, name))
        scores = {name: _sharpe([columns[name][idx] for idx in test]) for name in names}; score = scores[winner] if scores[winner] is not None else -math.inf
        worse, ties = sum(x is not None and x < score for x in scores.values()), sum(x == score for x in scores.values()); omega = min(1-1e-12, max(1e-12, (worse+.5*ties)/len(names))); logits.append(math.log(omega/(1-omega)))
    return {"pbo": sum(item <= 0 for item in logits)/len(logits), "splits": len(logits), "median_logit": sorted(logits)[len(logits)//2]}


def _reality(columns: Mapping[str, Sequence[float]], resamples: int, block_length: int, seed: int) -> dict[str, float]:
    names, n = sorted(columns), len(next(iter(columns.values()))); means = {name: fmean(columns[name]) for name in names}; observed = max(means.values()); centered = {name: [value-means[name] for value in columns[name]] for name in names}; rng, greater, block = random.Random(seed), 0, min(block_length, n)
    for _ in range(resamples):
        indexes = []
        for _ in range(math.ceil(n/block)):
            start = rng.randrange(n); indexes.extend((start+i) % n for i in range(block))
        if max(fmean([centered[name][index] for index in indexes[:n]]) for name in names) >= observed: greater += 1
    return {"observed_best_mean_bps": observed, "bootstrap_p_value": (greater+1)/(resamples+1)}


def build_cluster_inference_v2(cluster_matrix: Mapping[str, Any]) -> dict[str, Any]:
    """Run DSR/PBO/Reality-Check-style diagnostics at the verified cluster unit only."""
    matrix = verify_cluster_matrix_v2(cluster_matrix); contract = matrix["cluster_contract"]; columns: dict[str, list[float]] = defaultdict(list)
    for row in matrix["matrix"]:
        for cell in row["candidate_values"]: columns[cell["candidate_identity"]["candidate_id"]].append(cell["cluster_net_return_bps"])
    columns = dict(sorted(columns.items())); effective = matrix["effective_cluster_count"]; eligible = effective >= contract["minimum_completed_clusters"]
    per_candidate = {name: {"cluster_mean_net_return_bps": fmean(values), "cluster_sharpe": _sharpe(values), "cluster_count": len(values)} for name, values in columns.items()}
    if eligible:
        chosen = max(columns, key=lambda name: (per_candidate[name]["cluster_mean_net_return_bps"], name)); sharpes = [item["cluster_sharpe"] if item["cluster_sharpe"] is not None and math.isfinite(item["cluster_sharpe"]) else 0.0 for item in per_candidate.values()]; expected = fmean(sharpes) if len(sharpes)==1 else fmean(sharpes)+stdev(sharpes)*((1-.5772156649015329)*NormalDist().inv_cdf(1-1/len(sharpes))+.5772156649015329*NormalDist().inv_cdf(1-1/(len(sharpes)*math.e)))
        current = per_candidate[chosen]["cluster_sharpe"]; probability = None if current is None or not math.isfinite(current) else NormalDist().cdf((current-expected)*math.sqrt(max(1,effective-1)))
        diagnostics = {"selected_candidate_id": chosen, "deflated_sharpe": {"selected_cluster_sharpe": current, "expected_max_cluster_sharpe": expected, "probability": probability}, "pbo_cscv": _pbo(columns, contract["cscv_partitions"]), "reality_check": _reality(columns, contract["reality_check_resamples"], contract["block_length"], contract["seed"])}
    else: diagnostics = {"status": "insufficient_verified_clusters", "required": contract["minimum_completed_clusters"], "observed": effective}
    unsigned = {"schema": CLUSTER_INFERENCE_SCHEMA, "analysis": "cluster_level_family_selection_diagnostics_v2", "source_set": matrix["source_set"], "family_closure_sha256": matrix["family_closure_sha256"], "cluster_matrix_sha256": matrix["cluster_matrix_sha256"], "cluster_policy_sha256": contract["cluster_policy_sha256"], "raw_observation_count": matrix["raw_observation_count"], "effective_cluster_count": effective, "per_candidate": per_candidate, "selection_diagnostics": diagnostics, "inference_eligible": eligible, "eligibility_reasons": [] if eligible else ["minimum_verified_cluster_count_not_met"], "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "cluster_inference_sha256")


def verify_cluster_inference_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "cluster inference")
    needed = {"schema", "analysis", "source_set", "family_closure_sha256", "cluster_matrix_sha256", "cluster_policy_sha256", "raw_observation_count", "effective_cluster_count", "per_candidate", "selection_diagnostics", "inference_eligible", "eligibility_reasons", "non_authority_claims", "cluster_inference_sha256"}
    _keys(raw, needed, "cluster inference")
    if raw.get("schema") != CLUSTER_INFERENCE_SCHEMA or raw.get("analysis") != "cluster_level_family_selection_diagnostics_v2" or type(raw.get("inference_eligible")) is not bool or raw.get("non_authority_claims") != non_authority_claims(): raise DiscoveryGovernanceV2Error("invalid cluster inference")
    _verify_hash(raw, "cluster_inference_sha256", "cluster inference"); validate_canonical_source_set(raw.get("source_set")); _sha(raw.get("family_closure_sha256"), "closure hash"); _sha(raw.get("cluster_matrix_sha256"), "matrix hash"); _sha(raw.get("cluster_policy_sha256"), "cluster policy")
    if _int(raw.get("effective_cluster_count"), "cluster count") < 0 or _int(raw.get("raw_observation_count"), "raw count") < 0: raise DiscoveryGovernanceV2Error("invalid cluster counts")
    return _json(raw, "cluster inference")


def build_benchmark_policy_v2(*, policy_id: str, benchmark_id: str, formula: str, rationale: str, applicability: str, requires_positive_incremental_return: bool) -> dict[str, Any]:
    """Declare a benchmark before D0 graduation; non-applicability remains non-passing evidence."""
    if applicability not in {"REQUIRED", "NOT_APPLICABLE_WITH_FROZEN_RATIONALE"} or type(requires_positive_incremental_return) is not bool:
        raise DiscoveryGovernanceV2Error("invalid benchmark policy applicability or requirement")
    unsigned = {"schema": BENCHMARK_POLICY_SCHEMA, "policy_id": _str(policy_id, "benchmark policy ID"), "benchmark_id": _str(benchmark_id, "benchmark ID"), "formula": _str(formula, "benchmark formula"), "rationale": _str(rationale, "benchmark rationale"), "applicability": applicability, "requires_positive_incremental_return": requires_positive_incremental_return}
    return _seal(unsigned, "benchmark_policy_sha256")


def _benchmark_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "benchmark policy")
    needed = {"schema", "policy_id", "benchmark_id", "formula", "rationale", "applicability", "requires_positive_incremental_return", "benchmark_policy_sha256"}
    _keys(raw, needed, "benchmark policy")
    if raw.get("schema") != BENCHMARK_POLICY_SCHEMA: raise DiscoveryGovernanceV2Error("unsupported benchmark policy")
    _verify_hash(raw, "benchmark_policy_sha256", "benchmark policy")
    return build_benchmark_policy_v2(policy_id=raw.get("policy_id"), benchmark_id=raw.get("benchmark_id"), formula=raw.get("formula"), rationale=raw.get("rationale"), applicability=raw.get("applicability"), requires_positive_incremental_return=raw.get("requires_positive_incremental_return"))


def build_benchmark_assessment_v2(*, family_closure: Mapping[str, Any], cluster_matrix: Mapping[str, Any], benchmark_policy: Mapping[str, Any], aligned_observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare candidate and benchmark at identical completed clusters/accounting identities."""
    closure, matrix, policy = verify_family_closure_v2(family_closure), verify_cluster_matrix_v2(cluster_matrix), _benchmark_policy(benchmark_policy)
    if closure["closure_status"] != "CLOSED_VERIFIED" or closure["closure_sha256"] != matrix["family_closure_sha256"] or not source_sets_equal(closure["source_set"], matrix["source_set"]):
        raise DiscoveryGovernanceV2Error("benchmark must use the exact verified closed-family cluster matrix")
    selected = closure["selected_candidate_identity"]
    if policy["applicability"] == "NOT_APPLICABLE_WITH_FROZEN_RATIONALE":
        if aligned_observations: raise DiscoveryGovernanceV2Error("not-applicable benchmark cannot include aligned observations")
        rows, incrementals, status, eligible = [], [], "NOT_APPLICABLE", False
    else:
        expected = {}
        for row in matrix["matrix"]:
            for cell in row["candidate_values"]:
                if cell["candidate_identity"] == selected: expected[row["cluster_id"]] = cell["cluster_net_return_bps"]
        if not expected: raise DiscoveryGovernanceV2Error("selected candidate missing from cluster matrix")
        rows, seen, incrementals = [], set(), []
        for item in aligned_observations:
            row = _map(item, "benchmark observation")
            needed = {"cluster_id", "candidate_net_return_bps", "benchmark_net_return_bps", "accounting_identity_sha256", "cost_identity_sha256", "funding_identity_sha256"}
            _keys(row, needed, "benchmark observation")
            cluster = _str(row.get("cluster_id"), "benchmark cluster")
            if cluster in seen or cluster not in expected: raise DiscoveryGovernanceV2Error("benchmark clusters must exactly match candidate clusters")
            seen.add(cluster); candidate_return = _num(row.get("candidate_net_return_bps"), "candidate return")
            if candidate_return != expected[cluster]: raise DiscoveryGovernanceV2Error("benchmark candidate return is not the verified cluster-matrix value")
            benchmark_return = _num(row.get("benchmark_net_return_bps"), "benchmark return")
            identities = {name: _sha(row.get(name), name) for name in ("accounting_identity_sha256", "cost_identity_sha256", "funding_identity_sha256")}
            rows.append({"cluster_id": cluster, "candidate_net_return_bps": candidate_return, "benchmark_net_return_bps": benchmark_return, **identities}); incrementals.append(candidate_return-benchmark_return)
        if seen != set(expected): raise DiscoveryGovernanceV2Error("benchmark observations must cover every completed candidate cluster")
        rows.sort(key=lambda item: item["cluster_id"]); candidate_values, benchmark_values = [row["candidate_net_return_bps"] for row in rows], [row["benchmark_net_return_bps"] for row in rows]
        mean_candidate, mean_benchmark, mean_incremental = fmean(candidate_values), fmean(benchmark_values), fmean(incrementals)
        variance = fmean([(item-mean_benchmark)**2 for item in benchmark_values]); covariance = fmean([(candidate_values[index]-mean_candidate)*(benchmark_values[index]-mean_benchmark) for index in range(len(rows))]); beta = covariance/variance if variance > 0 else None
        eligible = (mean_incremental > 0) if policy["requires_positive_incremental_return"] else True; status = "PASS" if eligible else "FAILS_INCREMENTAL_BENCHMARK"
    if rows:
        mean_candidate, mean_benchmark, mean_incremental = fmean([row["candidate_net_return_bps"] for row in rows]), fmean([row["benchmark_net_return_bps"] for row in rows]), fmean(incrementals)
        variance = fmean([(row["benchmark_net_return_bps"]-mean_benchmark)**2 for row in rows]); covariance = fmean([(row["candidate_net_return_bps"]-mean_candidate)*(row["benchmark_net_return_bps"]-mean_benchmark) for row in rows]); beta = covariance/variance if variance > 0 else None
    else: mean_candidate = mean_benchmark = mean_incremental = beta = None
    unsigned = {"schema": BENCHMARK_SCHEMA, "analysis": "economically_aligned_benchmark_assessment_v2", "source_set": closure["source_set"], "family_closure_sha256": closure["closure_sha256"], "cluster_matrix_sha256": matrix["cluster_matrix_sha256"], "candidate_identity": selected, "benchmark_policy": policy, "aligned_observations": rows, "aligned_cluster_count": len(rows), "candidate_mean_net_return_bps": mean_candidate, "benchmark_mean_net_return_bps": mean_benchmark, "incremental_mean_net_return_bps": mean_incremental, "market_beta_diagnostic": beta, "benchmark_status": status, "benchmark_eligible": eligible, "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "benchmark_assessment_sha256")


def verify_benchmark_assessment_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "benchmark assessment")
    needed = {"schema", "analysis", "source_set", "family_closure_sha256", "cluster_matrix_sha256", "candidate_identity", "benchmark_policy", "aligned_observations", "aligned_cluster_count", "candidate_mean_net_return_bps", "benchmark_mean_net_return_bps", "incremental_mean_net_return_bps", "market_beta_diagnostic", "benchmark_status", "benchmark_eligible", "non_authority_claims", "benchmark_assessment_sha256"}
    _keys(raw, needed, "benchmark assessment")
    if raw.get("schema") != BENCHMARK_SCHEMA or raw.get("analysis") != "economically_aligned_benchmark_assessment_v2" or type(raw.get("benchmark_eligible")) is not bool or raw.get("non_authority_claims") != non_authority_claims(): raise DiscoveryGovernanceV2Error("invalid benchmark assessment")
    _verify_hash(raw, "benchmark_assessment_sha256", "benchmark assessment"); validate_canonical_source_set(raw.get("source_set")); _sha(raw.get("family_closure_sha256"), "closure hash"); _sha(raw.get("cluster_matrix_sha256"), "matrix hash"); _candidate(raw.get("candidate_identity"), "benchmark candidate"); policy = _benchmark_policy(raw.get("benchmark_policy"))
    rows = raw.get("aligned_observations")
    if not isinstance(rows, list) or raw.get("aligned_cluster_count") != len(rows): raise DiscoveryGovernanceV2Error("benchmark alignment count is invalid")
    if policy["applicability"] == "NOT_APPLICABLE_WITH_FROZEN_RATIONALE" and (rows or raw.get("benchmark_eligible") or raw.get("benchmark_status") != "NOT_APPLICABLE"): raise DiscoveryGovernanceV2Error("not-applicable benchmark cannot pass")
    return _json(raw, "benchmark assessment")


def build_evaluation_binding_v2(*, candidate_identity: Mapping[str, Any], source_set: Mapping[str, Any], candidate_result_sha256: str, dataset_manifest_sha256: str, code_revision_sha256: str, gate_config_sha256: str, controls_sha256: str, hard_gates: Mapping[str, bool], not_applicable_gates: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Bind candidate/spec/time to evaluator code, dataset, gates, controls, and D0 result."""
    gates = _map(hard_gates, "hard_gates")
    if not gates or any(not isinstance(name, str) or type(passed) is not bool for name, passed in gates.items()): raise DiscoveryGovernanceV2Error("hard_gates must be a nonempty bool map")
    nas = _map(not_applicable_gates or {}, "not_applicable_gates")
    if set(gates) & set(nas) or any(not isinstance(name, str) or not isinstance(reason, str) or not reason.strip() for name, reason in nas.items()): raise DiscoveryGovernanceV2Error("not-applicable gates must be disjoint with explicit rationales")
    unsigned = {"schema": EVALUATION_SCHEMA, "analysis": "hash_bound_discovery_evaluation_binding_v2", "candidate_identity": _candidate(candidate_identity), "source_set": validate_canonical_source_set(source_set), "candidate_result_sha256": _sha(candidate_result_sha256, "candidate result"), "dataset_manifest_sha256": _sha(dataset_manifest_sha256, "dataset manifest"), "code_revision_sha256": _sha(code_revision_sha256, "code revision"), "gate_config_sha256": _sha(gate_config_sha256, "gate config"), "controls_sha256": _sha(controls_sha256, "controls"), "hard_gates": dict(sorted(gates.items())), "not_applicable_gates": dict(sorted((str(k), str(v).strip()) for k,v in nas.items())), "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "evaluation_binding_sha256")


def verify_evaluation_binding_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "evaluation binding")
    needed = {"schema", "analysis", "candidate_identity", "source_set", "candidate_result_sha256", "dataset_manifest_sha256", "code_revision_sha256", "gate_config_sha256", "controls_sha256", "hard_gates", "not_applicable_gates", "non_authority_claims", "evaluation_binding_sha256"}
    _keys(raw, needed, "evaluation binding")
    if raw.get("schema") != EVALUATION_SCHEMA or raw.get("analysis") != "hash_bound_discovery_evaluation_binding_v2": raise DiscoveryGovernanceV2Error("unsupported evaluation binding")
    _verify_hash(raw, "evaluation_binding_sha256", "evaluation binding")
    rebuilt = build_evaluation_binding_v2(candidate_identity=raw.get("candidate_identity"), source_set=raw.get("source_set"), candidate_result_sha256=raw.get("candidate_result_sha256"), dataset_manifest_sha256=raw.get("dataset_manifest_sha256"), code_revision_sha256=raw.get("code_revision_sha256"), gate_config_sha256=raw.get("gate_config_sha256"), controls_sha256=raw.get("controls_sha256"), hard_gates=raw.get("hard_gates"), not_applicable_gates=raw.get("not_applicable_gates"))
    if raw != rebuilt: raise DiscoveryGovernanceV2Error("evaluation binding has been altered")
    return rebuilt


def build_graduation_policy_v2(*, policy_id: str, required_gate_names: Sequence[str], allowed_not_applicable_gate_names: Sequence[str]) -> dict[str, Any]:
    """Caller-declare required D0 gates; no absent gate can become an implicit pass."""
    required, allowed = _sorted_strings(list(required_gate_names), "required gates"), _sorted_strings(list(allowed_not_applicable_gate_names), "allowed N/A gates") if allowed_not_applicable_gate_names else []
    if not set(allowed).issubset(required): raise DiscoveryGovernanceV2Error("allowed N/A gates must be required gates")
    return _seal({"schema": GRADUATION_POLICY_SCHEMA, "policy_id": _str(policy_id, "graduation policy ID"), "required_gate_names": required, "allowed_not_applicable_gate_names": allowed}, "graduation_policy_sha256")


def _graduation_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "graduation policy")
    needed = {"schema", "policy_id", "required_gate_names", "allowed_not_applicable_gate_names", "graduation_policy_sha256"}
    _keys(raw, needed, "graduation policy")
    if raw.get("schema") != GRADUATION_POLICY_SCHEMA: raise DiscoveryGovernanceV2Error("unsupported graduation policy")
    _verify_hash(raw, "graduation_policy_sha256", "graduation policy")
    return build_graduation_policy_v2(policy_id=raw.get("policy_id"), required_gate_names=raw.get("required_gate_names"), allowed_not_applicable_gate_names=raw.get("allowed_not_applicable_gate_names"))


def build_graduation_binding_v2(*, family_closure: Mapping[str, Any], evaluation_binding: Mapping[str, Any], economics_eligibility: Mapping[str, Any], cluster_inference: Mapping[str, Any], benchmark_assessment: Mapping[str, Any], graduation_policy: Mapping[str, Any]) -> dict[str, Any]:
    """The sole prospective transition to ``REPLICATION_PENDING``.

    Missing, failed, or mismatched family/identity/gate/economics/cluster/
    benchmark evidence produces the terminal ``FALSIFIED``/``INELIGIBLE``
    result rather than an ambiguous passing state.  This is discovery evidence,
    never validation or promotion authorization.
    """
    closure = verify_family_closure_v2(family_closure); evaluation = verify_evaluation_binding_v2(evaluation_binding); economics = verify_economics_eligibility_v2(economics_eligibility); inference = verify_cluster_inference_v2(cluster_inference); benchmark = verify_benchmark_assessment_v2(benchmark_assessment); policy = _graduation_policy(graduation_policy)
    selected = closure["selected_candidate_identity"]; reasons = []
    all_sources = [closure["source_set"], evaluation["source_set"], economics["source_set"], inference["source_set"], benchmark["source_set"]]
    if not all(source_sets_equal(all_sources[0], item) for item in all_sources[1:]): reasons.append("source_set_mismatch")
    if closure["closure_status"] != "CLOSED_VERIFIED": reasons.append("family_closure_not_verified")
    if evaluation["candidate_identity"] != selected: reasons.append("evaluation_candidate_identity_mismatch")
    if benchmark["candidate_identity"] != selected: reasons.append("benchmark_candidate_identity_mismatch")
    if inference["family_closure_sha256"] != closure["closure_sha256"]: reasons.append("cluster_inference_closure_mismatch")
    if benchmark["family_closure_sha256"] != closure["closure_sha256"]: reasons.append("benchmark_closure_mismatch")
    required, supplied = set(policy["required_gate_names"]), set(evaluation["hard_gates"]) | set(evaluation["not_applicable_gates"])
    if supplied != required: reasons.append("required_gate_set_incomplete_or_extra")
    for gate in required:
        if gate in evaluation["hard_gates"] and evaluation["hard_gates"][gate] is not True: reasons.append(f"hard_gate_failed:{gate}")
        if gate in evaluation["not_applicable_gates"] and gate not in policy["allowed_not_applicable_gate_names"]: reasons.append(f"not_applicable_gate_not_allowed:{gate}")
    if not economics["economics_eligible"]: reasons.append("economics_ineligible")
    if not economics["friction_evidence_eligible"]: reasons.append("friction_evidence_ineligible")
    if not inference["inference_eligible"]: reasons.append("cluster_inference_ineligible")
    if not benchmark["benchmark_eligible"]: reasons.append("benchmark_ineligible")
    unique = list(dict.fromkeys(reasons)); status = "ELIGIBLE" if not unique else "INELIGIBLE"; terminal = "REPLICATION_PENDING" if not unique else "FALSIFIED"
    unsigned = {"schema": GRADUATION_SCHEMA, "analysis": "hash_bound_discovery_graduation_v2", "source_set": closure["source_set"], "family_closure_sha256": closure["closure_sha256"], "family_ledger_sha256": closure["family_ledger_sha256"], "candidate_identity": selected, "evaluation_binding_sha256": evaluation["evaluation_binding_sha256"], "candidate_result_sha256": evaluation["candidate_result_sha256"], "dataset_manifest_sha256": evaluation["dataset_manifest_sha256"], "code_revision_sha256": evaluation["code_revision_sha256"], "gate_config_sha256": evaluation["gate_config_sha256"], "controls_sha256": evaluation["controls_sha256"], "economics_eligibility_sha256": economics["economics_eligibility_sha256"], "cluster_inference_sha256": inference["cluster_inference_sha256"], "benchmark_assessment_sha256": benchmark["benchmark_assessment_sha256"], "graduation_policy": policy, "checks": {"family_closure": closure["closure_status"] == "CLOSED_VERIFIED", "exact_source_set": "source_set_mismatch" not in unique, "identity": not any("identity_mismatch" in item for item in unique), "declared_hard_gates": not any(item.startswith("hard_gate_failed") or item == "required_gate_set_incomplete_or_extra" or item.startswith("not_applicable_gate") for item in unique), "economics": economics["economics_eligible"], "cluster_inference": inference["inference_eligible"], "benchmark": benchmark["benchmark_eligible"]}, "graduation_status": status, "terminal_state": terminal, "reasons": unique, "claims": {"is_locked_validation": False, "profitable_edge_established": False, "promotion_authorized": False, "live_order_transmission_supported": False}, "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "graduation_sha256")


def verify_graduation_binding_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "graduation binding")
    needed = {"schema", "analysis", "source_set", "family_closure_sha256", "family_ledger_sha256", "candidate_identity", "evaluation_binding_sha256", "candidate_result_sha256", "dataset_manifest_sha256", "code_revision_sha256", "gate_config_sha256", "controls_sha256", "economics_eligibility_sha256", "cluster_inference_sha256", "benchmark_assessment_sha256", "graduation_policy", "checks", "graduation_status", "terminal_state", "reasons", "claims", "non_authority_claims", "graduation_sha256"}
    _keys(raw, needed, "graduation binding")
    if raw.get("schema") != GRADUATION_SCHEMA or raw.get("analysis") != "hash_bound_discovery_graduation_v2" or raw.get("graduation_status") not in {"ELIGIBLE", "INELIGIBLE"} or raw.get("terminal_state") not in {"REPLICATION_PENDING", "FALSIFIED"}: raise DiscoveryGovernanceV2Error("unsupported graduation binding")
    _verify_hash(raw, "graduation_sha256", "graduation binding"); validate_canonical_source_set(raw.get("source_set")); _candidate(raw.get("candidate_identity"), "graduation candidate")
    for name in ("family_closure_sha256", "family_ledger_sha256", "evaluation_binding_sha256", "candidate_result_sha256", "dataset_manifest_sha256", "code_revision_sha256", "gate_config_sha256", "controls_sha256", "economics_eligibility_sha256", "cluster_inference_sha256", "benchmark_assessment_sha256"):_sha(raw.get(name), name)
    _graduation_policy(raw.get("graduation_policy"))
    if raw.get("non_authority_claims") != non_authority_claims() or raw.get("claims") != {"is_locked_validation": False, "profitable_edge_established": False, "promotion_authorized": False, "live_order_transmission_supported": False}: raise DiscoveryGovernanceV2Error("graduation authority claims are invalid")
    if (raw["graduation_status"] == "ELIGIBLE") != (raw["terminal_state"] == "REPLICATION_PENDING") or (not raw["reasons"]) != (raw["graduation_status"] == "ELIGIBLE"): raise DiscoveryGovernanceV2Error("graduation terminal state/reasons are inconsistent")
    return _json(raw, "graduation binding")


def build_candidate_freeze_v2(*, graduations: Sequence[Mapping[str, Any]], freeze_created_at_utc: str, freeze_policy_sha256: str) -> dict[str, Any]:
    """Freeze only embedded, self-verifying eligible v2 graduations; no registry input exists."""
    if not graduations: raise DiscoveryGovernanceV2Error("v2 freeze requires at least one eligible graduation")
    eligible, seen = [], set()
    for item in graduations:
        graduation = verify_graduation_binding_v2(item)
        if graduation["graduation_status"] != "ELIGIBLE" or graduation["terminal_state"] != "REPLICATION_PENDING": raise DiscoveryGovernanceV2Error("v2 freeze rejects missing/failed/non-pending graduation")
        key = _candidate_key(graduation["candidate_identity"])
        if key in seen: raise DiscoveryGovernanceV2Error("v2 freeze contains duplicate candidate graduation")
        seen.add(key); eligible.append(graduation)
    eligible.sort(key=lambda item: _candidate_key(item["candidate_identity"]))
    unsigned = {"schema": FREEZE_SCHEMA, "analysis": "v2_candidate_freeze_from_eligible_graduations_only", "freeze_created_at_utc": _utc(freeze_created_at_utc, "freeze created time"), "freeze_policy_sha256": _sha(freeze_policy_sha256, "freeze policy"), "graduations": eligible, "claims": {"candidate_specification_frozen": True, "verified_out_of_sample_evidence": False, "profitable_edge_established": False, "promotion_authorized": False, "live_order_transmission_supported": False}, "non_authority_claims": non_authority_claims()}
    return _seal(unsigned, "freeze_sha256")


def verify_candidate_freeze_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _map(value, "v2 candidate freeze")
    needed = {"schema", "analysis", "freeze_created_at_utc", "freeze_policy_sha256", "graduations", "claims", "non_authority_claims", "freeze_sha256"}
    _keys(raw, needed, "v2 candidate freeze")
    if raw.get("schema") != FREEZE_SCHEMA or raw.get("analysis") != "v2_candidate_freeze_from_eligible_graduations_only": raise DiscoveryGovernanceV2Error("unsupported v2 candidate freeze")
    _verify_hash(raw, "freeze_sha256", "v2 candidate freeze")
    rebuilt = build_candidate_freeze_v2(graduations=raw.get("graduations"), freeze_created_at_utc=raw.get("freeze_created_at_utc"), freeze_policy_sha256=raw.get("freeze_policy_sha256"))
    if raw != rebuilt: raise DiscoveryGovernanceV2Error("v2 freeze has been altered or bypasses graduation")
    return rebuilt


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryGovernanceV2Error(f"cannot load JSON object: {path}") from exc
    return _map(value, path)


def _write_exclusive(path: str, value: Mapping[str, Any]) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline prospective discovery governance v2; no market data, storage service, or trading.")
    commands = parser.add_subparsers(dest="command", required=True)
    append = commands.add_parser("append-ledger", help="append one pre-inspection ledger event to a new JSON path")
    append.add_argument("ledger"); append.add_argument("event"); append.add_argument("--output", required=True)
    close = commands.add_parser("close-family", help="close an exact immutable ledger snapshot")
    close.add_argument("ledger"); close.add_argument("selected_candidate"); close.add_argument("--selection-rule-sha256", required=True); close.add_argument("--closure-policy-sha256", required=True); close.add_argument("--output", required=True)
    economics = commands.add_parser("economics", help="evaluate v2 measured-friction eligibility")
    economics.add_argument("input", help="JSON object containing kwargs for build_economics_eligibility_v2"); economics.add_argument("--output"); economics.add_argument("--require-clear", action="store_true", help="return 3 when economics is ineligible")
    graduate = commands.add_parser("graduate", help="make a fail-closed v2 discovery graduation")
    graduate.add_argument("input", help="JSON object containing kwargs for build_graduation_binding_v2"); graduate.add_argument("--output"); graduate.add_argument("--require-eligible", action="store_true")
    freeze = commands.add_parser("freeze", help="freeze eligible embedded graduation artifacts only")
    freeze.add_argument("input", help="JSON object containing kwargs for build_candidate_freeze_v2"); freeze.add_argument("--output", required=True)
    validate = commands.add_parser("validate", help="validate one named v2 artifact")
    validate.add_argument("kind", choices=["ledger", "closure", "economics", "matrix", "inference", "benchmark", "evaluation", "graduation", "freeze"]); validate.add_argument("input")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "append-ledger": result = append_family_ledger_event_v2(_load(args.ledger), _load(args.event)); _write_exclusive(args.output, result)
        elif args.command == "close-family": result = close_family_v2(_load(args.ledger), selected_candidate_identity=_load(args.selected_candidate), selection_rule_sha256=args.selection_rule_sha256, closure_policy_sha256=args.closure_policy_sha256); _write_exclusive(args.output, result)
        elif args.command == "economics":
            result = build_economics_eligibility_v2(**_load(args.input));
            if args.output: _write_exclusive(args.output, result)
            print(json.dumps(result, sort_keys=True)); return 3 if args.require_clear and not result["economics_eligible"] else 0
        elif args.command == "graduate":
            result = build_graduation_binding_v2(**_load(args.input));
            if args.output: _write_exclusive(args.output, result)
            print(json.dumps(result, sort_keys=True)); return 3 if args.require_eligible and result["graduation_status"] != "ELIGIBLE" else 0
        elif args.command == "freeze": result = build_candidate_freeze_v2(**_load(args.input)); _write_exclusive(args.output, result)
        else:
            validators = {"ledger": verify_family_ledger_v2, "closure": verify_family_closure_v2, "economics": verify_economics_eligibility_v2, "matrix": verify_cluster_matrix_v2, "inference": verify_cluster_inference_v2, "benchmark": verify_benchmark_assessment_v2, "evaluation": verify_evaluation_binding_v2, "graduation": verify_graduation_binding_v2, "freeze": verify_candidate_freeze_v2}; result = validators[args.kind](_load(args.input))
        print(json.dumps(result, sort_keys=True)); return 0
    except (DiscoveryGovernanceV2Error, ContractValidationError, OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "error_type": type(exc).__name__, "reason": str(exc)}, sort_keys=True), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())

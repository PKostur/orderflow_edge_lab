"""Fail-closed roadmap readiness reporting for an eventual autonomous bot.

This module is deliberately *not* a trading engine.  It only normalizes and
hashes caller-provided, local provenance objects and reports whether the
objects cover staged engineering checks.  It never contacts a venue, holds
credentials, constructs an order, schedules work, or grants a promotion or
live-trading authority.

A local ``PASS`` means only that hash-bound caller-supplied evidence declares
and structurally supports a check.  It is not independent verification and is
never evidence that an edge exists.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


UTC = timezone.utc
INPUT_SCHEMA = "orderflow_edge_lab.bot_readiness_input.v3"
SOURCE_SCHEMA = "orderflow_edge_lab.bot_readiness_source_provenance.v3"
REPORT_SCHEMA = "orderflow_edge_lab.bot_readiness_report.v3"

STAGES = (
    "S0_RESEARCH",
    "S1_FINITE_AUTONOMOUS_PAPER_REPLAY",
    "S2_USER_OPERATED_READ_ONLY",
    "S3_INDEPENDENT_REVIEW",
)
_STAGE_ORDER = {stage: index for index, stage in enumerate(STAGES)}
_SOURCE_TYPES = frozenset(
    {
        "research_record",
        "qualified_data",
        "paper_replay",
        "operations_evidence",
        "read_only_recording",
        "independent_review",
        "design_review",
    }
)
_EVIDENCE_STATES = frozenset({"PASS", "FAIL", "UNKNOWN"})
_HEX = frozenset("0123456789abcdef")

# These are intentionally all false even where a caller presents a locally
# self-consistent evidence bundle.  A report must not become an authority
# escalation mechanism through a caller-controlled boolean.
NON_AUTHORITY_CLAIMS = {
    "actual_live_capability": False,
    "live_order_transmission_supported": False,
    "profitable_edge_established": False,
    "promotion_authorized": False,
    "strategy_promotion_authorized": False,
    "verified_out_of_sample_evidence": False,
}

CHECK_CATALOG: dict[str, str] = {
    "research_governance": "Frozen protocol and trial-ledger controls are evidenced.",
    "versioned_causal_rules": "Rules are executable, versioned, and causal rather than continuously retuned.",
    "candidate_freeze_before_new_evidence": "Candidate/protocol freeze predates the evidence it will evaluate.",
    "point_in_time_qualified_data": "Data has a declared point-in-time qualification.",
    "benchmark_and_no_trade_controls": "Benchmark and no-trade controls are retained beside the strategy arm.",
    "nonzero_friction_and_venue_conventions": "Non-zero round-trip friction and a venue funding convention are explicit.",
    "purged_chronological_regime_cross_validation": "Chronological, purged, regime-aware cross-validation is declared.",
    "portfolio_limits_and_loss_budget": "Portfolio limits and a positive, actionable loss budget are declared.",
    "finite_autonomous_paper_replay": "A bounded simulated replay has no human action per simulated decision and no order routing.",
    "restart_replay_exactly_once": "Restart/replay and exactly-once recovery have been rehearsed.",
    "unattended_fault_controls": "Finite replay fault controls reject stale data, fail closed, halt to a loss budget, and escalate.",
    "detached_storage_recovery_clock": "Detached storage, recovery rehearsal, and clock synchronization are evidenced.",
    "user_operated_read_only_analysis": "Market analysis remains user-operated and read-only with no order-submission capability.",
    "qualified_recording": "Read-only recording has an explicit point-in-time qualification.",
    "independent_promotion_review": "An independent review record exists; it is not promotion authority.",
    "operational_risk_security_review": "Independent operational, risk, and security review records exist.",
    "broker_integration_conformance_design": "Broker/venue integration is a design/conformance prerequisite only, never a transmitter.",
}

_STAGE_CHECKS: dict[str, tuple[str, ...]] = {
    "S0_RESEARCH": (
        "research_governance",
        "versioned_causal_rules",
        "candidate_freeze_before_new_evidence",
        "point_in_time_qualified_data",
        "benchmark_and_no_trade_controls",
        "nonzero_friction_and_venue_conventions",
        "purged_chronological_regime_cross_validation",
        "portfolio_limits_and_loss_budget",
    ),
    "S1_FINITE_AUTONOMOUS_PAPER_REPLAY": (
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
    ),
    "S2_USER_OPERATED_READ_ONLY": (
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
    ),
    "S3_INDEPENDENT_REVIEW": tuple(CHECK_CATALOG),
}

# These are repository facts, not calculated strategy verdicts.  They retain
# the important distinction between an implementation review and evidence that
# could support a research claim.  They intentionally do not mutate any frozen
# study and cannot be cleared by caller-provided booleans.
CURRENT_REPOSITORY_BLOCKERS = (
    {
        "id": "edge_not_established",
        "detail": "STATUS.md declares profitable_edge_established=false and verified_out_of_sample_evidence=false; no promoted strategy exists.",
    },
    {
        "id": "live_boundary_closed",
        "detail": "Automatic live broker/exchange order transmission remains disabled; this module supplies no transmission path.",
    },
    {
        "id": "prospective_reviews_not_verdicts_here",
        "detail": "DON8 and W3 can be reviewed only by their frozen workflows after their own gates. This reporter never emits a DON8 or W3 verdict.",
    },
    {
        "id": "terminal_lanes_not_rescuable",
        "detail": "W1 and W2 are terminally falsified; D4 did not replicate directionally. No retune, reversed-sign, or other rescue is permitted under those IDs.",
    },
    {
        "id": "forward_operations_prerequisites_open",
        "detail": "V2 handoff records missing external immutable-copy configuration, retrieval/recovery rehearsal, producer checkpoint adoption, and qualified producer health evidence; stale heartbeat was an observed operational blocker.",
    },
    {
        "id": "paper_is_not_edge_proof",
        "detail": "Existing paper execution is approval-bound. Finite autonomous paper replay engineering must remain separate from statistical edge establishment.",
    },
)

# Calendar entries are informational only.  Their different dates make clear
# that a generated assessment clock is not a blanket October 23 decision date.
WATCH_CALENDAR = (
    {
        "watch_id": "evidence_v2_cross_strategy_session_forward_v1",
        "label": "DON8",
        "earliest_review_utc": "2026-10-23T00:00:00Z",
        "rule": "Frozen workflow only; v3 emits no verdict.",
    },
    {
        "watch_id": "SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST",
        "label": "W3",
        "earliest_review_utc": None,
        "rule": "Data-volume gate and frozen workflow only; v3 emits no verdict.",
    },
    {
        "watch_id": "crypto-trend-core-v1",
        "label": "Long-horizon forward watch",
        "earliest_review_utc": "2027-03-28T00:00:00Z",
        "rule": "Forward collector status is not an edge verdict.",
    },
    {
        "watch_id": "paper-account-blend-v1",
        "label": "Paper account forward watch",
        "earliest_review_utc": "2027-04-03T00:00:00Z",
        "rule": "Paper account observation is not live authority.",
    },
)


class BotReadinessV3Error(ValueError):
    """Raised when an input, provenance object, or self-hash is invalid."""


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise BotReadinessV3Error(f"{field} must be an object with string keys")
    return value


def _require_exact_keys(raw: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(raw)
    if actual != expected:
        parts: list[str] = []
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            parts.append("missing=" + ",".join(missing))
        if extra:
            parts.append("extra=" + ",".join(extra))
        raise BotReadinessV3Error(f"{field} has unsupported shape ({'; '.join(parts)})")


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BotReadinessV3Error(f"{field} must be a nonempty string")
    return value.strip()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX for char in value.lower()):
        raise BotReadinessV3Error(f"{field} must be a 64-character lowercase-or-uppercase hexadecimal SHA-256")
    return value.lower()


def _validate_json(value: object, field: str = "value") -> None:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BotReadinessV3Error(f"{field} contains a nonfinite float")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{field}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BotReadinessV3Error(f"{field} has a non-string key")
            _validate_json(item, f"{field}.{key}")
        return
    raise BotReadinessV3Error(f"{field} is not a JSON value")


def canonical_json_bytes_v3(value: object) -> bytes:
    """Return strict canonical JSON bytes suitable for a local self-hash."""

    _validate_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_json_sha256_v3(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes_v3(value)).hexdigest()


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BotReadinessV3Error(f"{field} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise BotReadinessV3Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BotReadinessV3Error(f"{field} must include an explicit timezone")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_copy(value: object, field: str) -> Any:
    _validate_json(value, field)
    return json.loads(canonical_json_bytes_v3(value).decode("utf-8"))


def _normalise_evidence(value: object) -> dict[str, str]:
    raw = _require_mapping(value, "source.evidence")
    normalized: dict[str, str] = {}
    for check, status in raw.items():
        check_id = _require_string(check, "source.evidence key")
        if not isinstance(status, str) or status not in _EVIDENCE_STATES:
            raise BotReadinessV3Error(f"source.evidence.{check_id} must be PASS, FAIL, or UNKNOWN")
        normalized[check_id] = status
    return dict(sorted(normalized.items()))


def build_source_provenance_v3(
    *,
    source_id: str,
    source_type: str,
    observed_at_utc: str | datetime,
    evidence: Mapping[str, str],
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a self-hashed, caller-declared provenance object.

    This binds the identity, observation time, check assertions, and supporting
    facts together.  It proves only internal local consistency of that object;
    it does not prove source authenticity, storage durability, statistical edge,
    promotion, or any trading permission.
    """

    type_value = _require_string(source_type, "source_type")
    if type_value not in _SOURCE_TYPES:
        raise BotReadinessV3Error("source_type is unsupported")
    observed = _format_utc(_parse_utc(observed_at_utc.isoformat() if isinstance(observed_at_utc, datetime) else observed_at_utc, "observed_at_utc"))
    unsigned = {
        "schema": SOURCE_SCHEMA,
        "source_id": _require_string(source_id, "source_id"),
        "source_type": type_value,
        "observed_at_utc": observed,
        "evidence": _normalise_evidence(evidence),
        "facts": _json_copy(dict(_require_mapping(facts, "facts")), "facts"),
    }
    return {**unsigned, "source_sha256": canonical_json_sha256_v3(unsigned)}


def validate_source_provenance_v3(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a source object's exact schema and hash without contacting it."""

    raw = _require_mapping(value, "source_provenance")
    _require_exact_keys(
        raw,
        {"schema", "source_id", "source_type", "observed_at_utc", "evidence", "facts", "source_sha256"},
        "source_provenance",
    )
    if raw.get("schema") != SOURCE_SCHEMA:
        raise BotReadinessV3Error("source_provenance schema is unsupported")
    rebuilt = build_source_provenance_v3(
        source_id=raw.get("source_id"),
        source_type=raw.get("source_type"),
        observed_at_utc=raw.get("observed_at_utc"),
        evidence=raw.get("evidence"),
        facts=raw.get("facts"),
    )
    actual_hash = _require_sha256(raw.get("source_sha256"), "source_provenance.source_sha256")
    if actual_hash != rebuilt["source_sha256"]:
        raise BotReadinessV3Error("source_provenance.source_sha256 does not match the canonical object")
    return rebuilt


def _is_positive_number(value: object) -> bool:
    return type(value) in {int, float} and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0


def _nonempty_mapping(value: object) -> bool:
    return isinstance(value, Mapping) and bool(value)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping_true(value: object, *keys: str) -> bool:
    return isinstance(value, Mapping) and all(value.get(key) is True for key in keys)


def _finite_replay_facts(facts: Mapping[str, Any]) -> bool:
    replay = facts.get("finite_replay")
    if not _mapping_true(replay, "no_order_routing", "simulated_decisions_no_human"):
        return False
    try:
        return _parse_utc(replay.get("bounded_start_utc"), "finite_replay.bounded_start_utc") < _parse_utc(
            replay.get("bounded_end_utc"), "finite_replay.bounded_end_utc"
        )
    except BotReadinessV3Error:
        return False


def _supports_check(check_id: str, facts: Mapping[str, Any]) -> bool:
    """Require structured facts in addition to a source's hash-bound PASS assertion."""

    if check_id == "research_governance":
        return _mapping_true(facts.get("research_governance"), "frozen_protocol", "trial_ledger_bound")
    if check_id == "versioned_causal_rules":
        return _nonempty_string(facts.get("causal_rules_version")) and facts.get("causal_rules_executable") is True
    if check_id == "candidate_freeze_before_new_evidence":
        return facts.get("candidate_frozen_before_new_evidence") is True
    if check_id == "point_in_time_qualified_data":
        return facts.get("point_in_time_qualified") is True
    if check_id == "benchmark_and_no_trade_controls":
        return facts.get("benchmark_control_declared") is True and facts.get("no_trade_control_declared") is True
    if check_id == "nonzero_friction_and_venue_conventions":
        convention = facts.get("venue_cost_funding_convention")
        return (
            isinstance(convention, Mapping)
            and _is_positive_number(convention.get("round_trip_cost_bps"))
            and _nonempty_string(convention.get("funding_convention"))
        )
    if check_id == "purged_chronological_regime_cross_validation":
        return _mapping_true(
            facts.get("cross_validation"), "chronological", "purged", "regime_aware", "outcome_separated"
        )
    if check_id == "portfolio_limits_and_loss_budget":
        budget = facts.get("loss_budget")
        return (
            _nonempty_mapping(facts.get("portfolio_limits"))
            and isinstance(budget, Mapping)
            and _is_positive_number(budget.get("amount"))
            and _nonempty_string(budget.get("currency"))
            and _nonempty_string(budget.get("breach_action"))
        )
    if check_id == "finite_autonomous_paper_replay":
        return _finite_replay_facts(facts)
    if check_id == "restart_replay_exactly_once":
        return _mapping_true(facts.get("restart_replay"), "exactly_once_verified", "recovery_rehearsed")
    if check_id == "unattended_fault_controls":
        return _mapping_true(
            facts.get("unattended_fault_controls"),
            "fail_closed",
            "stale_source_reject",
            "loss_budget_halt",
            "human_alert_escalation",
        )
    if check_id == "detached_storage_recovery_clock":
        return _mapping_true(
            facts.get("detached_storage"), "detached_copy_verified", "recovery_rehearsed", "clock_synchronized"
        )
    if check_id == "user_operated_read_only_analysis":
        return facts.get("user_operated_read_only") is True and facts.get("order_submission_capability") is False
    if check_id == "qualified_recording":
        return facts.get("qualified_recording") is True and facts.get("recording_point_in_time_verified") is True
    if check_id == "independent_promotion_review":
        return _mapping_true(facts.get("independent_review"), "review_completed", "reviewer_independent")
    if check_id == "operational_risk_security_review":
        return _mapping_true(
            facts.get("operational_risk_security_review"), "operations_reviewed", "risk_reviewed", "security_reviewed"
        )
    if check_id == "broker_integration_conformance_design":
        design = facts.get("broker_integration_conformance_design")
        return (
            isinstance(design, Mapping)
            and design.get("design_only") is True
            and design.get("executable_transmission") is False
            and design.get("transaction_payloads_present") is False
        )
    # Unknown checks never receive a pass merely because a caller supplied one.
    return False


def _source_freshness(source: Mapping[str, Any], as_of: datetime, max_age_seconds: int) -> tuple[bool, str | None]:
    observed = _parse_utc(source["observed_at_utc"], "source.observed_at_utc")
    if observed > as_of:
        return False, "source_timestamp_is_in_the_future"
    age = (as_of - observed).total_seconds()
    if age > max_age_seconds:
        return False, "source_stale"
    return True, None


def _source_set_sha256(sources: Sequence[Mapping[str, Any]]) -> str:
    identities = [{"source_id": item["source_id"], "source_sha256": item["source_sha256"]} for item in sources]
    return canonical_json_sha256_v3(sorted(identities, key=lambda item: item["source_id"]))


def _normalise_required_checks(value: Iterable[str]) -> list[str]:
    if isinstance(value, (str, bytes)):
        raise BotReadinessV3Error("required_checks must be a nonempty list of check IDs")
    try:
        raw = list(value)
    except TypeError as exc:
        raise BotReadinessV3Error("required_checks must be iterable") from exc
    if not raw:
        raise BotReadinessV3Error("required_checks must be caller-prespecified and nonempty")
    normalized = [_require_string(item, "required_checks item") for item in raw]
    if len(normalized) != len(set(normalized)):
        raise BotReadinessV3Error("required_checks must not contain duplicates")
    return sorted(normalized)


def _normalise_sources(value: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)):
        raise BotReadinessV3Error("source_provenance must be an array of objects")
    try:
        normalized = [validate_source_provenance_v3(item) for item in value]
    except TypeError as exc:
        raise BotReadinessV3Error("source_provenance must be iterable") from exc
    normalized.sort(key=lambda item: item["source_id"])
    identifiers = [item["source_id"] for item in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise BotReadinessV3Error("source_provenance source_id values must be unique")
    return normalized


def _check_state(
    check_id: str,
    sources: Sequence[Mapping[str, Any]],
    as_of: datetime,
    max_age_seconds: int,
) -> dict[str, Any]:
    if check_id not in CHECK_CATALOG:
        return {
            "check_id": check_id,
            "status": "UNKNOWN",
            "detail": "Unknown caller-required check fails closed; add a versioned implementation before it can pass.",
            "source_ids": [],
        }

    candidates = [source for source in sources if check_id in source["evidence"]]
    if not candidates:
        return {
            "check_id": check_id,
            "status": "MISSING",
            "detail": "No hash-valid source asserted this required check.",
            "source_ids": [],
        }

    fresh_support: list[str] = []
    stale_support: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []
    malformed_facts: list[str] = []
    for source in candidates:
        source_id = source["source_id"]
        assertion = source["evidence"][check_id]
        fresh, _ = _source_freshness(source, as_of, max_age_seconds)
        if assertion == "FAIL":
            failed.append(source_id)
            continue
        if assertion == "UNKNOWN":
            unknown.append(source_id)
            continue
        if not _supports_check(check_id, source["facts"]):
            malformed_facts.append(source_id)
            continue
        if fresh:
            fresh_support.append(source_id)
        else:
            stale_support.append(source_id)

    if fresh_support:
        return {
            "check_id": check_id,
            "status": "PASS",
            "detail": "Fresh, hash-valid caller-declared source assertion includes the required structured facts; local consistency only.",
            "source_ids": sorted(fresh_support),
        }
    if stale_support:
        return {
            "check_id": check_id,
            "status": "STALE",
            "detail": "Only stale or future-dated source evidence supports this check; stale evidence fails closed.",
            "source_ids": sorted(stale_support),
        }
    if failed:
        return {
            "check_id": check_id,
            "status": "FAIL",
            "detail": "A hash-valid source explicitly records this check as failed.",
            "source_ids": sorted(failed),
        }
    if malformed_facts:
        return {
            "check_id": check_id,
            "status": "FAIL",
            "detail": "A PASS assertion lacks the structured fact(s) required for this check.",
            "source_ids": sorted(malformed_facts),
        }
    return {
        "check_id": check_id,
        "status": "UNKNOWN",
        "detail": "Only UNKNOWN source assertions exist; unknown fails closed.",
        "source_ids": sorted(unknown),
    }


def _stage_state(target_stage: str, check_states: Sequence[Mapping[str, Any]]) -> str:
    all_pass = all(item["status"] == "PASS" for item in check_states)
    if target_stage == "S0_RESEARCH":
        return "RESEARCH_ONLY" if all_pass else "RESEARCH_CONTROLS_INCOMPLETE"
    if target_stage == "S1_FINITE_AUTONOMOUS_PAPER_REPLAY":
        return "PAPER_ENGINEERING_READY_LOCAL_ONLY" if all_pass else "PAPER_ENGINEERING_BLOCKED"
    if target_stage == "S2_USER_OPERATED_READ_ONLY":
        return "READ_ONLY_WORKFLOW_READY_LOCAL_ONLY" if all_pass else "READ_ONLY_WORKFLOW_BLOCKED"
    # S3 can record complete review inputs, but independent review artifacts are
    # still not a strategy-promotion decision and never open live capability.
    return "REVIEW_RECORDS_COMPLETE_NO_AUTHORITY" if all_pass else "INDEPENDENT_REVIEW_REQUIRED"


def _next_steps(target_stage: str, check_states: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    missing = [item["check_id"] for item in check_states if item["status"] != "PASS"]
    steps: list[dict[str, str]] = []
    if missing:
        steps.append(
            {
                "id": "close_declared_gaps",
                "action": "Produce fresh, hash-bound provenance for the listed checks; do not replace UNKNOWN with a caller boolean.",
                "checks": ",".join(missing),
            }
        )
    if _STAGE_ORDER[target_stage] <= _STAGE_ORDER["S0_RESEARCH"]:
        steps.append(
            {
                "id": "freeze_before_new_evidence",
                "action": "Version executable causal rules before new evidence; preserve benchmark/no-trade controls, non-zero friction, portfolio limits, and purged chronological regime cross-validation.",
                "checks": "research-only",
            }
        )
    if _STAGE_ORDER[target_stage] <= _STAGE_ORDER["S1_FINITE_AUTONOMOUS_PAPER_REPLAY"]:
        steps.append(
            {
                "id": "bounded_replay_not_service",
                "action": "Test a finite offline simulated replay with restart/replay exactly-once, stale-source rejection, loss-budget halt, detached recovery, and clock checks. Do not create a scheduler, daemon, order router, or credentials path.",
                "checks": "paper-engineering-only",
            }
        )
    if _STAGE_ORDER[target_stage] <= _STAGE_ORDER["S2_USER_OPERATED_READ_ONLY"]:
        steps.append(
            {
                "id": "read_only_recording",
                "action": "Keep market analysis user-operated and read-only; qualify recordings point-in-time before they are used as research inputs.",
                "checks": "no-order-submission",
            }
        )
    steps.append(
        {
            "id": "separate_live_program",
            "action": "If independent reviews ever support a future live-platform proposal, the user must control separate engineering outside this skill. This repository and report still provide no executable transmission.",
            "checks": "live-boundary-remains-closed",
        }
    )
    return steps


def build_bot_readiness_report_v3(
    source_provenance: Iterable[Mapping[str, Any]],
    *,
    target_stage: str,
    required_checks: Iterable[str],
    assessment_id: str,
    as_of_utc: str | datetime,
    max_source_age_seconds: int,
) -> dict[str, Any]:
    """Build a deterministic, fail-closed readiness report.

    ``required_checks`` is caller-prespecified and is merged with the stage's
    immutable baseline.  An unknown caller check remains ``UNKNOWN``; callers
    cannot use a boolean to remove a baseline, promote a strategy, or open live
    capability.
    """

    target = _require_string(target_stage, "target_stage")
    if target not in STAGES:
        raise BotReadinessV3Error("target_stage is unsupported")
    if type(max_source_age_seconds) is not int or max_source_age_seconds < 0:
        raise BotReadinessV3Error("max_source_age_seconds must be a nonnegative integer")
    as_of_input = as_of_utc.isoformat() if isinstance(as_of_utc, datetime) else as_of_utc
    as_of = _parse_utc(as_of_input, "as_of_utc")
    caller_checks = _normalise_required_checks(required_checks)
    sources = _normalise_sources(source_provenance)
    all_checks = sorted(set(_STAGE_CHECKS[target]) | set(caller_checks))
    states = [_check_state(check, sources, as_of, max_source_age_seconds) for check in all_checks]
    gaps = [
        f"{item['check_id']}:{item['status'].lower()}"
        for item in states
        if item["status"] != "PASS"
    ]
    ignored_unknown_evidence = sorted(
        {
            check
            for source in sources
            for check in source["evidence"]
            if check not in CHECK_CATALOG
        }
    )
    gaps.extend(f"source_evidence_unknown_check:{check}" for check in ignored_unknown_evidence)
    input_unsigned = {
        "schema": INPUT_SCHEMA,
        "assessment_id": _require_string(assessment_id, "assessment_id"),
        "target_stage": target,
        "as_of_utc": _format_utc(as_of),
        "max_source_age_seconds": max_source_age_seconds,
        "required_checks": caller_checks,
        "source_provenance": sources,
    }
    unsigned = {
        "schema": REPORT_SCHEMA,
        "assessment_id": input_unsigned["assessment_id"],
        "target_stage": target,
        "as_of_utc": input_unsigned["as_of_utc"],
        "max_source_age_seconds": max_source_age_seconds,
        "caller_required_checks": caller_checks,
        "required_checks": all_checks,
        "sources": sources,
        "source_set_sha256": _source_set_sha256(sources),
        "assessment_input_sha256": canonical_json_sha256_v3(input_unsigned),
        "stage_state": _stage_state(target, states),
        "check_states": states,
        "gaps": sorted(gaps),
        "next_steps": _next_steps(target, states),
        "current_repository_blockers": list(CURRENT_REPOSITORY_BLOCKERS),
        "watch_calendar": list(WATCH_CALENDAR),
        "watch_verdicts": {
            "DON8": "NOT_ISSUED_BY_V3",
            "W1": "TERMINAL_FALSIFIED_NO_RESCUE",
            "W2": "TERMINAL_FALSIFIED_NO_RESCUE",
            "W3": "NOT_ISSUED_BY_V3",
            "D4": "NOT_REPLICATED_NO_REVERSED_SIGN_RESCUE",
        },
        "non_authority_claims": dict(NON_AUTHORITY_CLAIMS),
        "actual_live_capability": False,
        "live_order_transmission_supported": False,
        "strategy_promotion_authorized": False,
        "profitable_edge_established": False,
        "verified_out_of_sample_evidence": False,
    }
    return {**unsigned, "report_sha256": canonical_json_sha256_v3(unsigned)}


# Short aliases make this domain-specific API discoverable while keeping one
# implementation.  Neither alias accepts a live/promotion boolean.
assess_bot_readiness_v3 = build_bot_readiness_report_v3
assess_readiness_v3 = build_bot_readiness_report_v3


def validate_bot_readiness_report_v3(value: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild and compare a v3 report, including all non-authority invariants."""

    raw = _require_mapping(value, "bot_readiness_report")
    expected_keys = {
        "schema",
        "assessment_id",
        "target_stage",
        "as_of_utc",
        "max_source_age_seconds",
        "caller_required_checks",
        "required_checks",
        "sources",
        "source_set_sha256",
        "assessment_input_sha256",
        "stage_state",
        "check_states",
        "gaps",
        "next_steps",
        "current_repository_blockers",
        "watch_calendar",
        "watch_verdicts",
        "non_authority_claims",
        "actual_live_capability",
        "live_order_transmission_supported",
        "strategy_promotion_authorized",
        "profitable_edge_established",
        "verified_out_of_sample_evidence",
        "report_sha256",
    }
    _require_exact_keys(raw, expected_keys, "bot_readiness_report")
    if raw.get("schema") != REPORT_SCHEMA:
        raise BotReadinessV3Error("bot_readiness_report schema is unsupported")
    if raw.get("non_authority_claims") != NON_AUTHORITY_CLAIMS:
        raise BotReadinessV3Error("non_authority_claims must be the exact all-false v3 claim set")
    for key in (
        "actual_live_capability",
        "live_order_transmission_supported",
        "strategy_promotion_authorized",
        "profitable_edge_established",
        "verified_out_of_sample_evidence",
    ):
        if raw.get(key) is not False:
            raise BotReadinessV3Error(f"{key} must remain false")
    if not isinstance(raw.get("caller_required_checks"), list) or not isinstance(raw.get("required_checks"), list):
        raise BotReadinessV3Error("caller_required_checks and required_checks must be arrays")
    supplied_hash = _require_sha256(raw.get("report_sha256"), "bot_readiness_report.report_sha256")
    supplied_unsigned = {key: raw[key] for key in expected_keys - {"report_sha256"}}
    if supplied_hash != canonical_json_sha256_v3(supplied_unsigned):
        raise BotReadinessV3Error("report_sha256 does not match the supplied canonical report")
    rebuilt = build_bot_readiness_report_v3(
        raw.get("sources"),
        target_stage=raw.get("target_stage"),
        required_checks=raw.get("caller_required_checks"),
        assessment_id=raw.get("assessment_id"),
        as_of_utc=raw.get("as_of_utc"),
        max_source_age_seconds=raw.get("max_source_age_seconds"),
    )
    if supplied_hash != rebuilt["report_sha256"]:
        raise BotReadinessV3Error("report_sha256 does not match the canonical report")
    if canonical_json_bytes_v3(raw) != canonical_json_bytes_v3(rebuilt):
        raise BotReadinessV3Error("report content does not match its deterministic v3 assessment")
    return rebuilt


def build_report_from_input_v3(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an input envelope and build its readiness report."""

    raw = _require_mapping(value, "bot_readiness_input")
    _require_exact_keys(
        raw,
        {
            "schema",
            "assessment_id",
            "target_stage",
            "as_of_utc",
            "max_source_age_seconds",
            "required_checks",
            "source_provenance",
        },
        "bot_readiness_input",
    )
    if raw.get("schema") != INPUT_SCHEMA:
        raise BotReadinessV3Error("bot_readiness_input schema is unsupported")
    return build_bot_readiness_report_v3(
        raw.get("source_provenance"),
        target_stage=raw.get("target_stage"),
        required_checks=raw.get("required_checks"),
        assessment_id=raw.get("assessment_id"),
        as_of_utc=raw.get("as_of_utc"),
        max_source_age_seconds=raw.get("max_source_age_seconds"),
    )


def write_bot_readiness_report_v3(report: Mapping[str, Any], path: str | Path) -> None:
    """Self-validate then atomically write a local JSON report; no external storage is used."""

    normalized = validate_bot_readiness_report_v3(report)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_bytes(canonical_json_bytes_v3(normalized) + b"\n")
    temporary.replace(target)


def _load_json_object(path: str | Path) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BotReadinessV3Error(f"cannot read JSON object from {path}") from exc
    return _require_mapping(value, f"JSON at {path}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run an offline JSON report CLI; it performs no market or order activity."""

    parser = argparse.ArgumentParser(
        description="Fail-closed, offline v3 readiness reporting. It cannot promote a strategy or transmit an order."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    assess = commands.add_parser("assess", help="build an all-non-authoritative readiness report from an input JSON object")
    assess.add_argument("--input", required=True, help="v3 readiness input JSON")
    assess.add_argument("--output", help="optional local JSON report path")
    validate = commands.add_parser("validate", help="self-validate a v3 report JSON object")
    validate.add_argument("--input", required=True, help="v3 readiness report JSON")
    source = commands.add_parser("build-source", help="self-hash an unsigned local source-provenance JSON object")
    source.add_argument("--input", required=True, help="JSON with source_id, source_type, observed_at_utc, evidence, and facts")

    args = parser.parse_args(argv)
    try:
        if args.command == "assess":
            report = build_report_from_input_v3(_load_json_object(args.input))
            if args.output:
                write_bot_readiness_report_v3(report, args.output)
            print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            return 0
        if args.command == "validate":
            report = validate_bot_readiness_report_v3(_load_json_object(args.input))
            print(json.dumps({"status": "VALID", "report_sha256": report["report_sha256"]}, sort_keys=True))
            return 0
        if args.command == "build-source":
            raw = _load_json_object(args.input)
            _require_exact_keys(raw, {"source_id", "source_type", "observed_at_utc", "evidence", "facts"}, "unsigned source")
            provenance = build_source_provenance_v3(**raw)
            print(json.dumps(provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            return 0
    except (BotReadinessV3Error, OSError, TypeError) as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

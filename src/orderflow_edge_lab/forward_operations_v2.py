"""Opt-in v2 forward-operations evidence-integrity overlays.

This module is deliberately operational and provenance-only.  It reads caller
supplied clock, report, source, workflow, and artifact facts; it never fetches
market data, modifies a frozen report, dispatches a workflow, counts a batch,
interprets PnL, makes a research verdict, or authorizes promotion/live orders.

The v2 objects make unavailable retention, source revisions, incomplete frozen
universes, and stale watch children explicit.  A local hash or a declared
storage requirement is *not* proof of durable external retention.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    ContractValidationError,
    build_canonical_source_set,
    build_coverage_result,
    build_manifest_result,
    build_source_record,
    canonical_json_bytes,
    canonical_json_sha256,
    missing_value,
    non_authority_claims,
    observed_value,
    validate_file_identity,
)

UTC = timezone.utc
RETENTION_SCHEMA = "orderflow_edge_lab.forward_retention_inventory.v2"
AVAILABILITY_SCHEMA = "orderflow_edge_lab.universe_availability_ledger.v2"
CHECKPOINT_SCHEMA = "orderflow_edge_lab.forward_source_checkpoint.v2"
REGISTRY_SCHEMA = "orderflow_edge_lab.forward_operations_registry.v2"
HEARTBEAT_SCHEMA = "orderflow_edge_lab.forward_operations_heartbeat.v2"
PRODUCER_CONTRACT_SCHEMA = "orderflow_edge_lab.forward_retention_producer_contract.v2"


class ForwardOperationsError(ValueError):
    """Raised when a v2 operational overlay is malformed or unsafe to interpret."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ForwardOperationsError(f"{field} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ForwardOperationsError(f"{field} keys must be strings")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ForwardOperationsError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ForwardOperationsError(f"{field} must be a nonempty string")
    return value.strip()


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        comparator = "nonnegative" if allow_zero else "positive"
        raise ForwardOperationsError(f"{field} must be a {comparator} integer")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ForwardOperationsError(f"{field} must be a SHA-256")
    lowered = value.lower()
    if any(char not in "0123456789abcdef" for char in lowered):
        raise ForwardOperationsError(f"{field} must be a SHA-256")
    return lowered


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ForwardOperationsError(f"{field} must be an ISO-8601 timestamp with an offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ForwardOperationsError(f"{field} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForwardOperationsError(f"{field} must carry a UTC offset")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _result(unsigned: Mapping[str, Any], hash_key: str) -> dict[str, Any]:
    copied = json.loads(canonical_json_bytes(dict(unsigned)).decode("utf-8"))
    return {**copied, hash_key: canonical_json_sha256(copied)}


def _validate_result_hash(value: Mapping[str, Any], hash_key: str, context: str) -> dict[str, Any]:
    raw = dict(_mapping(value, context))
    actual = _sha256(raw.pop(hash_key, None), f"{context}.{hash_key}")
    expected = canonical_json_sha256(raw)
    if actual != expected:
        raise ForwardOperationsError(f"{context}.{hash_key} does not match canonical content")
    return {**raw, hash_key: actual}


def _source_set(named_identities: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(named_identities, "source_identities")
    if not raw:
        raise ForwardOperationsError("source_identities must not be empty")
    records = []
    for source_id, identity in sorted(raw.items()):
        records.append(build_source_record(_string(source_id, "source identity id"), validate_file_identity(_mapping(identity, source_id))))
    try:
        return build_canonical_source_set(records)
    except ContractValidationError as exc:
        raise ForwardOperationsError(str(exc)) from exc


def _clock_watches(clock_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    clock = _mapping(clock_config, "clock_config")
    watches = _list(clock.get("watches"), "clock_config.watches")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(watches):
        watch = _mapping(value, f"clock_config.watches[{index}]")
        watch_id = _string(watch.get("watch_id"), f"clock_config.watches[{index}].watch_id")
        if watch_id in seen:
            raise ForwardOperationsError(f"clock_config has duplicate watch_id {watch_id!r}")
        seen.add(watch_id)
        start = _utc(watch.get("prospective_start_utc"), f"{watch_id}.prospective_start_utc")
        gate = _mapping(watch.get("review_gate"), f"{watch_id}.review_gate")
        minimum_days = gate.get("minimum_days")
        if type(minimum_days) is not int or minimum_days < 0:
            raise ForwardOperationsError(f"{watch_id}.review_gate.minimum_days must be a nonnegative integer")
        normalized.append(
            {
                "watch_id": watch_id,
                "prospective_start_utc": _format_utc(start),
                "terminal_state": watch.get("terminal_state"),
                "review_gate_type": _string(gate.get("type"), f"{watch_id}.review_gate.type"),
                "minimum_days": minimum_days,
                "forward_workflow": watch.get("forward_workflow"),
            }
        )
    return normalized


def _open_watches(clock_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [watch for watch in _clock_watches(clock_config) if watch["terminal_state"] is None]


def _copy_policy(value: object, context: str) -> dict[str, Any]:
    raw = _mapping(value, context)
    required = raw.get("required")
    if required is not True:
        raise ForwardOperationsError(f"{context}.required must be true; local retention cannot substitute for immutable copy")
    status = _string(raw.get("status"), f"{context}.status")
    if status not in {"BLOCKED_EXTERNAL", "UNVERIFIED_EXTERNAL"}:
        raise ForwardOperationsError(f"{context}.status must remain BLOCKED_EXTERNAL or UNVERIFIED_EXTERNAL")
    reference = raw.get("reference")
    if reference is not None and (not isinstance(reference, str) or not reference.strip()):
        raise ForwardOperationsError(f"{context}.reference must be null or a nonempty caller-provided reference")
    return {"required": True, "status": status, "reference": reference}


def _retention_artifact(value: object, context: str) -> dict[str, Any]:
    raw = _mapping(value, context)
    role = _string(raw.get("role"), f"{context}.role")
    if role not in {"REPORT", "SOURCE_CHECKPOINT", "HASH_MANIFEST"}:
        raise ForwardOperationsError(f"{context}.role is unsupported")
    return {
        "role": role,
        "artifact_name": _string(raw.get("artifact_name"), f"{context}.artifact_name"),
        "artifact_path": _string(raw.get("artifact_path"), f"{context}.artifact_path"),
        "producer_workflow": _string(raw.get("producer_workflow"), f"{context}.producer_workflow"),
        "requested_retention_days": _positive_int(raw.get("requested_retention_days"), f"{context}.requested_retention_days"),
        "external_immutable_copy": _copy_policy(raw.get("external_immutable_copy"), f"{context}.external_immutable_copy"),
    }


def build_retention_inventory_v2(
    clock_config: Mapping[str, Any],
    retention_overlay: Mapping[str, Any],
    *,
    source_identities: Mapping[str, Any],
    generated_at_utc: str,
) -> dict[str, Any]:
    """Derive a deterministic nonterminal retention inventory from frozen clock IDs.

    The overlay is a caller-declared operational template.  It must map every
    nonterminal watch to report, source-checkpoint, and hash-manifest artifacts.
    All durable-copy states deliberately remain blocked/unverified: a local
    source identity cannot establish external immutable storage.
    """

    moment = _utc(generated_at_utc, "generated_at_utc")
    watches = _open_watches(clock_config)
    overlay = _mapping(retention_overlay, "retention_overlay")
    entries = _list(overlay.get("watches"), "retention_overlay.watches")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, candidate in enumerate(entries):
        row = _mapping(candidate, f"retention_overlay.watches[{index}]")
        watch_id = _string(row.get("watch_id"), f"retention_overlay.watches[{index}].watch_id")
        if watch_id in by_id:
            raise ForwardOperationsError(f"retention_overlay has duplicate watch_id {watch_id!r}")
        by_id[watch_id] = row
    open_ids = {watch["watch_id"] for watch in watches}
    extras = sorted(set(by_id) - open_ids)
    missing = sorted(open_ids - set(by_id))
    if extras:
        raise ForwardOperationsError(f"retention_overlay maps terminal/unknown watches: {extras}")
    if missing:
        raise ForwardOperationsError(f"retention_overlay omits nonterminal watches: {missing}")

    records: list[dict[str, Any]] = []
    declaration_observations: list[dict[str, Any]] = []
    for watch in sorted(watches, key=lambda item: item["watch_id"]):
        row = by_id[watch["watch_id"]]
        margin = _positive_int(row.get("operational_margin_days"), f"{watch['watch_id']}.operational_margin_days", allow_zero=True)
        start = _utc(watch["prospective_start_utc"], f"{watch['watch_id']}.prospective_start_utc")
        earliest = start + timedelta(days=watch["minimum_days"])
        required_through = earliest + timedelta(days=margin)
        artifacts = [_retention_artifact(item, f"{watch['watch_id']}.artifacts[{index}]") for index, item in enumerate(_list(row.get("artifacts"), f"{watch['watch_id']}.artifacts"))]
        roles = {artifact["role"] for artifact in artifacts}
        required_roles = {"REPORT", "SOURCE_CHECKPOINT", "HASH_MANIFEST"}
        if not required_roles.issubset(roles):
            raise ForwardOperationsError(f"{watch['watch_id']} must declare REPORT, SOURCE_CHECKPOINT, and HASH_MANIFEST artifacts")
        signatures = [(artifact["role"], artifact["artifact_name"], artifact["artifact_path"]) for artifact in artifacts]
        if len(signatures) != len(set(signatures)):
            raise ForwardOperationsError(f"{watch['watch_id']} has duplicate retention artifact declarations")
        records.append(
            {
                "watch_id": watch["watch_id"],
                "prospective_start_utc": watch["prospective_start_utc"],
                "review_gate_type": watch["review_gate_type"],
                "earliest_possible_review_utc": _format_utc(earliest),
                "operational_margin_days": margin,
                "required_through_utc": _format_utc(required_through),
                "artifacts": sorted(artifacts, key=lambda item: (item["role"], item["artifact_name"], item["artifact_path"])),
                "retention_status": "EXTERNAL_IMMUTABLE_COPY_UNVERIFIED",
            }
        )
        declaration_observations.append({"observation_id": watch["watch_id"], "observation": observed_value(1)})

    earliest_start = min(_utc(watch["prospective_start_utc"], "prospective_start_utc") for watch in watches)
    latest_required = max(_utc(record["required_through_utc"], "required_through_utc") for record in records)
    from orderflow_edge_lab.contracts_v2 import CLOSED_OPEN, build_utc_interval

    coverage = build_coverage_result(
        "retention_declaration_per_nonterminal_watch",
        build_utc_interval(earliest_start, latest_required + timedelta(seconds=1), convention=CLOSED_OPEN),
        declaration_observations,
    )
    source_set = _source_set(source_identities)
    manifest = build_manifest_result(
        "forward_retention_inventory_v2",
        source_set,
        "DIAGNOSTIC_ONLY",
        coverage=coverage,
        attributes={"external_retention_activation_blocked": True, "open_watch_count": len(records)},
    )
    return _result(
        {
            "schema": RETENTION_SCHEMA,
            "analysis": "forward_retention_inventory_v2",
            "generated_at_utc": _format_utc(moment),
            "source_set": source_set,
            "coverage": coverage,
            "watches": records,
            "durable_retention_activation": "BLOCKED_EXTERNAL_IMMUTABLE_COPY_EVIDENCE_REQUIRED",
            "manifest_result": manifest,
            "non_authority_claims": non_authority_claims(),
        },
        "inventory_sha256",
    )


def _source_observation(value: object, context: str) -> dict[str, Any]:
    raw = _mapping(value, context)
    availability = _string(raw.get("availability"), f"{context}.availability")
    if availability == "OBSERVED":
        if raw.get("reason") is not None:
            raise ForwardOperationsError(f"{context}.reason must be null for an observed source")
        return {"availability": "OBSERVED", "source_identity": validate_file_identity(_mapping(raw.get("source_identity"), f"{context}.source_identity")), "reason": None}
    if availability == "MISSING":
        if raw.get("source_identity") is not None:
            raise ForwardOperationsError(f"{context}.source_identity must be null for a missing source")
        return {"availability": "MISSING", "source_identity": None, "reason": _string(raw.get("reason"), f"{context}.reason")}
    raise ForwardOperationsError(f"{context}.availability must be OBSERVED or MISSING")


def _symbol_row(value: object, context: str) -> dict[str, Any]:
    raw = _mapping(value, context)
    symbol = _string(raw.get("symbol"), f"{context}.symbol")
    warmup = raw.get("warmup_sufficient")
    if type(warmup) is not bool:
        raise ForwardOperationsError(f"{context}.warmup_sufficient must be boolean")
    error = raw.get("error_class")
    if error is not None and (not isinstance(error, str) or not error.strip()):
        raise ForwardOperationsError(f"{context}.error_class must be null or nonempty")
    first = raw.get("first_completed_boundary_utc")
    last = raw.get("last_completed_boundary_utc")
    if first is not None:
        first = _format_utc(_utc(first, f"{context}.first_completed_boundary_utc"))
    if last is not None:
        last = _format_utc(_utc(last, f"{context}.last_completed_boundary_utc"))
    if first is not None and last is not None and _utc(last, f"{context}.last_completed_boundary_utc") < _utc(first, f"{context}.first_completed_boundary_utc"):
        raise ForwardOperationsError(f"{context} last completed boundary precedes first")
    return {
        "symbol": symbol,
        "price": _source_observation(raw.get("price"), f"{context}.price"),
        "funding": _source_observation(raw.get("funding"), f"{context}.funding"),
        "first_completed_boundary_utc": first,
        "last_completed_boundary_utc": last,
        "warmup_sufficient": warmup,
        "error_class": error,
    }


def _previous_link(value: object, *, watch_id: str, context: str) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _mapping(value, context)
    if _string(raw.get("watch_id"), f"{context}.watch_id") != watch_id:
        raise ForwardOperationsError(f"{context}.watch_id must match {watch_id}")
    hash_value = raw.get("checkpoint_sha256", raw.get("ledger_sha256"))
    return {
        "checkpoint_id": _string(raw.get("checkpoint_id"), f"{context}.checkpoint_id"),
        "checkpoint_sha256": _sha256(hash_value, f"{context}.checkpoint_sha256 or ledger_sha256"),
    }


def build_universe_availability_ledger_v2(
    *,
    watch_id: str,
    checkpoint_id: str,
    observed_at_utc: str,
    interval: Mapping[str, Any],
    expected_symbols: Sequence[str],
    symbol_rows: Sequence[Mapping[str, Any]],
    universe_identity: Mapping[str, Any],
    previous_checkpoint: Mapping[str, Any] | None = None,
    report_identity: Mapping[str, Any] | None = None,
    policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Build an immutable, append-only overlay for a frozen symbol universe.

    Any missing price/funding source, insufficient warm-up, omitted row, or
    unknown source forces ``DATA_INCOMPLETE``.  It does not recalculate, delete,
    reweight, or overwrite the original report.
    """

    normalized_watch = _string(watch_id, "watch_id")
    normalized_checkpoint = _string(checkpoint_id, "checkpoint_id")
    observed = _format_utc(_utc(observed_at_utc, "observed_at_utc"))
    symbols = [_string(symbol, "expected_symbols item") for symbol in expected_symbols]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ForwardOperationsError("expected_symbols must be a nonempty unique sequence")
    normalized_rows = [_symbol_row(item, f"symbol_rows[{index}]") for index, item in enumerate(symbol_rows)]
    row_ids = [row["symbol"] for row in normalized_rows]
    if len(row_ids) != len(set(row_ids)):
        raise ForwardOperationsError("symbol_rows contains duplicate symbols")
    unexpected = sorted(set(row_ids) - set(symbols))
    if unexpected:
        raise ForwardOperationsError(f"symbol_rows includes symbols outside frozen universe: {unexpected}")
    by_symbol = {row["symbol"]: row for row in normalized_rows}

    normalized: list[dict[str, Any]] = []
    coverage_observations: list[dict[str, Any]] = []
    source_identities: dict[str, Any] = {"expected_universe": validate_file_identity(_mapping(universe_identity, "universe_identity"))}
    if report_identity is not None:
        source_identities["original_report"] = validate_file_identity(_mapping(report_identity, "report_identity"))
    complete_symbols = 0
    for symbol in sorted(symbols):
        row = by_symbol.get(symbol)
        if row is None:
            row = {
                "symbol": symbol,
                "price": {"availability": "MISSING", "source_identity": None, "reason": "symbol_row_absent"},
                "funding": {"availability": "MISSING", "source_identity": None, "reason": "symbol_row_absent"},
                "first_completed_boundary_utc": None,
                "last_completed_boundary_utc": None,
                "warmup_sufficient": False,
                "error_class": "symbol_row_absent",
            }
        for kind in ("price", "funding"):
            source = row[kind]
            if source["availability"] == "OBSERVED":
                source_identities[f"{kind}:{symbol}"] = source["source_identity"]
        row_complete = (
            row["price"]["availability"] == "OBSERVED"
            and row["funding"]["availability"] == "OBSERVED"
            and row["warmup_sufficient"]
            and row["first_completed_boundary_utc"] is not None
            and row["last_completed_boundary_utc"] is not None
        )
        if row_complete:
            complete_symbols += 1
            coverage_observations.append({"observation_id": symbol, "observation": observed_value(1)})
        else:
            reasons = []
            for kind in ("price", "funding"):
                if row[kind]["availability"] == "MISSING":
                    reasons.append(f"{kind}:{row[kind]['reason']}")
            if not row["warmup_sufficient"]:
                reasons.append("warmup_insufficient")
            if row["first_completed_boundary_utc"] is None or row["last_completed_boundary_utc"] is None:
                reasons.append("completed_boundary_unknown")
            coverage_observations.append({"observation_id": symbol, "observation": missing_value(";".join(reasons) or "availability_incomplete")})
        normalized.append(row)

    from orderflow_edge_lab.contracts_v2 import validate_utc_interval

    coverage = build_coverage_result("frozen_universe_symbol_availability", validate_utc_interval(interval), coverage_observations)
    fraction = complete_symbols / len(symbols)
    previous = _previous_link(previous_checkpoint, watch_id=normalized_watch, context="previous_checkpoint")
    source_set = _source_set(source_identities)
    outcome = "COMPLETE" if coverage["status"] == "COMPLETE" else "INCOMPLETE"
    manifest = build_manifest_result(
        "universe_availability_ledger_v2",
        source_set,
        outcome,
        coverage=coverage,
        policy_sha256=_sha256(policy_sha256, "policy_sha256") if policy_sha256 is not None else None,
        attributes={"coverage_status": "COMPLETE" if outcome == "COMPLETE" else "DATA_INCOMPLETE", "append_only": True},
    )
    return _result(
        {
            "schema": AVAILABILITY_SCHEMA,
            "analysis": "universe_availability_ledger_v2",
            "watch_id": normalized_watch,
            "checkpoint_id": normalized_checkpoint,
            "observed_at_utc": observed,
            "append_only": True,
            "previous_checkpoint": previous,
            "expected_symbols": sorted(symbols),
            "symbol_rows": normalized,
            "coverage": coverage,
            "coverage_fraction": fraction,
            "coverage_status": "COMPLETE" if outcome == "COMPLETE" else "DATA_INCOMPLETE",
            "source_set": source_set,
            "original_report_preserved": True,
            "manifest_result": manifest,
            "non_authority_claims": non_authority_claims(),
        },
        "ledger_sha256",
    )


def _checkpoint_source(value: object, context: str, expected_boundaries: set[str]) -> dict[str, Any]:
    raw = _mapping(value, context)
    source_id = _string(raw.get("source_id"), f"{context}.source_id")
    observed_boundaries = [_format_utc(_utc(item, f"{context}.observed_boundaries_utc")) for item in _list(raw.get("observed_boundaries_utc"), f"{context}.observed_boundaries_utc")]
    if len(observed_boundaries) != len(set(observed_boundaries)):
        raise ForwardOperationsError(f"{context}.observed_boundaries_utc has duplicates")
    if set(observed_boundaries) - expected_boundaries:
        raise ForwardOperationsError(f"{context}.observed_boundaries_utc contains a boundary outside expected grid")
    observation = _source_observation({"availability": raw.get("availability"), "source_identity": raw.get("source_identity"), "reason": raw.get("reason")}, context)
    return {
        "source_id": source_id,
        "symbol": _string(raw.get("symbol"), f"{context}.symbol"),
        "kind": _string(raw.get("kind"), f"{context}.kind"),
        "availability": observation["availability"],
        "source_identity": observation["source_identity"],
        "reason": observation["reason"],
        "observed_boundaries_utc": sorted(observed_boundaries),
    }


def build_source_checkpoint_v2(
    *,
    watch_id: str,
    checkpoint_id: str,
    fetched_at_utc: str,
    bar_seconds: int,
    expected_boundaries_utc: Sequence[str],
    sources: Sequence[Mapping[str, Any]],
    report_identity: Mapping[str, Any],
    config_identity: Mapping[str, Any],
    code_identity: Mapping[str, Any],
    previous_checkpoint: Mapping[str, Any] | None = None,
    policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Bind one append-only forward-source checkpoint to report/config/code bytes.

    A boundary is counted only when its full bar had closed at ``fetched_at_utc``.
    A changed source identity is retained as a revision link, never used to
    overwrite the predecessor or silently recompute the frozen report.
    """

    normalized_watch = _string(watch_id, "watch_id")
    normalized_checkpoint = _string(checkpoint_id, "checkpoint_id")
    fetched = _utc(fetched_at_utc, "fetched_at_utc")
    duration = timedelta(seconds=_positive_int(bar_seconds, "bar_seconds"))
    expected = [_format_utc(_utc(item, "expected_boundaries_utc item")) for item in expected_boundaries_utc]
    if not expected or expected != sorted(expected) or len(expected) != len(set(expected)):
        raise ForwardOperationsError("expected_boundaries_utc must be a nonempty, sorted, unique UTC sequence")
    expected_set = set(expected)
    closed = [item for item in expected if _utc(item, "expected boundary") + duration <= fetched]
    open_boundaries = [item for item in expected if item not in set(closed)]
    rows = [_checkpoint_source(item, f"sources[{index}]", expected_set) for index, item in enumerate(sources)]
    source_ids = [row["source_id"] for row in rows]
    if not rows or len(source_ids) != len(set(source_ids)):
        raise ForwardOperationsError("sources must be a nonempty sequence with unique source_id values")
    if rows != sorted(rows, key=lambda row: row["source_id"]):
        raise ForwardOperationsError("sources must be sorted by source_id for append-only deterministic checkpoints")
    for row in rows:
        invalid_open = set(row["observed_boundaries_utc"]) & set(open_boundaries)
        if invalid_open:
            raise ForwardOperationsError(f"{row['source_id']} claims still-open boundaries as observed: {sorted(invalid_open)}")

    previous_raw = previous_checkpoint
    previous = _previous_link(previous_raw, watch_id=normalized_watch, context="previous_checkpoint")
    previous_sources: dict[str, Mapping[str, Any]] = {}
    if previous_raw is not None:
        prior_sources = _list(_mapping(previous_raw, "previous_checkpoint").get("sources"), "previous_checkpoint.sources")
        for item in prior_sources:
            source = _mapping(item, "previous_checkpoint.source")
            source_id = _string(source.get("source_id"), "previous_checkpoint.source.source_id")
            previous_sources[source_id] = source

    coverage_observations: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    named_identities: dict[str, Any] = {
        "report": validate_file_identity(_mapping(report_identity, "report_identity")),
        "config": validate_file_identity(_mapping(config_identity, "config_identity")),
        "code": validate_file_identity(_mapping(code_identity, "code_identity")),
    }
    for row in rows:
        if row["availability"] == "OBSERVED":
            named_identities[f"source:{row['source_id']}"] = row["source_identity"]
        observed_set = set(row["observed_boundaries_utc"])
        for boundary in closed:
            observation_id = f"{row['source_id']}@{boundary}"
            if row["availability"] == "OBSERVED" and boundary in observed_set:
                coverage_observations.append({"observation_id": observation_id, "observation": observed_value(1)})
            else:
                reason = row["reason"] if row["availability"] == "MISSING" else "closed_boundary_missing"
                coverage_observations.append({"observation_id": observation_id, "observation": missing_value(reason)})
        prior = previous_sources.get(row["source_id"])
        if prior is not None and row["availability"] == "OBSERVED":
            prior_identity = prior.get("source_identity")
            if isinstance(prior_identity, Mapping):
                normalized_prior = validate_file_identity(prior_identity)
                if normalized_prior["sha256"] != row["source_identity"]["sha256"]:
                    revisions.append(
                        {
                            "source_id": row["source_id"],
                            "predecessor_source_sha256": normalized_prior["sha256"],
                            "revised_source_sha256": row["source_identity"]["sha256"],
                            "predecessor_checkpoint_sha256": previous["checkpoint_sha256"] if previous else None,
                        }
                    )

    coverage = None
    if closed:
        from orderflow_edge_lab.contracts_v2 import CLOSED_OPEN, build_utc_interval

        coverage = build_coverage_result(
            "closed_forward_bar_grid",
            build_utc_interval(_utc(closed[0], "closed boundary"), _utc(closed[-1], "closed boundary") + duration, convention=CLOSED_OPEN),
            coverage_observations,
        )
    if not closed:
        checkpoint_status = "OPEN_BAR_ONLY"
        outcome = "DIAGNOSTIC_ONLY"
    elif coverage is not None and coverage["status"] != "COMPLETE" and revisions:
        checkpoint_status = "DATA_GAP_AND_REVISED_SOURCE"
        outcome = "INCOMPLETE"
    elif coverage is not None and coverage["status"] != "COMPLETE":
        checkpoint_status = "DATA_GAP"
        outcome = "INCOMPLETE"
    elif revisions:
        checkpoint_status = "REVISED_SOURCE"
        outcome = "DIAGNOSTIC_ONLY"
    else:
        checkpoint_status = "COMPLETE"
        outcome = "COMPLETE"
    source_set = _source_set(named_identities)
    manifest = build_manifest_result(
        "forward_source_checkpoint_v2",
        source_set,
        outcome,
        coverage=coverage,
        policy_sha256=_sha256(policy_sha256, "policy_sha256") if policy_sha256 is not None else None,
        attributes={"checkpoint_status": checkpoint_status, "append_only": True, "original_report_preserved": True},
    )
    return _result(
        {
            "schema": CHECKPOINT_SCHEMA,
            "analysis": "forward_source_checkpoint_v2",
            "watch_id": normalized_watch,
            "checkpoint_id": normalized_checkpoint,
            "fetched_at_utc": _format_utc(fetched),
            "bar_seconds": int(bar_seconds),
            "expected_boundaries_utc": expected,
            "closed_boundaries_utc": closed,
            "open_boundaries_excluded_utc": open_boundaries,
            "sources": rows,
            "coverage": coverage,
            "checkpoint_status": checkpoint_status,
            "revision_links": revisions,
            "append_only": True,
            "previous_checkpoint": previous,
            "original_report_preserved": True,
            "source_set": source_set,
            "manifest_result": manifest,
            "non_authority_claims": non_authority_claims(),
        },
        "checkpoint_sha256",
    )


def locate_checkpoint_by_report_sha256_v2(checkpoints: Iterable[Mapping[str, Any]], report_sha256: str) -> list[dict[str, Any]]:
    """Locate retained checkpoint references for formal review without changing evidence."""

    target = _sha256(report_sha256, "report_sha256")
    matches: list[dict[str, Any]] = []
    for index, checkpoint in enumerate(checkpoints):
        raw = _mapping(checkpoint, f"checkpoints[{index}]")
        identity = _mapping(raw.get("source_set"), f"checkpoints[{index}].source_set")
        sources = _list(identity.get("sources"), f"checkpoints[{index}].source_set.sources")
        report = next((item for item in sources if isinstance(item, Mapping) and item.get("source_id") == "report"), None)
        if report is not None and _sha256(_mapping(report, "report").get("sha256"), "report.sha256") == target:
            matches.append(
                {
                    "watch_id": _string(raw.get("watch_id"), "checkpoint.watch_id"),
                    "checkpoint_id": _string(raw.get("checkpoint_id"), "checkpoint.checkpoint_id"),
                    "checkpoint_sha256": _sha256(raw.get("checkpoint_sha256"), "checkpoint.checkpoint_sha256"),
                    "checkpoint_status": _string(raw.get("checkpoint_status"), "checkpoint.checkpoint_status"),
                }
            )
    return sorted(matches, key=lambda item: (item["watch_id"], item["checkpoint_id"]))


def _registry_row(value: object, context: str, watch: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, context)
    if _string(raw.get("watch_id"), f"{context}.watch_id") != watch["watch_id"]:
        raise ForwardOperationsError(f"{context}.watch_id must match the clock watch")
    return {
        "watch_id": watch["watch_id"],
        "prospective_start_utc": watch["prospective_start_utc"],
        "producer_workflow": _string(raw.get("producer_workflow"), f"{context}.producer_workflow"),
        "producer_ref": _string(raw.get("producer_ref"), f"{context}.producer_ref"),
        "dispatcher": _string(raw.get("dispatcher"), f"{context}.dispatcher"),
        "artifact_name": _string(raw.get("artifact_name"), f"{context}.artifact_name"),
        "report_parser": _string(raw.get("report_parser"), f"{context}.report_parser"),
        "cadence_seconds": _positive_int(raw.get("cadence_seconds"), f"{context}.cadence_seconds"),
        "grace_seconds": _positive_int(raw.get("grace_seconds"), f"{context}.grace_seconds", allow_zero=True),
        "boundary_seconds": _positive_int(raw.get("boundary_seconds"), f"{context}.boundary_seconds"),
    }


def build_forward_operations_registry_v2(
    clock_config: Mapping[str, Any],
    registry_template: Mapping[str, Any],
    *,
    source_identities: Mapping[str, Any],
    generated_at_utc: str,
) -> dict[str, Any]:
    """Validate one no-PnL operational row for every nonterminal clock watch."""

    moment = _utc(generated_at_utc, "generated_at_utc")
    watches = _open_watches(clock_config)
    template = _mapping(registry_template, "registry_template")
    raw_rows = _list(template.get("watches"), "registry_template.watches")
    lookup: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(raw_rows):
        mapping = _mapping(row, f"registry_template.watches[{index}]")
        watch_id = _string(mapping.get("watch_id"), f"registry_template.watches[{index}].watch_id")
        if watch_id in lookup:
            raise ForwardOperationsError(f"registry_template duplicates watch {watch_id}")
        lookup[watch_id] = mapping
    open_ids = {item["watch_id"] for item in watches}
    if set(lookup) != open_ids:
        raise ForwardOperationsError(f"registry_template must map exactly nonterminal watches; missing={sorted(open_ids-set(lookup))}, extra={sorted(set(lookup)-open_ids)}")
    rows = [_registry_row(lookup[watch["watch_id"]], watch["watch_id"], watch) for watch in sorted(watches, key=lambda item: item["watch_id"])]
    source_set = _source_set(source_identities)
    return _result(
        {
            "schema": REGISTRY_SCHEMA,
            "analysis": "forward_operations_registry_v2",
            "generated_at_utc": _format_utc(moment),
            "source_set": source_set,
            "watches": rows,
            "monitoring_scope": "artifact_and_report_heartbeat_only",
            "dispatch_authority": "NONE",
            "claims": {
                "inspects_strategy_pnl": False,
                "computes_strategy_verdicts": False,
                "promotes_any_strategy": False,
                "dispatches_workflows": False,
                "live_order_transmission_supported": False,
            },
            "non_authority_claims": non_authority_claims(),
        },
        "registry_sha256",
    )


def _heartbeat_observation(value: object, context: str) -> dict[str, Any]:
    raw = _mapping(value, context)
    active = raw.get("active_run")
    if type(active) is not bool:
        raise ForwardOperationsError(f"{context}.active_run must be boolean")
    result = {"watch_id": _string(raw.get("watch_id"), f"{context}.watch_id"), "active_run": active}
    for key in ("last_successful_run_utc", "artifact_created_at_utc", "report_as_of_utc", "latest_completed_boundary_utc"):
        value_at = raw.get(key)
        result[key] = _format_utc(_utc(value_at, f"{context}.{key}")) if value_at is not None else None
    return result


def assess_forward_operations_heartbeat_v2(
    registry: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    now_utc: str,
) -> dict[str, Any]:
    """Assess child-run/artifact/as-of/boundary freshness without dispatching anything."""

    checked = _utc(now_utc, "now_utc")
    normalized_registry = _validate_result_hash(registry, "registry_sha256", "registry")
    if normalized_registry.get("schema") != REGISTRY_SCHEMA:
        raise ForwardOperationsError("registry schema is unsupported")
    rows = _list(normalized_registry.get("watches"), "registry.watches")
    registry_by_id = {_string(_mapping(item, "registry row").get("watch_id"), "registry row.watch_id"): _mapping(item, "registry row") for item in rows}
    if len(registry_by_id) != len(rows):
        raise ForwardOperationsError("registry contains duplicate watch rows")
    actual = [_heartbeat_observation(item, f"observations[{index}]") for index, item in enumerate(observations)]
    by_id = {item["watch_id"]: item for item in actual}
    if len(by_id) != len(actual):
        raise ForwardOperationsError("observations contains duplicate watch rows")
    unknown = sorted(set(by_id) - set(registry_by_id))
    if unknown:
        raise ForwardOperationsError(f"observations contains unknown watches: {unknown}")

    findings: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for watch_id in sorted(registry_by_id):
        row = registry_by_id[watch_id]
        start = _utc(row.get("prospective_start_utc"), f"{watch_id}.prospective_start_utc")
        cadence = timedelta(seconds=_positive_int(row.get("cadence_seconds"), f"{watch_id}.cadence_seconds"))
        grace = timedelta(seconds=_positive_int(row.get("grace_seconds"), f"{watch_id}.grace_seconds", allow_zero=True))
        boundary = timedelta(seconds=_positive_int(row.get("boundary_seconds"), f"{watch_id}.boundary_seconds"))
        obs = by_id.get(watch_id)
        status = {"watch_id": watch_id, "state": "HEALTHY", "recovery_dispatch": "NOT_AUTHORIZED", "observation_present": obs is not None}
        if checked < start:
            status["state"] = "PRESTART_NO_SLO"
            statuses.append(status)
            continue
        if obs is None or obs["last_successful_run_utc"] is None:
            if checked > start + cadence + grace:
                status["state"] = "NO_SUCCESSFUL_CHILD_RUN"
                findings.append({"severity": "error", "code": "no_successful_child_run", "watch_id": watch_id, "detail": "no successful child run was supplied after cadence plus grace"})
            else:
                status["state"] = "AWAITING_FIRST_RUN"
            statuses.append(status)
            continue
        stale_before = checked - cadence - grace
        errors: list[str] = []
        if _utc(obs["last_successful_run_utc"], "last_successful_run_utc") < stale_before:
            errors.append("stale_child_run")
        if obs["artifact_created_at_utc"] is None or _utc(obs["artifact_created_at_utc"], "artifact_created_at_utc") < stale_before:
            errors.append("stale_artifact")
        if obs["report_as_of_utc"] is None or _utc(obs["report_as_of_utc"], "report_as_of_utc") < stale_before:
            errors.append("stale_report_as_of")
        required_boundary = checked - boundary - grace
        if obs["latest_completed_boundary_utc"] is None or _utc(obs["latest_completed_boundary_utc"], "latest_completed_boundary_utc") < required_boundary:
            errors.append("nonadvancing_completed_boundary")
        if obs["active_run"]:
            status["recovery_dispatch"] = "SUPPRESSED_ACTIVE_RUN"
            findings.append({"severity": "info", "code": "active_run_no_duplicate_dispatch", "watch_id": watch_id, "detail": "active child run observed; this reporting layer will not dispatch a duplicate"})
        if errors:
            status["state"] = "OPERATIONAL_ERROR"
            status["error_codes"] = errors
            for code in errors:
                findings.append({"severity": "error", "code": code, "watch_id": watch_id, "detail": f"{watch_id} violates cadence/boundary observation only; no market interval is backfilled"})
        statuses.append(status)
    highest = "error" if any(item["severity"] == "error" for item in findings) else "info"
    return _result(
        {
            "schema": HEARTBEAT_SCHEMA,
            "analysis": "forward_operations_heartbeat_v2",
            "checked_at_utc": _format_utc(checked),
            "registry_sha256": normalized_registry["registry_sha256"],
            "watch_statuses": statuses,
            "findings": findings,
            "operational_check_conclusion": "FAIL" if highest == "error" else "PASS",
            "claims": {
                "inspects_strategy_pnl": False,
                "computes_strategy_verdicts": False,
                "dispatches_workflows": False,
                "backfills_market_intervals": False,
                "live_order_transmission_supported": False,
            },
            "non_authority_claims": non_authority_claims(),
        },
        "heartbeat_sha256",
    )


def _workflow_uploads(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ForwardOperationsError(f"workflow is not readable: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    uploads: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        if "uses: actions/upload-artifact@" not in lines[index]:
            index += 1
            continue
        block: list[str] = []
        index += 1
        while index < len(lines) and not (lines[index].lstrip().startswith("- ") and "uses:" in lines[index]):
            block.append(lines[index])
            index += 1
        name = None
        retention = None
        for line in block:
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped.split(":", 1)[1].strip().strip("'\"")
            if stripped.startswith("retention-days:"):
                raw = stripped.split(":", 1)[1].strip().strip("'\"")
                if raw.isdigit():
                    retention = int(raw)
        if name:
            uploads.append({"name": name, "retention_days": retention})
    return uploads


def audit_retention_producer_contract_v2(retention_inventory: Mapping[str, Any], *, repo_root: Path | str = ".") -> dict[str, Any]:
    """Check declared v2 report/checkpoint uploads without treating local files as durable storage."""

    inventory = _validate_result_hash(retention_inventory, "inventory_sha256", "retention_inventory")
    if inventory.get("schema") != RETENTION_SCHEMA:
        raise ForwardOperationsError("retention_inventory schema is unsupported")
    root = Path(repo_root)
    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    cache: dict[str, list[dict[str, Any]]] = {}
    for watch in _list(inventory.get("watches"), "retention_inventory.watches"):
        row = _mapping(watch, "retention inventory watch")
        watch_id = _string(row.get("watch_id"), "retention inventory watch.watch_id")
        for artifact in _list(row.get("artifacts"), f"{watch_id}.artifacts"):
            declared = _mapping(artifact, f"{watch_id}.artifact")
            workflow = _string(declared.get("producer_workflow"), f"{watch_id}.producer_workflow")
            if workflow not in cache:
                try:
                    cache[workflow] = _workflow_uploads(root / workflow)
                except ForwardOperationsError as exc:
                    cache[workflow] = []
                    findings.append({"severity": "error", "code": "producer_workflow_unreadable", "watch_id": watch_id, "artifact_name": declared.get("artifact_name"), "detail": str(exc)})
            matching = [upload for upload in cache[workflow] if upload["name"] == declared.get("artifact_name")]
            actual = matching[0] if matching else None
            record = {"watch_id": watch_id, "role": declared.get("role"), "artifact_name": declared.get("artifact_name"), "producer_workflow": workflow, "requested_retention_days": declared.get("requested_retention_days"), "producer_upload_present": actual is not None, "declared_retention_days": actual["retention_days"] if actual else None, "external_immutable_copy_status": _mapping(declared.get("external_immutable_copy"), "external_immutable_copy").get("status")}
            if actual is None:
                findings.append({"severity": "error", "code": "required_artifact_not_uploaded", "watch_id": watch_id, "artifact_name": declared.get("artifact_name"), "detail": "declared report/checkpoint/hash manifest has no producer upload in the named workflow"})
            elif actual["retention_days"] is None:
                findings.append({"severity": "error", "code": "producer_retention_not_explicit", "watch_id": watch_id, "artifact_name": declared.get("artifact_name"), "detail": "producer upload has no explicit retention-days declaration"})
            elif actual["retention_days"] < declared.get("requested_retention_days"):
                findings.append({"severity": "error", "code": "producer_retention_shorter_than_requested", "watch_id": watch_id, "artifact_name": declared.get("artifact_name"), "detail": "producer retention-days is shorter than caller-declared v2 retention"})
            if record["external_immutable_copy_status"] != "UNVERIFIED_EXTERNAL":
                findings.append({"severity": "error", "code": "external_immutable_copy_blocked", "watch_id": watch_id, "artifact_name": declared.get("artifact_name"), "detail": "durable immutable copy is an external activation blocker, not locally verified storage"})
            records.append(record)
    return _result(
        {
            "schema": PRODUCER_CONTRACT_SCHEMA,
            "analysis": "forward_retention_producer_contract_v2",
            "inventory_sha256": inventory["inventory_sha256"],
            "records": records,
            "findings": findings,
            "contract_ok": not any(item["severity"] == "error" for item in findings),
            "claims": {
                "checks_local_workflow_declarations_only": True,
                "external_storage_verified": False,
                "computes_strategy_verdicts": False,
                "live_order_transmission_supported": False,
            },
            "non_authority_claims": non_authority_claims(),
        },
        "contract_sha256",
    )


def load_json_object(path: Path | str) -> dict[str, Any]:
    """Read a local JSON object for the offline v2 CLI."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardOperationsError(f"cannot read JSON object from {path}") from exc
    return dict(_mapping(value, f"JSON at {path}"))

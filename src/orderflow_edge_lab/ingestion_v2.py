"""Opt-in, offline-verifiable market-data acquisition contracts (v2).

This module is deliberately separate from legacy recorders and historical readers.
It neither opens a provider connection nor schedules a collector.  It validates
caller-supplied prospective evidence: local raw-page identities, declared
policies, panel readiness, bounded-retry audit events, receipt/processor
telemetry, terminal completion, and expected-grid coverage.

A local hash proves only local bytes.  In particular, none of these APIs claims
provider completeness, provider entitlement, durable external retention,
exchange-clock calibration, a research result, or a live-trading capability.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import json
import math
from pathlib import Path
import socket
import time
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    ContractValidationError,
    build_canonical_source_set,
    build_coverage_result,
    build_file_identity,
    build_manifest_result,
    build_source_record,
    build_utc_interval,
    canonical_json_sha256,
    missing_value,
    non_authority_claims,
    observed_value,
    validate_coverage_result,
    validate_file_identity,
    validate_manifest_result,
    validate_utc_interval,
)

UTC = timezone.utc
SESSION_TERMINAL_MANIFEST_TYPE = "ingestion.session_terminal.v3"
HISTORICAL_MANIFEST_TYPE = "ingestion.historical_acquisition.v2"
READINESS_MANIFEST_TYPE = "ingestion.provider_readiness.v2"
CAPABILITY_SCHEMA = "orderflow_edge_lab.provider_capability.v2"


class IngestionV2Error(ValueError):
    """Raised when prospective ingestion evidence is malformed or ineligible."""


class RestAttemptsExhaustedV2(IngestionV2Error):
    """A bounded REST attempt budget ended without a valid payload."""

    def __init__(self, message: str, attempts: Sequence[Mapping[str, Any]]):
        super().__init__(message)
        self.attempts = [dict(item) for item in attempts]


@dataclass(frozen=True)
class _QueuedFrame:
    sequence: int
    payload: Mapping[str, Any]
    received_at_utc: str
    received_monotonic_ns: int


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise IngestionV2Error(f"{field} must be a JSON object with string keys")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise IngestionV2Error(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionV2Error(f"{field} must be a nonempty string")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise IngestionV2Error(f"{field} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise IngestionV2Error(f"{field} must be a nonnegative integer")
    return value


def _positive_int(value: object, field: str) -> int:
    result = _nonnegative_int(value, field)
    if result < 1:
        raise IngestionV2Error(f"{field} must be positive")
    return result


def _finite_number(value: object, field: str, *, positive: bool = False) -> float:
    if type(value) is int:
        result = float(value)
    elif isinstance(value, float):
        result = value
    else:
        raise IngestionV2Error(f"{field} must be a finite number")
    if not math.isfinite(result) or (positive and result <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise IngestionV2Error(f"{field} must be a {qualifier} number")
    return result


def _json_copy(value: object, field: str) -> Any:
    try:
        # The shared contract is the canonical JSON authority; the roundtrip also
        # prevents caller-owned mutable mappings from changing a built manifest.
        encoded_hash = canonical_json_sha256(value)
        del encoded_hash
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise IngestionV2Error(f"{field} must contain ordinary finite JSON") from exc


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IngestionV2Error(f"{field} must be an ISO-8601 UTC-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestionV2Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IngestionV2Error(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _policy_hash(policy: Mapping[str, Any], field: str) -> tuple[dict[str, Any], str]:
    """Require a caller-declared policy object and bind its exact content.

    There are no policy defaults in v2.  The policy hash must be supplied by the
    caller and match every non-hash field, so a terminal cannot silently inherit
    current recorder settings or a retrospective readiness rule.
    """

    raw = _mapping(policy, field)
    if "policy_sha256" not in raw or "policy_id" not in raw:
        raise IngestionV2Error(f"{field} must include caller-supplied policy_id and policy_sha256")
    unsigned = {key: value for key, value in raw.items() if key != "policy_sha256"}
    _string(unsigned.get("policy_id"), f"{field}.policy_id")
    expected = canonical_json_sha256(unsigned)
    supplied = _sha256(raw.get("policy_sha256"), f"{field}.policy_sha256")
    if supplied != expected:
        raise IngestionV2Error(f"{field}.policy_sha256 does not bind the supplied policy")
    return _json_copy(dict(raw), field), supplied


def _validate_readiness_policy(policy: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    copied, digest = _policy_hash(policy, "readiness_policy")
    required = {
        "policy_id",
        "policy_sha256",
        "max_symbol_idle_seconds",
        "required_streams",
        "require_subscription_ack",
        "allow_degraded_diagnostics",
    }
    if set(copied) != required:
        raise IngestionV2Error("readiness_policy has unsupported or missing fields")
    _finite_number(copied["max_symbol_idle_seconds"], "readiness_policy.max_symbol_idle_seconds", positive=True)
    streams = _list(copied["required_streams"], "readiness_policy.required_streams")
    normalized = [_string(item, "readiness_policy.required_streams item").lower() for item in streams]
    if sorted(normalized) != ["depth", "snapshot", "trade"]:
        raise IngestionV2Error("readiness_policy.required_streams must declare exactly snapshot, depth, and trade")
    if copied["require_subscription_ack"] is not True:
        raise IngestionV2Error("readiness_policy.require_subscription_ack must be true for a complete panel")
    if type(copied["allow_degraded_diagnostics"]) is not bool:
        raise IngestionV2Error("readiness_policy.allow_degraded_diagnostics must be boolean")
    copied["required_streams"] = ["snapshot", "depth", "trade"]
    return copied, digest


def _validate_retry_policy(policy: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    copied, digest = _policy_hash(policy, "retry_policy")
    required = {"policy_id", "policy_sha256", "max_attempts", "base_backoff_seconds", "retry_http_statuses"}
    if set(copied) != required:
        raise IngestionV2Error("retry_policy has unsupported or missing fields")
    _positive_int(copied["max_attempts"], "retry_policy.max_attempts")
    _finite_number(copied["base_backoff_seconds"], "retry_policy.base_backoff_seconds")
    statuses = _list(copied["retry_http_statuses"], "retry_policy.retry_http_statuses")
    normalized = [_positive_int(item, "retry_policy.retry_http_statuses item") for item in statuses]
    if len(normalized) != len(set(normalized)):
        raise IngestionV2Error("retry_policy.retry_http_statuses must not contain duplicates")
    if any(status != 429 and not 500 <= status <= 599 for status in normalized):
        raise IngestionV2Error("retry policy may permit only HTTP 429 and 5xx; 401/403 and other 4xx are never transient")
    copied["retry_http_statuses"] = sorted(normalized)
    return copied, digest


def _validate_historical_policy(policy: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    copied, digest = _policy_hash(policy, "acquisition_policy")
    required = {"policy_id", "policy_sha256", "allow_diagnostic_only"}
    if set(copied) != required or type(copied.get("allow_diagnostic_only")) is not bool:
        raise IngestionV2Error("acquisition_policy must declare only policy_id, allow_diagnostic_only, and policy_sha256")
    return copied, digest


def _build_source_set(sources: Iterable[Mapping[str, Any]], field: str) -> dict[str, Any]:
    try:
        return build_canonical_source_set(sources)
    except ContractValidationError as exc:
        raise IngestionV2Error(f"{field}: {exc}") from exc


def _validated_interval(value: Mapping[str, Any], field: str, *, convention: str = CLOSED_OPEN) -> dict[str, str]:
    try:
        interval = validate_utc_interval(value)
    except ContractValidationError as exc:
        raise IngestionV2Error(f"{field}: {exc}") from exc
    if interval["convention"] != convention:
        raise IngestionV2Error(f"{field} must use {convention}")
    return interval


def _safe_url(value: object, field: str) -> str:
    url = _string(value, field)
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        raise IngestionV2Error(f"{field} must be an absolute non-credential HTTP(S) URL")
    sensitive = {"api_key", "apikey", "key", "secret", "token", "signature", "authorization", "password"}
    if any(name.lower() in sensitive for name, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise IngestionV2Error(f"{field} must not contain credential-like query parameters")
    return url


def _coverage_observations(expected_ids: Sequence[str], observed: Mapping[str, float], missing_reason: str) -> list[dict[str, Any]]:
    return [
        {
            "observation_id": observation_id,
            "observation": observed_value(observed[observation_id]) if observation_id in observed else missing_value(missing_reason),
        }
        for observation_id in expected_ids
    ]


def _manifest_or_error(manifest_type: str, source_set: Mapping[str, Any], outcome: str, *, coverage: Mapping[str, Any] | None, policy_sha256: str, attributes: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return build_manifest_result(
            manifest_type,
            source_set,
            outcome,
            coverage=coverage,
            policy_sha256=policy_sha256,
            attributes=attributes,
        )
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc


def build_provider_capability_contract_v2(
    capability_path: str | Path,
    *,
    source_id: str,
) -> dict[str, Any]:
    """Hash-bind a nonsecret provider capability artifact stored in a local file.

    The artifact is only an operator/provider declaration.  It is not an
    entitlement probe and all non-authority claims remain false.  Required JSON
    fields are ``provider``, ``approved_routes``, ``event_types``,
    ``instrument_mappings``, ``historical_interval`` (or null), ``delayed``,
    ``export_time_zone``, and ``redistribution_restriction``.
    """

    path = Path(capability_path)
    try:
        capability_raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionV2Error("capability_path must name readable JSON") from exc
    capability = _mapping(capability_raw, "capability artifact")
    required = {
        "provider",
        "approved_routes",
        "event_types",
        "instrument_mappings",
        "historical_interval",
        "delayed",
        "export_time_zone",
        "redistribution_restriction",
    }
    if set(capability) != required:
        raise IngestionV2Error("capability artifact has unsupported or missing fields")
    provider = _string(capability["provider"], "capability.provider")
    routes = [_safe_url(item, "capability.approved_routes item") for item in _list(capability["approved_routes"], "capability.approved_routes")]
    if not routes or len(routes) != len(set(routes)):
        raise IngestionV2Error("capability.approved_routes must be a unique nonempty array")
    event_types = sorted({_string(item, "capability.event_types item").upper() for item in _list(capability["event_types"], "capability.event_types")})
    if not event_types:
        raise IngestionV2Error("capability.event_types must not be empty")
    mappings: list[dict[str, str]] = []
    for item in _list(capability["instrument_mappings"], "capability.instrument_mappings"):
        row = _mapping(item, "capability.instrument_mappings item")
        if set(row) != {"logical_symbol", "provider_symbol"}:
            raise IngestionV2Error("capability.instrument_mappings item has unsupported shape")
        mappings.append({"logical_symbol": _string(row["logical_symbol"], "logical_symbol").upper(), "provider_symbol": _string(row["provider_symbol"], "provider_symbol").upper()})
    mappings.sort(key=lambda item: item["logical_symbol"])
    if not mappings or len({item["logical_symbol"] for item in mappings}) != len(mappings) or len({item["provider_symbol"] for item in mappings}) != len(mappings):
        raise IngestionV2Error("capability instrument mappings must be nonempty and one-to-one")
    historical_raw = capability["historical_interval"]
    historical_interval = None if historical_raw is None else _validated_interval(_mapping(historical_raw, "capability.historical_interval"), "capability.historical_interval")
    if type(capability["delayed"]) is not bool:
        raise IngestionV2Error("capability.delayed must be boolean")
    normalized_capability = {
        "provider": provider,
        "approved_routes": sorted(routes),
        "event_types": event_types,
        "instrument_mappings": mappings,
        "historical_interval": historical_interval,
        "delayed": capability["delayed"],
        "export_time_zone": _string(capability["export_time_zone"], "capability.export_time_zone"),
        "redistribution_restriction": _string(capability["redistribution_restriction"], "capability.redistribution_restriction"),
    }
    try:
        identity = build_file_identity(path, logical_name=_string(source_id, "source_id"))
        source_set = build_canonical_source_set([build_source_record(source_id, identity)])
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    unsigned = {
        "schema": CAPABILITY_SCHEMA,
        "analysis": "provider_capability_contract_v2",
        "source_set": source_set,
        "capability": normalized_capability,
        "non_authority_claims": non_authority_claims(),
    }
    return {**unsigned, "capability_sha256": canonical_json_sha256(unsigned)}


def validate_provider_capability_contract_v2(contract: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(contract, "provider capability contract")
    required = {"schema", "analysis", "source_set", "capability", "non_authority_claims", "capability_sha256"}
    if set(raw) != required or raw.get("schema") != CAPABILITY_SCHEMA or raw.get("analysis") != "provider_capability_contract_v2":
        raise IngestionV2Error("provider capability contract has unsupported shape")
    # Reuse the builder's strict normalizer without touching the original file.
    source_set = _build_source_set(_list(_mapping(raw["source_set"], "source_set").get("sources"), "source_set.sources"), "source_set")
    capability = _json_copy(_mapping(raw["capability"], "capability"), "capability")
    # Validate this in-memory declaration using the exact same structural checks.
    temp = {"provider": capability.get("provider"), "approved_routes": capability.get("approved_routes"), "event_types": capability.get("event_types"), "instrument_mappings": capability.get("instrument_mappings"), "historical_interval": capability.get("historical_interval"), "delayed": capability.get("delayed"), "export_time_zone": capability.get("export_time_zone"), "redistribution_restriction": capability.get("redistribution_restriction")}
    # Local validation that never accesses a provider or assumes rights.
    provider = _string(temp["provider"], "capability.provider")
    routes = sorted({_safe_url(item, "capability.approved_routes item") for item in _list(temp["approved_routes"], "capability.approved_routes")})
    event_types = sorted({_string(item, "capability.event_types item").upper() for item in _list(temp["event_types"], "capability.event_types")})
    mappings: list[dict[str, str]] = []
    for item in _list(temp["instrument_mappings"], "capability.instrument_mappings"):
        row = _mapping(item, "capability.instrument_mappings item")
        if set(row) != {"logical_symbol", "provider_symbol"}:
            raise IngestionV2Error("capability.instrument_mappings item has unsupported shape")
        mappings.append({"logical_symbol": _string(row["logical_symbol"], "logical_symbol").upper(), "provider_symbol": _string(row["provider_symbol"], "provider_symbol").upper()})
    mappings.sort(key=lambda item: item["logical_symbol"])
    if not routes or not event_types or not mappings or len({item["logical_symbol"] for item in mappings}) != len(mappings) or len({item["provider_symbol"] for item in mappings}) != len(mappings):
        raise IngestionV2Error("capability contract has empty or non-one-to-one declared scope")
    historical = None if temp["historical_interval"] is None else _validated_interval(_mapping(temp["historical_interval"], "historical_interval"), "historical_interval")
    if type(temp["delayed"]) is not bool:
        raise IngestionV2Error("capability.delayed must be boolean")
    normalized_capability = {"provider": provider, "approved_routes": routes, "event_types": event_types, "instrument_mappings": mappings, "historical_interval": historical, "delayed": temp["delayed"], "export_time_zone": _string(temp["export_time_zone"], "export_time_zone"), "redistribution_restriction": _string(temp["redistribution_restriction"], "redistribution_restriction")}
    if raw.get("non_authority_claims") != non_authority_claims():
        raise IngestionV2Error("provider capability non-authority claims must remain false")
    unsigned = {"schema": CAPABILITY_SCHEMA, "analysis": "provider_capability_contract_v2", "source_set": source_set, "capability": normalized_capability, "non_authority_claims": non_authority_claims()}
    if _sha256(raw.get("capability_sha256"), "capability_sha256") != canonical_json_sha256(unsigned):
        raise IngestionV2Error("capability_sha256 does not bind the capability contract")
    return {**unsigned, "capability_sha256": canonical_json_sha256(unsigned)}


def _normal_panel(panel: Sequence[Mapping[str, Any]], field: str = "requested_panel") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in panel:
        row = _mapping(item, f"{field} item")
        if set(row) != {"symbol", "venue_symbol"}:
            raise IngestionV2Error(f"{field} item must contain exactly symbol and venue_symbol")
        rows.append({"symbol": _string(row["symbol"], f"{field}.symbol").upper(), "venue_symbol": _string(row["venue_symbol"], f"{field}.venue_symbol").upper()})
    rows.sort(key=lambda item: item["symbol"])
    if not rows or len({item["symbol"] for item in rows}) != len(rows) or len({item["venue_symbol"] for item in rows}) != len(rows):
        raise IngestionV2Error(f"{field} must be nonempty with one-to-one logical/native symbols")
    return rows


def validate_capability_request_v2(
    capability_contract: Mapping[str, Any],
    *,
    provider: str,
    requested_panel: Sequence[Mapping[str, Any]],
    required_event_types: Sequence[str],
    requested_interval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject a request outside a nonsecret capability declaration before parsing data."""

    capability = validate_provider_capability_contract_v2(capability_contract)
    provider_name = _string(provider, "provider")
    if provider_name != capability["capability"]["provider"]:
        raise IngestionV2Error("provider does not match the supplied capability artifact")
    panel = _normal_panel(requested_panel)
    mappings = {(item["logical_symbol"], item["provider_symbol"]) for item in capability["capability"]["instrument_mappings"]}
    if any((item["symbol"], item["venue_symbol"]) not in mappings for item in panel):
        raise IngestionV2Error("requested panel has a symbol mapping outside declared capability scope")
    events = sorted({_string(item, "required_event_types item").upper() for item in required_event_types})
    if not events or not set(events).issubset(set(capability["capability"]["event_types"])):
        raise IngestionV2Error("requested event type is outside declared capability scope")
    interval = None
    if requested_interval is not None:
        interval = _validated_interval(requested_interval, "requested_interval")
        allowed = capability["capability"]["historical_interval"]
        if allowed is None:
            raise IngestionV2Error("capability artifact does not declare a permitted historical interval")
        start = _parse_utc(interval["start_utc"], "requested_interval.start_utc")
        end = _parse_utc(interval["end_utc"], "requested_interval.end_utc")
        allowed_start = _parse_utc(allowed["start_utc"], "capability.historical_interval.start_utc")
        allowed_end = _parse_utc(allowed["end_utc"], "capability.historical_interval.end_utc")
        if start < allowed_start or end > allowed_end:
            raise IngestionV2Error("requested historical interval is outside declared capability scope")
    return {"schema": "orderflow_edge_lab.capability_request_check.v2", "provider": provider_name, "requested_panel": panel, "required_event_types": events, "requested_interval": interval, "capability_sha256": capability["capability_sha256"], "status": "WITHIN_DECLARED_SCOPE", "non_authority_claims": non_authority_claims()}


def build_provider_readiness_manifest_v2(
    *,
    provider: str,
    requested_panel: Sequence[Mapping[str, Any]],
    observed_states: Sequence[Mapping[str, Any]],
    capability_contract: Mapping[str, Any],
    evidence_sources: Sequence[Mapping[str, Any]],
    readiness_policy: Mapping[str, Any],
    mode: str,
) -> dict[str, Any]:
    """Build preflight panel coverage; only a fully observed strict panel is complete."""

    policy, policy_sha = _validate_readiness_policy(readiness_policy)
    if mode not in {"STRICT", "DEGRADED_DIAGNOSTIC"}:
        raise IngestionV2Error("mode must be STRICT or DEGRADED_DIAGNOSTIC")
    panel = _normal_panel(requested_panel)
    validate_capability_request_v2(capability_contract, provider=provider, requested_panel=panel, required_event_types=["SNAPSHOT", "DEPTH", "TRADE"])
    capability = validate_provider_capability_contract_v2(capability_contract)
    states_by_symbol: dict[str, dict[str, Any]] = {}
    for item in observed_states:
        row = _mapping(item, "observed_states item")
        required = {"symbol", "venue_symbol", "subscription_acknowledged", "snapshot_observed", "observed_streams"}
        if set(row) != required:
            raise IngestionV2Error("observed_states item has unsupported shape")
        symbol = _string(row["symbol"], "observed_states.symbol").upper()
        if symbol in states_by_symbol:
            raise IngestionV2Error("observed_states symbols must be unique")
        if type(row["subscription_acknowledged"]) is not bool or type(row["snapshot_observed"]) is not bool:
            raise IngestionV2Error("observed readiness booleans must be boolean")
        streams = sorted({_string(value, "observed_streams item").lower() for value in _list(row["observed_streams"], "observed_streams")})
        states_by_symbol[symbol] = {"symbol": symbol, "venue_symbol": _string(row["venue_symbol"], "observed_states.venue_symbol").upper(), "subscription_acknowledged": row["subscription_acknowledged"], "snapshot_observed": row["snapshot_observed"], "observed_streams": streams}
    if set(states_by_symbol) - {item["symbol"] for item in panel}:
        raise IngestionV2Error("observed readiness includes an unrequested symbol")
    observations: list[dict[str, Any]] = []
    normalized_states: list[dict[str, Any]] = []
    for requested in panel:
        state = states_by_symbol.get(requested["symbol"])
        mapping_ok = state is not None and state["venue_symbol"] == requested["venue_symbol"]
        values = {
            "subscription_ack": bool(mapping_ok and state and state["subscription_acknowledged"]),
            "snapshot": bool(mapping_ok and state and state["snapshot_observed"]),
            "depth": bool(mapping_ok and state and "depth" in state["observed_streams"]),
            "trade": bool(mapping_ok and state and "trade" in state["observed_streams"]),
        }
        for key, present in values.items():
            observations.append({"observation_id": f"{requested['symbol']}:{key}", "observation": observed_value(1.0) if present else missing_value("preflight_not_observed")})
        normalized_states.append({"symbol": requested["symbol"], "venue_symbol": requested["venue_symbol"], **values})
    try:
        coverage = build_coverage_result("ingestion.panel_readiness", build_utc_interval("1970-01-01T00:00:00Z", "1970-01-01T00:00:01Z", convention=CLOSED_OPEN), observations)
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    sources = [dict(item) for item in evidence_sources]
    # Capability artifact is an identity-bearing input, so readiness binds it too.
    sources.extend(capability["source_set"]["sources"])
    source_set = _build_source_set(sources, "readiness evidence sources")
    complete = coverage["status"] == "COMPLETE" and mode == "STRICT"
    panel_status = "complete" if complete else "degraded"
    outcome = "COMPLETE" if complete else "DIAGNOSTIC_ONLY"
    attrs = {"analysis": "provider_readiness_v2", "provider": _string(provider, "provider"), "requested_panel": panel, "observed_states": normalized_states, "mode": mode, "panel_status": panel_status, "capability_sha256": capability["capability_sha256"], "policy": policy}
    return _manifest_or_error(READINESS_MANIFEST_TYPE, source_set, outcome, coverage=coverage, policy_sha256=policy_sha, attributes=attrs)


def validate_provider_readiness_manifest_v2(manifest: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized = validate_manifest_result(manifest)
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    if normalized["manifest_type"] != READINESS_MANIFEST_TYPE or normalized["coverage"] is None:
        raise IngestionV2Error("not a provider readiness manifest")
    attrs = _mapping(normalized["attributes"], "readiness attributes")
    required = {"analysis", "provider", "requested_panel", "observed_states", "mode", "panel_status", "capability_sha256", "policy"}
    if set(attrs) != required or attrs.get("analysis") != "provider_readiness_v2":
        raise IngestionV2Error("readiness manifest attributes have unsupported shape")
    policy, digest = _validate_readiness_policy(_mapping(attrs["policy"], "readiness policy"))
    if digest != normalized["policy_sha256"]:
        raise IngestionV2Error("readiness manifest policy hash mismatch")
    panel = _normal_panel(_list(attrs["requested_panel"], "requested_panel"))
    states = _list(attrs["observed_states"], "observed_states")
    coverage = validate_coverage_result(normalized["coverage"])
    expected_ids = sorted(f"{item['symbol']}:{kind}" for item in panel for kind in ("subscription_ack", "snapshot", "depth", "trade"))
    if [item["observation_id"] for item in coverage["observations"]] != expected_ids:
        raise IngestionV2Error("readiness coverage does not bind every required panel stream")
    complete = coverage["status"] == "COMPLETE" and attrs["mode"] == "STRICT"
    if attrs.get("panel_status") != ("complete" if complete else "degraded"):
        raise IngestionV2Error("readiness panel_status is inconsistent with stream coverage")
    if normalized["outcome"] != ("COMPLETE" if complete else "DIAGNOSTIC_ONLY"):
        raise IngestionV2Error("readiness outcome is inconsistent with coverage")
    return normalized


def _normalize_terminal_state(state: Mapping[str, Any], *, terminal_monotonic_ns: int, terminal_at_utc: datetime, policy: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    raw = _mapping(state, "symbol_states item")
    required = {"symbol", "venue_symbol", "subscription_acknowledged", "snapshot_observed", "depth_observed", "trade_observed", "last_receipt_monotonic_ns", "last_receipt_at_utc", "connection_epoch", "feed_silence_events"}
    if set(raw) != required:
        raise IngestionV2Error("symbol_states item has unsupported shape")
    symbol = _string(raw["symbol"], "symbol_states.symbol").upper()
    last_mono = _nonnegative_int(raw["last_receipt_monotonic_ns"], "last_receipt_monotonic_ns")
    if last_mono > terminal_monotonic_ns:
        raise IngestionV2Error("symbol last receipt cannot be after the terminal monotonic timestamp")
    last_utc = _parse_utc(raw["last_receipt_at_utc"], "last_receipt_at_utc")
    if last_utc > terminal_at_utc:
        raise IngestionV2Error("symbol last receipt cannot be after terminal UTC timestamp")
    if type(raw["subscription_acknowledged"]) is not bool or any(type(raw[key]) is not bool for key in ("snapshot_observed", "depth_observed", "trade_observed")):
        raise IngestionV2Error("symbol readiness fields must be booleans")
    silence_events = _list(raw["feed_silence_events"], "feed_silence_events")
    normalized_silence = [_json_copy(_mapping(item, "feed_silence event"), "feed_silence event") for item in silence_events]
    idle_seconds = (terminal_monotonic_ns - last_mono) / 1_000_000_000.0
    values = {
        "subscription_ack": raw["subscription_acknowledged"],
        "snapshot": raw["snapshot_observed"],
        "depth": raw["depth_observed"],
        "trade": raw["trade_observed"],
        "liveness": idle_seconds <= float(policy["max_symbol_idle_seconds"]) and not normalized_silence,
    }
    normalized = {"symbol": symbol, "venue_symbol": _string(raw["venue_symbol"], "venue_symbol").upper(), "last_receipt_monotonic_ns": last_mono, "last_receipt_at_utc": _utc_text(last_utc), "connection_epoch": _nonnegative_int(raw["connection_epoch"], "connection_epoch"), "feed_silence_events": normalized_silence, "idle_seconds_at_terminal": idle_seconds, **values}
    return normalized, {key: 1.0 for key, present in values.items() if present}


def build_session_terminal_v2(
    *,
    requested_interval: Mapping[str, Any],
    symbol_states: Sequence[Mapping[str, Any]],
    evidence_sources: Sequence[Mapping[str, Any]],
    readiness_manifest: Mapping[str, Any],
    readiness_policy: Mapping[str, Any],
    terminal_at_utc: str,
    terminal_monotonic_ns: int,
    terminal_cause: str,
    telemetry: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a completion-bound capture terminal record.

    ``COMPLETE`` is intentionally narrow: every requested readiness stream must
    be observed, no symbol may exceed the caller-declared idle limit, no silence
    record or queue overflow may exist, strict panel readiness must be complete,
    and the terminal wall clock must reach the requested interval end.
    """

    interval = _validated_interval(requested_interval, "requested_interval")
    policy, policy_sha = _validate_readiness_policy(readiness_policy)
    readiness = validate_provider_readiness_manifest_v2(readiness_manifest)
    terminal_time = _parse_utc(terminal_at_utc, "terminal_at_utc")
    if terminal_time < _parse_utc(interval["end_utc"], "requested_interval.end_utc"):
        raise IngestionV2Error("terminal_at_utc cannot claim a requested interval that has not ended")
    terminal_mono = _nonnegative_int(terminal_monotonic_ns, "terminal_monotonic_ns")
    cause = _string(terminal_cause, "terminal_cause")
    telemetry_copy = _json_copy(_mapping(telemetry, "telemetry"), "telemetry")
    overflow = _nonnegative_int(telemetry_copy.get("overflow_count"), "telemetry.overflow_count")
    open_barriers = _nonnegative_int(telemetry_copy.get("open_recovery_barrier_count", 0), "telemetry.open_recovery_barrier_count")
    source_set = _build_source_set(evidence_sources, "terminal evidence sources")
    states: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in symbol_states:
        state, values = _normalize_terminal_state(item, terminal_monotonic_ns=terminal_mono, terminal_at_utc=terminal_time, policy=policy)
        if state["symbol"] in seen:
            raise IngestionV2Error("symbol_states symbols must be unique")
        seen.add(state["symbol"])
        states.append(state)
        for kind in ("subscription_ack", "snapshot", "depth", "trade", "liveness"):
            observations.append({"observation_id": f"{state['symbol']}:{kind}", "observation": observed_value(values[kind]) if kind in values else missing_value("symbol_capture_contract_not_satisfied")})
    if not states:
        raise IngestionV2Error("symbol_states must be nonempty")
    states.sort(key=lambda item: item["symbol"])
    try:
        coverage = build_coverage_result("ingestion.capture_terminal", interval, observations)
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    strict_readiness = readiness["outcome"] == "COMPLETE" and readiness["attributes"]["panel_status"] == "complete"
    readiness_mappings = {(item["symbol"], item["venue_symbol"]) for item in readiness["attributes"]["requested_panel"]}
    state_mappings = {(item["symbol"], item["venue_symbol"]) for item in states}
    panel_matches = readiness_mappings == state_mappings
    complete = coverage["status"] == "COMPLETE" and strict_readiness and panel_matches and overflow == 0 and open_barriers == 0 and cause == "REQUESTED_INTERVAL_COMPLETE"
    fatal_causes = {"QUEUE_OVERFLOW", "EXCEPTION", "RECOVERY_UNRESOLVED", "REST_EXHAUSTED", "REQUESTED_INTERVAL_NOT_REACHED"}
    completion_status = "complete" if complete else ("failed" if cause in fatal_causes else "degraded")
    attrs = {"analysis": "session_terminal_v3", "completion_status": completion_status, "terminal_cause": cause, "requested_interval": interval, "terminal_at_utc": _utc_text(terminal_time), "terminal_monotonic_ns": terminal_mono, "symbol_states": states, "telemetry": telemetry_copy, "readiness_manifest_sha256": readiness["manifest_sha256"], "readiness_panel_status": readiness["attributes"]["panel_status"], "panel_matches_terminal_symbols": panel_matches, "policy": policy}
    return _manifest_or_error(SESSION_TERMINAL_MANIFEST_TYPE, source_set, "COMPLETE" if complete else "INCOMPLETE", coverage=coverage, policy_sha256=policy_sha, attributes=attrs)


def validate_session_terminal_v2(terminal: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized = validate_manifest_result(terminal)
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    if normalized["manifest_type"] != SESSION_TERMINAL_MANIFEST_TYPE or normalized["coverage"] is None:
        raise IngestionV2Error("not a v3 session terminal manifest")
    attrs = _mapping(normalized["attributes"], "terminal attributes")
    required = {"analysis", "completion_status", "terminal_cause", "requested_interval", "terminal_at_utc", "terminal_monotonic_ns", "symbol_states", "telemetry", "readiness_manifest_sha256", "readiness_panel_status", "panel_matches_terminal_symbols", "policy"}
    if set(attrs) != required or attrs.get("analysis") != "session_terminal_v3":
        raise IngestionV2Error("session terminal attributes have unsupported shape")
    policy, policy_sha = _validate_readiness_policy(_mapping(attrs["policy"], "terminal policy"))
    if policy_sha != normalized["policy_sha256"]:
        raise IngestionV2Error("terminal policy hash mismatch")
    interval = _validated_interval(_mapping(attrs["requested_interval"], "terminal requested_interval"), "terminal requested_interval")
    if _validated_interval(_mapping(normalized["coverage"], "coverage")["interval"], "terminal coverage interval") != interval:
        raise IngestionV2Error("terminal coverage interval differs from requested interval")
    terminal_time = _parse_utc(attrs["terminal_at_utc"], "terminal_at_utc")
    terminal_mono = _nonnegative_int(attrs["terminal_monotonic_ns"], "terminal_monotonic_ns")
    _sha256(attrs["readiness_manifest_sha256"], "readiness_manifest_sha256")
    if terminal_time < _parse_utc(interval["end_utc"], "requested_interval.end_utc"):
        raise IngestionV2Error("terminal_at_utc precedes the requested interval end")
    states = _list(attrs["symbol_states"], "symbol_states")
    normalized_states: list[dict[str, Any]] = []
    for state in states:
        emitted = _mapping(state, "symbol_state")
        emitted_keys = {"symbol", "venue_symbol", "last_receipt_monotonic_ns", "last_receipt_at_utc", "connection_epoch", "feed_silence_events", "idle_seconds_at_terminal", "subscription_ack", "snapshot", "depth", "trade", "liveness"}
        if set(emitted) != emitted_keys:
            raise IngestionV2Error("terminal symbol_state has unsupported shape")
        rebuilt, _ = _normalize_terminal_state(
            {
                "symbol": emitted["symbol"],
                "venue_symbol": emitted["venue_symbol"],
                "subscription_acknowledged": emitted["subscription_ack"],
                "snapshot_observed": emitted["snapshot"],
                "depth_observed": emitted["depth"],
                "trade_observed": emitted["trade"],
                "last_receipt_monotonic_ns": emitted["last_receipt_monotonic_ns"],
                "last_receipt_at_utc": emitted["last_receipt_at_utc"],
                "connection_epoch": emitted["connection_epoch"],
                "feed_silence_events": emitted["feed_silence_events"],
            },
            terminal_monotonic_ns=terminal_mono,
            terminal_at_utc=terminal_time,
            policy=policy,
        )
        if emitted != rebuilt:
            raise IngestionV2Error("terminal symbol_state liveness facts do not recompute")
        normalized_states.append(rebuilt)
    if normalized_states != sorted(normalized_states, key=lambda item: item["symbol"]):
        raise IngestionV2Error("terminal symbol_states must be sorted")
    telemetry = _mapping(attrs["telemetry"], "telemetry")
    symbols = [state["symbol"] for state in normalized_states]
    if not symbols or len(symbols) != len(set(symbols)):
        raise IngestionV2Error("terminal symbol_states must be nonempty and unique")
    expected_coverage = build_coverage_result(
        "ingestion.capture_terminal", interval,
        [{"observation_id": f"{state['symbol']}:{kind}",
          "observation": observed_value(1.0) if state[kind] else missing_value("symbol_capture_contract_not_satisfied")}
         for state in normalized_states
         for kind in ("subscription_ack", "snapshot", "depth", "trade", "liveness")],
    )
    if normalized["coverage"] != expected_coverage:
        raise IngestionV2Error("terminal coverage does not recompute from symbol liveness/readiness")
    overflow = _nonnegative_int(telemetry.get("overflow_count"), "telemetry.overflow_count")
    open_barriers = _nonnegative_int(telemetry.get("open_recovery_barrier_count", 0), "telemetry.open_recovery_barrier_count")
    coverage = validate_coverage_result(normalized["coverage"])
    claims_complete = attrs["completion_status"] == "complete"
    expected_complete = coverage["status"] == "COMPLETE" and attrs["readiness_panel_status"] == "complete" and attrs["panel_matches_terminal_symbols"] is True and overflow == 0 and open_barriers == 0 and attrs["terminal_cause"] == "REQUESTED_INTERVAL_COMPLETE"
    if claims_complete != expected_complete or normalized["outcome"] != ("COMPLETE" if expected_complete else "INCOMPLETE"):
        raise IngestionV2Error("terminal completion status does not fail closed")
    if attrs["completion_status"] not in {"complete", "degraded", "failed"}:
        raise IngestionV2Error("terminal completion_status is unsupported")
    return normalized


def capture_pair_input_v2(terminal: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact non-authoritative terminal facts a capture-pair consumer needs.

    Stage 02 must still validate this terminal and bind raw/features identities;
    this helper deliberately does not manufacture a capture pair or replay claim.
    """

    normalized = validate_session_terminal_v2(terminal)
    attrs = normalized["attributes"]
    return {"schema": "orderflow_edge_lab.capture_pair_input.v2", "session_terminal_manifest_sha256": normalized["manifest_sha256"], "source_set": normalized["source_set"], "completion_status": attrs["completion_status"], "coverage_status": normalized["coverage"]["status"], "terminal_cause": attrs["terminal_cause"], "non_authority_claims": non_authority_claims()}


def legacy_terminal_status_v2(schema_version: object) -> dict[str, Any]:
    """Label v1/v2 capture records as integrity-only legacy artifacts, never complete."""

    if schema_version not in {1, 2, "1", "2"}:
        raise IngestionV2Error("legacy terminal classifier applies only to schema v1/v2")
    return {"schema": "orderflow_edge_lab.legacy_capture_terminal_status.v2", "legacy_schema_version": int(schema_version), "terminal_status": "unknown_legacy", "completion_status": "unavailable", "aggregation_eligible": False, "non_authority_claims": non_authority_claims()}


def _normalize_historical_pages(raw_pages: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    page_ids: set[str] = set()
    for item in raw_pages:
        page = _mapping(item, "raw_pages item")
        required = {"page_id", "source_id", "raw_path", "request", "page_status"}
        if set(page) != required:
            raise IngestionV2Error("raw_pages item has unsupported shape")
        page_id = _string(page["page_id"], "raw_pages.page_id")
        if page_id in page_ids:
            raise IngestionV2Error("raw_pages.page_id must be unique")
        page_ids.add(page_id)
        source_id = _string(page["source_id"], "raw_pages.source_id")
        request = _mapping(page["request"], "raw_pages.request")
        request_required = {"requested_url", "resolved_url", "cursor", "retrieved_at_utc", "retrieval_monotonic_ns", "http_status", "retry_outcome", "parser_schema"}
        if set(request) != request_required:
            raise IngestionV2Error("raw page request ledger has unsupported shape")
        try:
            identity = build_file_identity(Path(_string(page["raw_path"], "raw_pages.raw_path")), logical_name=source_id)
            source = build_source_record(source_id, identity)
        except ContractValidationError as exc:
            raise IngestionV2Error(str(exc)) from exc
        status = _string(page["page_status"], "raw_pages.page_status")
        if status not in {"SUCCESS", "EARLY_EXHAUSTION", "MAX_PAGES", "TRANSPORT_FAILURE", "HTTP_FAILURE", "SCHEMA_FAILURE"}:
            raise IngestionV2Error("raw_pages.page_status is unsupported")
        ledger.append({"page_id": page_id, "source_id": source_id, "identity": identity, "request": {"requested_url": _safe_url(request["requested_url"], "requested_url"), "resolved_url": _safe_url(request["resolved_url"], "resolved_url"), "cursor": _json_copy(request["cursor"], "cursor"), "retrieved_at_utc": _utc_text(_parse_utc(request["retrieved_at_utc"], "retrieved_at_utc")), "retrieval_monotonic_ns": _nonnegative_int(request["retrieval_monotonic_ns"], "retrieval_monotonic_ns"), "http_status": _positive_int(request["http_status"], "http_status"), "retry_outcome": _string(request["retry_outcome"], "retry_outcome"), "parser_schema": _string(request["parser_schema"], "parser_schema")}, "page_status": status})
        sources.append(source)
    if not ledger:
        raise IngestionV2Error("raw_pages must be nonempty; a manifest cannot invent raw sources")
    if len({item["source_id"] for item in sources}) != len(sources):
        raise IngestionV2Error("raw page source_id values must be unique")
    ledger.sort(key=lambda item: item["page_id"])
    return ledger, _build_source_set(sources, "raw pages")


def _expected_grid(interval: Mapping[str, Any], step_seconds: int) -> list[str]:
    start = _parse_utc(interval["start_utc"], "requested_interval.start_utc")
    end = _parse_utc(interval["end_utc"], "requested_interval.end_utc")
    span_seconds = (end - start).total_seconds()
    if span_seconds % step_seconds != 0:
        raise IngestionV2Error("requested interval must divide exactly into grid_step_seconds")
    count = int(span_seconds // step_seconds)
    if count < 1:
        raise IngestionV2Error("expected grid cannot be empty")
    return [_utc_text(start + index * (end - start) / count) for index in range(count)]


def build_historical_acquisition_manifest_v2(
    *,
    provider: str,
    instrument: str,
    acquisition_kind: str,
    requested_interval: Mapping[str, Any],
    grid_step_seconds: int,
    raw_pages: Sequence[Mapping[str, Any]],
    observed_rows: Sequence[Mapping[str, Any]],
    rejected_rows: Sequence[Mapping[str, Any]],
    acquisition_policy: Mapping[str, Any],
    diagnostic_only: bool,
) -> dict[str, Any]:
    """Build a provenance-bearing expected-grid manifest from locally retained pages.

    ``raw_pages`` must point to exclusive prospective raw artifacts already on
    local disk.  The resulting portable source set binds their current bytes but
    intentionally does not claim they are durably retained externally.  Rows
    rejected by a parser are retained in ``rejected_rows`` with page/row
    references; they cannot silently disappear from a complete result.
    """

    policy, policy_sha = _validate_historical_policy(acquisition_policy)
    if type(diagnostic_only) is not bool:
        raise IngestionV2Error("diagnostic_only must be boolean")
    if diagnostic_only and not policy["allow_diagnostic_only"]:
        raise IngestionV2Error("caller policy does not allow a diagnostics-only partial result")
    kind = _string(acquisition_kind, "acquisition_kind")
    if kind not in {"CANDLE", "FUNDING_SETTLEMENT"}:
        raise IngestionV2Error("acquisition_kind must be CANDLE or FUNDING_SETTLEMENT")
    interval = _validated_interval(requested_interval, "requested_interval")
    step = _positive_int(grid_step_seconds, "grid_step_seconds")
    expected = _expected_grid(interval, step)
    ledger, source_set = _normalize_historical_pages(raw_pages)
    pages = {page["page_id"] for page in ledger}
    observed_by_timestamp: dict[str, float] = {}
    accepted_rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for item in observed_rows:
        row = _mapping(item, "observed_rows item")
        required = {"timestamp_utc", "value", "page_id", "row_index", "confirmed"}
        if set(row) != required:
            raise IngestionV2Error("observed_rows item has unsupported shape")
        page_id = _string(row["page_id"], "observed_rows.page_id")
        if page_id not in pages:
            raise IngestionV2Error("observed row references an unknown raw page")
        timestamp = _utc_text(_parse_utc(row["timestamp_utc"], "observed_rows.timestamp_utc"))
        row_index = _nonnegative_int(row["row_index"], "observed_rows.row_index")
        value = _finite_number(row["value"], "observed_rows.value")
        if type(row["confirmed"]) is not bool:
            raise IngestionV2Error("observed_rows.confirmed must be boolean")
        if timestamp not in expected:
            issues.append({"code": "OFF_GRID_TIMESTAMP", "timestamp_utc": timestamp, "page_id": page_id, "row_index": row_index})
            continue
        if timestamp in observed_by_timestamp:
            issues.append({"code": "DUPLICATE_TIMESTAMP", "timestamp_utc": timestamp, "page_id": page_id, "row_index": row_index})
            continue
        if not row["confirmed"]:
            issues.append({"code": "UNCONFIRMED_ROW", "timestamp_utc": timestamp, "page_id": page_id, "row_index": row_index})
            continue
        observed_by_timestamp[timestamp] = value
        accepted_rows.append({"timestamp_utc": timestamp, "value": value, "page_id": page_id, "row_index": row_index, "confirmed": True})
    rejection_records: list[dict[str, Any]] = []
    seen_rejections: set[tuple[str, int]] = set()
    for item in rejected_rows:
        row = _mapping(item, "rejected_rows item")
        if set(row) != {"page_id", "row_index", "reason", "raw_row"}:
            raise IngestionV2Error("rejected_rows item has unsupported shape")
        page_id = _string(row["page_id"], "rejected_rows.page_id")
        if page_id not in pages:
            raise IngestionV2Error("rejected row references an unknown raw page")
        key = (page_id, _nonnegative_int(row["row_index"], "rejected_rows.row_index"))
        if key in seen_rejections:
            raise IngestionV2Error("rejected row page/index references must be unique")
        seen_rejections.add(key)
        rejection_records.append({"page_id": page_id, "row_index": key[1], "reason": _string(row["reason"], "rejected_rows.reason"), "raw_row": _json_copy(row["raw_row"], "rejected_rows.raw_row")})
    rejection_records.sort(key=lambda item: (item["page_id"], item["row_index"]))
    for page in ledger:
        if page["page_status"] != "SUCCESS":
            issues.append({"code": page["page_status"], "page_id": page["page_id"]})
    try:
        coverage = build_coverage_result(
            "ingestion.funding_settlement_grid" if kind == "FUNDING_SETTLEMENT" else "ingestion.candle_grid",
            interval,
            _coverage_observations(expected, observed_by_timestamp, "expected_grid_observation_missing"),
        )
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    issues.sort(key=lambda item: (item["code"], item.get("timestamp_utc", ""), item.get("page_id", ""), item.get("row_index", -1)))
    valid_complete = coverage["status"] == "COMPLETE" and not issues and not rejection_records
    outcome = "COMPLETE" if valid_complete else ("DIAGNOSTIC_ONLY" if diagnostic_only else "INCOMPLETE")
    attrs = {
        "analysis": "historical_acquisition_v2",
        "provider": _string(provider, "provider"),
        "instrument": _string(instrument, "instrument").upper(),
        "acquisition_kind": kind,
        "requested_interval": interval,
        "grid_step_seconds": step,
        "expected_grid_utc": expected,
        "observed_grid_utc": sorted(observed_by_timestamp),
        "accepted_rows": sorted(accepted_rows, key=lambda item: item["timestamp_utc"]),
        "page_ledger": ledger,
        "rejected_rows": rejection_records,
        "validation_issues": issues,
        "diagnostic_only": diagnostic_only,
        "policy": policy,
    }
    return _manifest_or_error(HISTORICAL_MANIFEST_TYPE, source_set, outcome, coverage=coverage, policy_sha256=policy_sha, attributes=attrs)


def validate_acquisition_manifest_v2(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate source provenance, raw-row retention, and expected-grid coverage."""

    try:
        normalized = validate_manifest_result(manifest)
    except ContractValidationError as exc:
        raise IngestionV2Error(str(exc)) from exc
    if normalized["manifest_type"] != HISTORICAL_MANIFEST_TYPE or normalized["coverage"] is None:
        raise IngestionV2Error("not a historical acquisition manifest")
    attrs = _mapping(normalized["attributes"], "acquisition attributes")
    required = {"analysis", "provider", "instrument", "acquisition_kind", "requested_interval", "grid_step_seconds", "expected_grid_utc", "observed_grid_utc", "accepted_rows", "page_ledger", "rejected_rows", "validation_issues", "diagnostic_only", "policy"}
    if set(attrs) != required or attrs.get("analysis") != "historical_acquisition_v2":
        raise IngestionV2Error("historical acquisition attributes have unsupported shape")
    policy, policy_sha = _validate_historical_policy(_mapping(attrs["policy"], "acquisition policy"))
    if policy_sha != normalized["policy_sha256"]:
        raise IngestionV2Error("historical acquisition policy hash mismatch")
    if type(attrs["diagnostic_only"]) is not bool:
        raise IngestionV2Error("diagnostic_only must be boolean")
    if attrs["diagnostic_only"] and not policy["allow_diagnostic_only"]:
        raise IngestionV2Error("manifest uses diagnostics-only mode not permitted by its policy")
    kind = _string(attrs["acquisition_kind"], "acquisition_kind")
    if kind not in {"CANDLE", "FUNDING_SETTLEMENT"}:
        raise IngestionV2Error("acquisition_kind is unsupported")
    interval = _validated_interval(_mapping(attrs["requested_interval"], "requested_interval"), "requested_interval")
    step = _positive_int(attrs["grid_step_seconds"], "grid_step_seconds")
    expected = _expected_grid(interval, step)
    supplied_expected = [_utc_text(_parse_utc(item, "expected_grid_utc item")) for item in _list(attrs["expected_grid_utc"], "expected_grid_utc")]
    if supplied_expected != expected:
        raise IngestionV2Error("expected grid does not match requested interval/cadence")
    ledger = _list(attrs["page_ledger"], "page_ledger")
    if not ledger:
        raise IngestionV2Error("historical manifest has no raw-page ledger")
    page_sources: list[dict[str, Any]] = []
    page_ids: set[str] = set()
    for item in ledger:
        row = _mapping(item, "page_ledger item")
        if set(row) != {"page_id", "source_id", "identity", "request", "page_status"}:
            raise IngestionV2Error("page ledger item has unsupported shape")
        page_id = _string(row["page_id"], "page_id")
        if page_id in page_ids:
            raise IngestionV2Error("page ledger page IDs must be unique")
        page_ids.add(page_id)
        identity = _mapping(row["identity"], "page identity")
        try:
            page_sources.append(build_source_record(_string(row["source_id"], "source_id"), validate_file_identity(identity)))
        except ContractValidationError as exc:
            raise IngestionV2Error(str(exc)) from exc
        request = _mapping(row["request"], "page request")
        if set(request) != {"requested_url", "resolved_url", "cursor", "retrieved_at_utc", "retrieval_monotonic_ns", "http_status", "retry_outcome", "parser_schema"}:
            raise IngestionV2Error("page request has unsupported shape")
        _safe_url(request["requested_url"], "requested_url")
        _safe_url(request["resolved_url"], "resolved_url")
        _parse_utc(request["retrieved_at_utc"], "retrieved_at_utc")
        _nonnegative_int(request["retrieval_monotonic_ns"], "retrieval_monotonic_ns")
        _positive_int(request["http_status"], "http_status")
        _string(request["retry_outcome"], "retry_outcome")
        _string(request["parser_schema"], "parser_schema")
        if row["page_status"] not in {"SUCCESS", "EARLY_EXHAUSTION", "MAX_PAGES", "TRANSPORT_FAILURE", "HTTP_FAILURE", "SCHEMA_FAILURE"}:
            raise IngestionV2Error("page status unsupported")
    ledger_ids = [item["page_id"] for item in ledger]
    if ledger_ids != sorted(ledger_ids):
        raise IngestionV2Error("page ledger must be sorted by page_id")
    if _build_source_set(page_sources, "page sources") != normalized["source_set"]:
        raise IngestionV2Error("historical source_set must bind exactly the raw-page identities")
    observed_rows = _list(attrs["accepted_rows"], "accepted_rows")
    observed: dict[str, float] = {}
    for item in observed_rows:
        row = _mapping(item, "accepted row")
        if set(row) != {"timestamp_utc", "value", "page_id", "row_index", "confirmed"}:
            raise IngestionV2Error("accepted row has unsupported shape")
        timestamp = _utc_text(_parse_utc(row["timestamp_utc"], "accepted row timestamp"))
        if timestamp not in expected or timestamp in observed or _string(row["page_id"], "accepted row page_id") not in page_ids or row["confirmed"] is not True:
            raise IngestionV2Error("accepted rows are not a unique confirmed expected-grid set")
        _nonnegative_int(row["row_index"], "accepted row row_index")
        observed[timestamp] = _finite_number(row["value"], "accepted row value")
    if [item["timestamp_utc"] for item in observed_rows] != sorted(observed):
        raise IngestionV2Error("accepted rows must be sorted by timestamp")
    supplied_observed = [_utc_text(_parse_utc(item, "observed_grid_utc item")) for item in _list(attrs["observed_grid_utc"], "observed_grid_utc")]
    if supplied_observed != sorted(observed):
        raise IngestionV2Error("observed grid must equal accepted raw rows")
    rejections = _list(attrs["rejected_rows"], "rejected_rows")
    rejection_keys: list[tuple[str, int]] = []
    for item in rejections:
        row = _mapping(item, "rejected row")
        if set(row) != {"page_id", "row_index", "reason", "raw_row"}:
            raise IngestionV2Error("rejected row has unsupported shape")
        page_id = _string(row["page_id"], "rejected page_id")
        if page_id not in page_ids:
            raise IngestionV2Error("rejected row refers to unknown page")
        key = (page_id, _nonnegative_int(row["row_index"], "rejected row index"))
        rejection_keys.append(key)
        _string(row["reason"], "rejected reason")
        _json_copy(row["raw_row"], "rejected raw_row")
    if rejection_keys != sorted(rejection_keys) or len(set(rejection_keys)) != len(rejection_keys):
        raise IngestionV2Error("rejected rows must be uniquely sorted page/index records")
    issues = _list(attrs["validation_issues"], "validation_issues")
    normalized_issues = [_json_copy(_mapping(item, "validation issue"), "validation issue") for item in issues]
    if normalized_issues != sorted(normalized_issues, key=lambda item: (item["code"], item.get("timestamp_utc", ""), item.get("page_id", ""), item.get("row_index", -1))):
        raise IngestionV2Error("validation issues must be canonically sorted")
    coverage = validate_coverage_result(normalized["coverage"])
    if coverage["coverage_kind"] != ("ingestion.funding_settlement_grid" if kind == "FUNDING_SETTLEMENT" else "ingestion.candle_grid") or coverage["interval"] != interval:
        raise IngestionV2Error("coverage kind or interval does not match acquisition attributes")
    expected_coverage = build_coverage_result(coverage["coverage_kind"], interval, _coverage_observations(expected, observed, "expected_grid_observation_missing"))
    if coverage != expected_coverage:
        raise IngestionV2Error("coverage does not match preserved requested-vs-observed grid")
    complete = coverage["status"] == "COMPLETE" and not normalized_issues and not rejections and all(item["page_status"] == "SUCCESS" for item in ledger)
    expected_outcome = "COMPLETE" if complete else ("DIAGNOSTIC_ONLY" if attrs["diagnostic_only"] else "INCOMPLETE")
    if normalized["outcome"] != expected_outcome:
        raise IngestionV2Error("historical acquisition outcome does not fail closed")
    return normalized


def funding_economics_admissibility_v2(
    acquisition_manifest: Mapping[str, Any],
    *,
    required_settlement_ids: Sequence[str],
) -> dict[str, Any]:
    """Fail closed before funding-inclusive economics; observed zero remains observed."""

    manifest = validate_acquisition_manifest_v2(acquisition_manifest)
    attrs = manifest["attributes"]
    if attrs["acquisition_kind"] != "FUNDING_SETTLEMENT":
        raise IngestionV2Error("funding admissibility requires a funding settlement acquisition manifest")
    ids = [_utc_text(_parse_utc(item, "required_settlement_ids item")) for item in required_settlement_ids]
    if not ids or len(ids) != len(set(ids)):
        raise IngestionV2Error("required_settlement_ids must be a nonempty unique caller-declared schedule")
    coverage = manifest["coverage"]
    values = {item["observation_id"]: item["observation"] for item in coverage["observations"]}
    missing = [item for item in ids if item not in values or values[item]["availability"] != "OBSERVED"]
    admissible = manifest["outcome"] == "COMPLETE" and not missing
    funding_sum = None if not admissible else float(sum(float(values[item]["value"]) for item in ids))
    return {"schema": "orderflow_edge_lab.funding_economics_admissibility.v2", "acquisition_manifest_sha256": manifest["manifest_sha256"], "required_settlement_ids": sorted(ids), "missing_settlement_ids": sorted(missing), "funding_economics_admissible": admissible, "funding_rate_sum": funding_sum, "status": "ADMISSIBLE" if admissible else "INADMISSIBLE_DATA_GAP", "non_authority_claims": non_authority_claims()}


def _classify_rest_failure(exc: BaseException, retry_http_statuses: set[int]) -> tuple[str, int | None, bool]:
    if isinstance(exc, HTTPError):
        status = int(exc.code)
        return "HTTP", status, status in retry_http_statuses
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError, OSError, URLError)):
        return "TRANSPORT", None, True
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, IngestionV2Error, ContractValidationError, ValueError, TypeError)):
        return "SCHEMA_OR_CONFIG", None, False
    return "UNEXPECTED", None, False


def execute_rest_attempts_v2(
    operation: str,
    fetch: Callable[[], Any],
    payload_validator: Callable[[Any], Any],
    *,
    retry_policy: Mapping[str, Any],
    connection_epoch: int,
    event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    monotonic_clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Apply a caller-declared bounded retry policy and emit sanitized attempts.

    The callable injection is intentional: callers may connect it to a real
    recorder later, while tests and the included CLI remain entirely offline.
    No response body or credential-bearing URL is put in an audit record.
    """

    policy, policy_sha = _validate_retry_policy(retry_policy)
    op = _string(operation, "operation")
    epoch = _nonnegative_int(connection_epoch, "connection_epoch")
    attempts: list[dict[str, Any]] = []
    retry_statuses = set(policy["retry_http_statuses"])
    for attempt in range(1, int(policy["max_attempts"]) + 1):
        started = _nonnegative_int(monotonic_clock_ns(), "monotonic clock")
        try:
            payload = fetch()
            validated = payload_validator(payload)
        except Exception as exc:  # normalized below; no provider body is serialized
            ended = _nonnegative_int(monotonic_clock_ns(), "monotonic clock")
            if ended < started:
                raise IngestionV2Error("monotonic clock moved backwards during REST attempt")
            category, http_status, retryable = _classify_rest_failure(exc, retry_statuses)
            can_retry = retryable and attempt < int(policy["max_attempts"])
            decision = "RETRY" if can_retry else "FAIL"
            record = {"schema": "orderflow_edge_lab.rest_attempt.v2", "record_type": "rest_attempt", "operation": op, "connection_epoch": epoch, "attempt": attempt, "started_monotonic_ns": started, "elapsed_monotonic_ns": ended - started, "failure_category": category, "http_status": http_status, "decision": decision, "backoff_seconds": float(policy["base_backoff_seconds"]) * (2 ** (attempt - 1)) if can_retry else 0.0, "error_type": type(exc).__name__, "retry_policy_sha256": policy_sha}
            attempts.append(record)
            if event_sink is not None:
                event_sink(dict(record))
            if can_retry:
                sleep(record["backoff_seconds"])
                continue
            raise RestAttemptsExhaustedV2(f"{op} did not obtain a valid payload after {attempt} bounded attempt(s): {category}", attempts) from exc
        ended = _nonnegative_int(monotonic_clock_ns(), "monotonic clock")
        if ended < started:
            raise IngestionV2Error("monotonic clock moved backwards during REST attempt")
        record = {"schema": "orderflow_edge_lab.rest_attempt.v2", "record_type": "rest_attempt", "operation": op, "connection_epoch": epoch, "attempt": attempt, "started_monotonic_ns": started, "elapsed_monotonic_ns": ended - started, "failure_category": None, "http_status": None, "decision": "SUCCESS", "backoff_seconds": 0.0, "error_type": None, "retry_policy_sha256": policy_sha}
        attempts.append(record)
        if event_sink is not None:
            event_sink(dict(record))
        return {"schema": "orderflow_edge_lab.rest_attempt_result.v2", "operation": op, "connection_epoch": epoch, "payload": validated, "attempts": attempts, "status": "SUCCESS", "retry_policy_sha256": policy_sha, "non_authority_claims": non_authority_claims()}
    raise AssertionError("unreachable bounded attempt loop")


class BoundedOrderedCaptureV2:
    """Raw-first bounded receipt queue with ordered processing and honest telemetry.

    Call ``receive`` as soon as a frame arrives, even while a separate worker is
    resolving a snapshot or recovery barrier.  Each frame is passed to the raw
    sink before it can be dropped from the bounded processor queue.  Overflow is
    recorded and permanently disqualifies a complete terminal.
    """

    def __init__(
        self,
        *,
        capacity: int,
        required_symbols: Sequence[str],
        raw_event_sink: Callable[[Mapping[str, Any]], None],
        clock_comparability: Mapping[str, Any] | None = None,
    ) -> None:
        self.capacity = _positive_int(capacity, "capacity")
        self.required_symbols = {_string(item, "required_symbols item").upper() for item in required_symbols}
        if not self.required_symbols:
            raise IngestionV2Error("required_symbols must be nonempty")
        if not callable(raw_event_sink):
            raise IngestionV2Error("raw_event_sink must be callable")
        self._sink = raw_event_sink
        self._queue: deque[_QueuedFrame] = deque()
        self._last_received_mono: dict[str, int] = {}
        self._sequence = 0
        self._last_receiver_mono: int | None = None
        self._last_processor_mono: int | None = None
        self._high_water = 0
        self._overflow_count = 0
        self._processed = 0
        self._queue_age_max_ns = 0
        self._processing_delay_max_ns = 0
        self._queue_age_samples: deque[int] = deque(maxlen=1024)
        self._rest_durations: deque[dict[str, Any]] = deque(maxlen=256)
        self._barriers: list[dict[str, Any]] = []
        self._open_barriers: dict[str, int] = {}
        self._clock_status = "unavailable"
        if clock_comparability is not None:
            declared = _mapping(clock_comparability, "clock_comparability")
            if set(declared) != {"status", "basis"} or declared["status"] != "CALLER_DECLARED_COMPARABLE":
                raise IngestionV2Error("clock_comparability may only be a caller-declared comparable basis")
            self._clock_status = "caller_declared_comparable"

    def _write(self, event: Mapping[str, Any]) -> None:
        # Validate before emitting so raw event sinks cannot receive an ambiguous
        # NaN/bytes/datetime record that later defeats canonical evidence tooling.
        self._sink(_json_copy(event, "raw capture event"))

    def receive(self, payload: Mapping[str, Any], *, received_at_utc: str, received_monotonic_ns: int) -> bool:
        """Durably record one arrival then enqueue it if capacity remains.

        Returns false on overflow.  The raw frame was still handed to the sink;
        callers must finalize incomplete rather than pretending the dropped
        processor item was a continuous capture.
        """

        frame = _json_copy(_mapping(payload, "frame payload"), "frame payload")
        received = _nonnegative_int(received_monotonic_ns, "received_monotonic_ns")
        if self._last_receiver_mono is not None and received < self._last_receiver_mono:
            raise IngestionV2Error("receiver monotonic timestamps must not move backwards")
        received_utc = _utc_text(_parse_utc(received_at_utc, "received_at_utc"))
        self._last_receiver_mono = received
        self._sequence += 1
        symbol = frame.get("symbol")
        normalized_symbol = _string(symbol, "frame payload.symbol").upper() if symbol is not None else None
        if normalized_symbol in self.required_symbols:
            self._last_received_mono[normalized_symbol] = received
        raw_event = {"schema": "orderflow_edge_lab.capture_receipt.v2", "record_type": "raw_frame_received", "sequence": self._sequence, "received_at_utc": received_utc, "received_monotonic_ns": received, "symbol": normalized_symbol, "payload": frame}
        self._write(raw_event)
        if len(self._queue) >= self.capacity:
            self._overflow_count += 1
            self._write({"schema": "orderflow_edge_lab.capture_receipt.v2", "record_type": "queue_overflow", "sequence": self._sequence, "received_at_utc": received_utc, "received_monotonic_ns": received, "capacity": self.capacity, "queue_depth": len(self._queue), "overflow_count": self._overflow_count})
            return False
        self._queue.append(_QueuedFrame(self._sequence, frame, received_utc, received))
        self._high_water = max(self._high_water, len(self._queue))
        return True

    def begin_recovery_barrier(self, barrier_id: str, *, started_monotonic_ns: int, kind: str) -> None:
        ident = _string(barrier_id, "barrier_id")
        if ident in self._open_barriers:
            raise IngestionV2Error("recovery barrier is already open")
        started = _nonnegative_int(started_monotonic_ns, "started_monotonic_ns")
        self._open_barriers[ident] = started
        self._write({"schema": "orderflow_edge_lab.capture_barrier.v2", "record_type": "recovery_barrier_started", "barrier_id": ident, "kind": _string(kind, "kind"), "started_monotonic_ns": started, "queue_depth": len(self._queue)})

    def end_recovery_barrier(self, barrier_id: str, *, ended_monotonic_ns: int, outcome: str) -> None:
        ident = _string(barrier_id, "barrier_id")
        if ident not in self._open_barriers:
            raise IngestionV2Error("recovery barrier was not open")
        started = self._open_barriers.pop(ident)
        ended = _nonnegative_int(ended_monotonic_ns, "ended_monotonic_ns")
        if ended < started:
            raise IngestionV2Error("recovery barrier monotonic duration cannot be negative")
        record = {"barrier_id": ident, "started_monotonic_ns": started, "ended_monotonic_ns": ended, "duration_monotonic_ns": ended - started, "outcome": _string(outcome, "outcome"), "queue_depth_at_end": len(self._queue)}
        self._barriers.append(record)
        self._write({"schema": "orderflow_edge_lab.capture_barrier.v2", "record_type": "recovery_barrier_ended", **record})

    def record_rest_duration(self, operation: str, *, started_monotonic_ns: int, ended_monotonic_ns: int) -> None:
        """Record a bounded, clock-safe REST duration without serializing a response body."""

        started = _nonnegative_int(started_monotonic_ns, "started_monotonic_ns")
        ended = _nonnegative_int(ended_monotonic_ns, "ended_monotonic_ns")
        if ended < started:
            raise IngestionV2Error("REST monotonic duration cannot be negative")
        record = {"operation": _string(operation, "operation"), "started_monotonic_ns": started, "ended_monotonic_ns": ended, "duration_monotonic_ns": ended - started}
        self._rest_durations.append(record)
        self._write({"schema": "orderflow_edge_lab.capture_rest_timing.v2", "record_type": "rest_duration", **record})

    def process_next(self, processor: Callable[[Mapping[str, Any]], None], *, processed_monotonic_ns: int) -> bool:
        """Process exactly one queued frame in receipt sequence order."""

        if not callable(processor):
            raise IngestionV2Error("processor must be callable")
        processed = _nonnegative_int(processed_monotonic_ns, "processed_monotonic_ns")
        if self._last_processor_mono is not None and processed < self._last_processor_mono:
            raise IngestionV2Error("processor monotonic timestamps must not move backwards")
        self._last_processor_mono = processed
        if not self._queue:
            return False
        item = self._queue.popleft()
        if processed < item.received_monotonic_ns:
            raise IngestionV2Error("processing cannot precede receipt on a monotonic clock")
        age = processed - item.received_monotonic_ns
        self._queue_age_max_ns = max(self._queue_age_max_ns, age)
        self._processing_delay_max_ns = max(self._processing_delay_max_ns, age)
        self._queue_age_samples.append(age)
        processor(dict(item.payload))
        self._processed += 1
        self._write({"schema": "orderflow_edge_lab.capture_processing.v2", "record_type": "frame_processed", "sequence": item.sequence, "received_monotonic_ns": item.received_monotonic_ns, "processed_monotonic_ns": processed, "processing_delay_monotonic_ns": age, "queue_depth_after": len(self._queue)})
        return True

    def check_liveness(self, *, now_monotonic_ns: int, max_symbol_idle_seconds: float) -> list[dict[str, Any]]:
        """Emit deterministic per-symbol silence facts without declaring a completion."""

        now = _nonnegative_int(now_monotonic_ns, "now_monotonic_ns")
        limit = _finite_number(max_symbol_idle_seconds, "max_symbol_idle_seconds", positive=True)
        events: list[dict[str, Any]] = []
        for symbol in sorted(self.required_symbols):
            last = self._last_received_mono.get(symbol)
            idle = None if last is None else (now - last) / 1_000_000_000.0
            if last is None or idle > limit:
                event = {"schema": "orderflow_edge_lab.feed_silence.v2", "record_type": "feed_silence", "symbol": symbol, "last_receipt_monotonic_ns": last, "checked_monotonic_ns": now, "max_symbol_idle_seconds": limit, "idle_seconds": idle, "connection_epoch": None}
                self._write(event)
                events.append(event)
        return events

    def telemetry(self) -> dict[str, Any]:
        """Return measured queue/recovery facts, never a fabricated exchange latency."""

        samples = sorted(self._queue_age_samples)
        def percentile(fraction: float) -> int | None:
            if not samples:
                return None
            return samples[math.ceil(fraction * len(samples)) - 1]
        return {"schema": "orderflow_edge_lab.capture_telemetry.v2", "queue_capacity": self.capacity, "queue_depth": len(self._queue), "queue_high_water": self._high_water, "overflow_count": self._overflow_count, "processed_frame_count": self._processed, "received_frame_count": self._sequence, "queue_age_max_monotonic_ns": self._queue_age_max_ns, "queue_age_sample_count": len(samples), "queue_age_sample_capacity": self._queue_age_samples.maxlen, "queue_age_sample_percentiles_monotonic_ns": {"p50": percentile(0.50), "p95": percentile(0.95)}, "processing_delay_max_monotonic_ns": self._processing_delay_max_ns, "rest_duration_samples": list(self._rest_durations), "open_recovery_barrier_count": len(self._open_barriers), "recovery_barriers": list(self._barriers), "exchange_latency_status": self._clock_status, "exchange_latency_ns": None}

    async def receive_continuously(
        self,
        receive: Callable[[], Awaitable[Mapping[str, Any]]],
        *,
        should_stop: Callable[[], bool],
        utc_clock: Callable[[], str],
        monotonic_clock_ns: Callable[[], int] = time.monotonic_ns,
        max_receive_wait_seconds: float | None = None,
        max_symbol_idle_seconds: float | None = None,
    ) -> None:
        """Asynchronous receiver loop for a caller-owned offline/live transport adapter."""

        if (max_receive_wait_seconds is None) != (max_symbol_idle_seconds is None):
            raise IngestionV2Error("bounded receive wait and liveness policy must be supplied together")
        if max_receive_wait_seconds is not None:
            _finite_number(max_receive_wait_seconds, "max_receive_wait_seconds", positive=True)
            _finite_number(max_symbol_idle_seconds, "max_symbol_idle_seconds", positive=True)
        while not should_stop():
            try:
                payload = await receive() if max_receive_wait_seconds is None else await asyncio.wait_for(receive(), timeout=max_receive_wait_seconds)
            except asyncio.TimeoutError:
                if max_receive_wait_seconds is None:
                    raise
                self.check_liveness(now_monotonic_ns=monotonic_clock_ns(), max_symbol_idle_seconds=max_symbol_idle_seconds)
                continue
            self.receive(payload, received_at_utc=utc_clock(), received_monotonic_ns=monotonic_clock_ns())


def build_capture_simulation_v2(specification: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the bounded raw-first pipeline against caller-supplied offline frames."""

    spec = _mapping(specification, "capture simulation")
    required = {"capacity", "required_symbols", "frames"}
    if set(spec) != required:
        raise IngestionV2Error("capture simulation requires capacity, required_symbols, and frames")
    events: list[dict[str, Any]] = []
    pipeline = BoundedOrderedCaptureV2(capacity=spec["capacity"], required_symbols=_list(spec["required_symbols"], "required_symbols"), raw_event_sink=events.append)
    frames = _list(spec["frames"], "frames")
    for item in frames:
        row = _mapping(item, "capture simulation frame")
        if set(row) != {"payload", "received_at_utc", "received_monotonic_ns"}:
            raise IngestionV2Error("simulation frame has unsupported shape")
        pipeline.receive(_mapping(row["payload"], "simulation payload"), received_at_utc=_string(row["received_at_utc"], "received_at_utc"), received_monotonic_ns=_nonnegative_int(row["received_monotonic_ns"], "received_monotonic_ns"))
    processed: list[dict[str, Any]] = []
    now = max([_nonnegative_int(_mapping(item, "frame")["received_monotonic_ns"], "received_monotonic_ns") for item in frames], default=0)
    while pipeline.process_next(processed.append, processed_monotonic_ns=now):
        now += 1
    telemetry = pipeline.telemetry()
    return {"schema": "orderflow_edge_lab.capture_simulation_result.v2", "status": "INCOMPLETE_OVERFLOW" if telemetry["overflow_count"] else "PROCESSED", "processed_payloads": processed, "events": events, "telemetry": telemetry, "non_authority_claims": non_authority_claims()}

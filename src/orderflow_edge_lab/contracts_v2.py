"""Shared, opt-in v2 integrity contracts.

These contracts describe local bytes, declared source sets, missingness, UTC
interval membership, and structured completion results. They deliberately do
not establish provider authenticity, durable retention, engine calibration,
statistical validity, profitability, promotion authority, or live-trading
permission. Legacy modules do not import this module; successor paths opt in
explicitly.

The module also offers an offline ``python -m orderflow_edge_lab.contracts_v2``
CLI for validating canonical JSON, local file identity, and manifest results.
It performs no network, storage-service, scheduler, or order activity.
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
FILE_IDENTITY_SCHEMA = "orderflow_edge_lab.file_identity.v2"
FILE_VERIFICATION_SCHEMA = "orderflow_edge_lab.file_verification.v2"
SOURCE_SET_SCHEMA = "orderflow_edge_lab.canonical_source_set.v2"
UTC_INTERVAL_SCHEMA = "orderflow_edge_lab.utc_interval.v2"
COVERAGE_RESULT_SCHEMA = "orderflow_edge_lab.coverage_result.v2"
MANIFEST_RESULT_SCHEMA = "orderflow_edge_lab.manifest_result.v2"

CLOSED_OPEN = "CLOSED_OPEN"  # [start, end)
OPEN_CLOSED = "OPEN_CLOSED"  # (start, end]
_INTERVAL_CONVENTIONS = {CLOSED_OPEN, OPEN_CLOSED}
_MANIFEST_OUTCOMES = {"COMPLETE", "INCOMPLETE", "INVALID", "DIAGNOSTIC_ONLY"}
_HEX = frozenset("0123456789abcdef")


class ContractValidationError(ValueError):
    """Raised when a v2 contract is malformed, ambiguous, or internally inconsistent."""


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field} keys must be strings")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    present = set(value)
    if present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        parts: list[str] = []
        if missing:
            parts.append("missing=" + ",".join(missing))
        if extra:
            parts.append("extra=" + ",".join(extra))
        raise ContractValidationError(f"{field} has unsupported shape ({'; '.join(parts)})")


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a nonempty string")
    return value.strip()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX for char in value.lower()):
        raise ContractValidationError(f"{field} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _require_nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ContractValidationError(f"{field} must be a nonnegative integer")
    return value


def _validate_json(value: object, field: str = "value") -> None:
    """Reject non-JSON and nonfinite input before a canonical representation is hashed."""

    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) is int:
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{field} contains a nonfinite float")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{field}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"{field} has a non-string key")
            _validate_json(item, f"{field}.{key}")
        return
    raise ContractValidationError(f"{field} is not a JSON value")


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON bytes after rejecting ambiguous values.

    Only ordinary JSON values are accepted: objects with string keys, arrays,
    strings, booleans, null, finite integer values, and finite floats. Tuples,
    Decimal instances, bytes, datetimes, and NaN/Infinity are intentionally not
    coerced, because coercion would make a signed/hash-bound contract ambiguous.
    """

    _validate_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    """Return the SHA-256 of :func:`canonical_json_bytes`."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json_copy(value: object) -> Any:
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def sha256_file(path: str | Path) -> str:
    """Hash one exact local byte stream; this makes no retention or provenance claim."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_identity(path: str | Path, *, logical_name: str | None = None) -> dict[str, Any]:
    """Describe current local bytes with a content hash and byte count.

    ``logical_name`` is caller-declared and portable; an absolute filesystem path
    is deliberately not made part of the identity.
    """

    target = Path(path)
    if not target.is_file():
        raise ContractValidationError(f"file is not readable: {target}")
    result: dict[str, Any] = {
        "schema": FILE_IDENTITY_SCHEMA,
        "size_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }
    if logical_name is not None:
        result["logical_name"] = _require_nonempty_string(logical_name, "logical_name")
    return result


def validate_file_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a portable local-byte identity object."""

    raw = _require_mapping(identity, "file_identity")
    expected = {"schema", "size_bytes", "sha256"}
    if "logical_name" in raw:
        expected.add("logical_name")
    _require_exact_keys(raw, expected, "file_identity")
    if raw.get("schema") != FILE_IDENTITY_SCHEMA:
        raise ContractValidationError("file_identity schema is unsupported")
    normalized: dict[str, Any] = {
        "schema": FILE_IDENTITY_SCHEMA,
        "size_bytes": _require_nonnegative_int(raw.get("size_bytes"), "file_identity.size_bytes"),
        "sha256": _require_sha256(raw.get("sha256"), "file_identity.sha256"),
    }
    if "logical_name" in raw:
        normalized["logical_name"] = _require_nonempty_string(raw["logical_name"], "file_identity.logical_name")
    return normalized


def non_authority_claims() -> dict[str, bool]:
    """Return mandatory false claims for every generic v2 result.

    A successful local comparison is intentionally narrower than external
    authority, durable storage, provider coverage, calibrated economics, a
    strategy verdict, promotion, or trading permission.
    """

    return {
        "external_storage_verified": False,
        "provider_completeness_verified": False,
        "independent_engine_calibration_verified": False,
        "profitable_edge_established": False,
        "promotion_authorized": False,
        "live_order_transmission_supported": False,
    }


def validate_non_authority_claims(claims: Mapping[str, Any]) -> dict[str, bool]:
    """Require the exact non-authority claim set with every value set to false."""

    raw = _require_mapping(claims, "non_authority_claims")
    required = non_authority_claims()
    _require_exact_keys(raw, set(required), "non_authority_claims")
    for key in required:
        if raw[key] is not False:
            raise ContractValidationError(f"non_authority_claims.{key} must be false")
    return dict(required)


def verify_file_identity(path: str | Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Compare local bytes with an expected identity and return a non-authoritative result."""

    expected_identity = validate_file_identity(expected)
    target = Path(path)
    result: dict[str, Any] = {
        "schema": FILE_VERIFICATION_SCHEMA,
        "checked_path": str(target),
        "expected": expected_identity,
        "observed": None,
        "checks": {"exists": False, "size_bytes": False, "sha256": False},
        "status": "FILE_MISSING",
        "verification_scope": "local_bytes_only",
        "non_authority_claims": non_authority_claims(),
    }
    if not target.is_file():
        return result

    observed = build_file_identity(target, logical_name=expected_identity.get("logical_name"))
    checks = {
        "exists": True,
        "size_bytes": observed["size_bytes"] == expected_identity["size_bytes"],
        "sha256": observed["sha256"] == expected_identity["sha256"],
    }
    result["observed"] = observed
    result["checks"] = checks
    result["status"] = "VERIFIED_LOCAL_BYTES" if all(checks.values()) else "FILE_MISMATCH"
    return result


def build_source_record(source_id: str, identity: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a caller-declared immutable source identifier to a file identity."""

    normalized = validate_file_identity(identity)
    return {
        "source_id": _require_nonempty_string(source_id, "source_id"),
        "size_bytes": normalized["size_bytes"],
        "sha256": normalized["sha256"],
    }


def _validate_source_record(source: Mapping[str, Any]) -> dict[str, Any]:
    raw = _require_mapping(source, "source")
    _require_exact_keys(raw, {"source_id", "size_bytes", "sha256"}, "source")
    return {
        "source_id": _require_nonempty_string(raw.get("source_id"), "source.source_id"),
        "size_bytes": _require_nonnegative_int(raw.get("size_bytes"), "source.size_bytes"),
        "sha256": _require_sha256(raw.get("sha256"), "source.sha256"),
    }


def build_canonical_source_set(sources: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build an exact, order-independent source set for cross-artifact equality checks.

    A source set uses stable caller-declared ``source_id`` values plus byte size
    and digest. It intentionally excludes local filesystem paths, so materializing
    the same sealed bytes in a different directory does not change the set.
    """

    normalized = [_validate_source_record(source) for source in sources]
    if not normalized:
        raise ContractValidationError("source_set must contain at least one source")
    normalized.sort(key=lambda item: item["source_id"])
    ids = [item["source_id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ContractValidationError("source_set source_id values must be unique")
    unsigned = {"schema": SOURCE_SET_SCHEMA, "sources": normalized}
    return {**unsigned, "source_set_sha256": canonical_json_sha256(unsigned)}


def validate_canonical_source_set(source_set: Mapping[str, Any]) -> dict[str, Any]:
    """Validate digest, ordering, and exact source membership of a source set."""

    raw = _require_mapping(source_set, "source_set")
    _require_exact_keys(raw, {"schema", "sources", "source_set_sha256"}, "source_set")
    if raw.get("schema") != SOURCE_SET_SCHEMA:
        raise ContractValidationError("source_set schema is unsupported")
    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ContractValidationError("source_set.sources must be a nonempty array")
    normalized = [_validate_source_record(item) for item in sources]
    sorted_normalized = sorted(normalized, key=lambda item: item["source_id"])
    if normalized != sorted_normalized:
        raise ContractValidationError("source_set.sources must be sorted by source_id")
    ids = [item["source_id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ContractValidationError("source_set source_id values must be unique")
    unsigned = {"schema": SOURCE_SET_SCHEMA, "sources": normalized}
    expected = canonical_json_sha256(unsigned)
    if _require_sha256(raw.get("source_set_sha256"), "source_set.source_set_sha256") != expected:
        raise ContractValidationError("source_set_sha256 does not match canonical source membership")
    return {**unsigned, "source_set_sha256": expected}


def source_sets_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Return true only when two validated sets have identical canonical membership."""

    return validate_canonical_source_set(left)["source_set_sha256"] == validate_canonical_source_set(right)[
        "source_set_sha256"
    ]


def observed_value(value: int | float) -> dict[str, Any]:
    """Represent an observed finite numeric value, including an observed exact zero."""

    if type(value) is not int and not isinstance(value, float):
        raise ContractValidationError("observed value must be a finite numeric value")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError("observed value must be finite")
    return {"availability": "OBSERVED", "value": value, "reason": None}


def missing_value(reason: str) -> dict[str, Any]:
    """Represent an unavailable observation without replacing it with a numeric zero."""

    return {"availability": "MISSING", "value": None, "reason": _require_nonempty_string(reason, "missing reason")}


def validate_observation_value(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the explicit observed-versus-missing representation."""

    raw = _require_mapping(observation, "observation")
    _require_exact_keys(raw, {"availability", "value", "reason"}, "observation")
    availability = raw.get("availability")
    if availability == "OBSERVED":
        if raw.get("reason") is not None:
            raise ContractValidationError("observed observation reason must be null")
        return observed_value(raw.get("value"))
    if availability == "MISSING":
        if raw.get("value") is not None:
            raise ContractValidationError("missing observation value must be null, never an implicit zero")
        return missing_value(raw.get("reason"))
    raise ContractValidationError("observation.availability must be OBSERVED or MISSING")


def _parse_utc(value: datetime | str, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractValidationError(f"{field} must be ISO-8601") from exc
    else:
        raise ContractValidationError(f"{field} must be a timezone-aware datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_utc_interval(
    start: datetime | str,
    end: datetime | str,
    *,
    convention: str,
) -> dict[str, str]:
    """Build a timezone-aware interval using an explicitly selected endpoint convention.

    ``CLOSED_OPEN`` means ``[start, end)`` and is suitable for expected grids.
    ``OPEN_CLOSED`` means ``(start, end]`` and is suitable for strictly
    post-anchor targets. The caller must choose; no implicit convention exists.
    """

    if convention not in _INTERVAL_CONVENTIONS:
        raise ContractValidationError("interval convention must be CLOSED_OPEN or OPEN_CLOSED")
    start_utc = _parse_utc(start, "interval.start_utc")
    end_utc = _parse_utc(end, "interval.end_utc")
    if end_utc <= start_utc:
        raise ContractValidationError("interval end_utc must be after start_utc")
    return {
        "schema": UTC_INTERVAL_SCHEMA,
        "convention": convention,
        "start_utc": _format_utc(start_utc),
        "end_utc": _format_utc(end_utc),
    }


def validate_utc_interval(interval: Mapping[str, Any]) -> dict[str, str]:
    """Validate a normalized interval object and return canonical UTC timestamps."""

    raw = _require_mapping(interval, "interval")
    _require_exact_keys(raw, {"schema", "convention", "start_utc", "end_utc"}, "interval")
    if raw.get("schema") != UTC_INTERVAL_SCHEMA:
        raise ContractValidationError("interval schema is unsupported")
    return build_utc_interval(raw.get("start_utc"), raw.get("end_utc"), convention=raw.get("convention"))


def interval_contains(timestamp: datetime | str, interval: Mapping[str, Any]) -> bool:
    """Apply the declared interval convention to one timezone-aware timestamp."""

    normalized = validate_utc_interval(interval)
    point = _parse_utc(timestamp, "timestamp")
    start = _parse_utc(normalized["start_utc"], "interval.start_utc")
    end = _parse_utc(normalized["end_utc"], "interval.end_utc")
    if normalized["convention"] == CLOSED_OPEN:
        return start <= point < end
    return start < point <= end


def _validate_coverage_observation(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = _require_mapping(item, "coverage observation")
    _require_exact_keys(raw, {"observation_id", "observation"}, "coverage observation")
    return {
        "observation_id": _require_nonempty_string(raw.get("observation_id"), "coverage observation.observation_id"),
        "observation": validate_observation_value(raw.get("observation")),
    }


def build_coverage_result(
    coverage_kind: str,
    interval: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build fail-closed expected-observation coverage with explicit missingness.

    Every expected observation must be present in ``observations`` exactly once.
    The result is complete only when every observation is explicitly observed;
    an observed ``0`` is valid, while ``MISSING`` is incomplete.
    """

    normalized_observations = [_validate_coverage_observation(item) for item in observations]
    if not normalized_observations:
        raise ContractValidationError("coverage_result requires at least one expected observation")
    normalized_observations.sort(key=lambda item: item["observation_id"])
    ids = [item["observation_id"] for item in normalized_observations]
    if len(ids) != len(set(ids)):
        raise ContractValidationError("coverage_result observation_id values must be unique")
    missing_ids = [
        item["observation_id"]
        for item in normalized_observations
        if item["observation"]["availability"] == "MISSING"
    ]
    unsigned = {
        "schema": COVERAGE_RESULT_SCHEMA,
        "coverage_kind": _require_nonempty_string(coverage_kind, "coverage_kind"),
        "interval": validate_utc_interval(interval),
        "observations": normalized_observations,
        "missing_observation_ids": missing_ids,
        "status": "INCOMPLETE" if missing_ids else "COMPLETE",
    }
    return {**unsigned, "coverage_sha256": canonical_json_sha256(unsigned)}


def validate_coverage_result(coverage: Mapping[str, Any]) -> dict[str, Any]:
    """Validate coverage status, missing list, ordering, and canonical self-hash."""

    raw = _require_mapping(coverage, "coverage_result")
    _require_exact_keys(
        raw,
        {
            "schema",
            "coverage_kind",
            "interval",
            "observations",
            "missing_observation_ids",
            "status",
            "coverage_sha256",
        },
        "coverage_result",
    )
    if raw.get("schema") != COVERAGE_RESULT_SCHEMA:
        raise ContractValidationError("coverage_result schema is unsupported")
    observations = raw.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ContractValidationError("coverage_result.observations must be a nonempty array")
    normalized_observations = [_validate_coverage_observation(item) for item in observations]
    sorted_observations = sorted(normalized_observations, key=lambda item: item["observation_id"])
    if normalized_observations != sorted_observations:
        raise ContractValidationError("coverage_result.observations must be sorted by observation_id")
    ids = [item["observation_id"] for item in normalized_observations]
    if len(ids) != len(set(ids)):
        raise ContractValidationError("coverage_result observation_id values must be unique")
    missing = raw.get("missing_observation_ids")
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        raise ContractValidationError("coverage_result.missing_observation_ids must be an array of strings")
    expected_missing = [
        item["observation_id"]
        for item in normalized_observations
        if item["observation"]["availability"] == "MISSING"
    ]
    if missing != expected_missing:
        raise ContractValidationError("coverage_result missing_observation_ids does not match observation availability")
    expected_status = "INCOMPLETE" if expected_missing else "COMPLETE"
    if raw.get("status") != expected_status:
        raise ContractValidationError("coverage_result status does not match observation availability")
    unsigned = {
        "schema": COVERAGE_RESULT_SCHEMA,
        "coverage_kind": _require_nonempty_string(raw.get("coverage_kind"), "coverage_result.coverage_kind"),
        "interval": validate_utc_interval(raw.get("interval")),
        "observations": normalized_observations,
        "missing_observation_ids": expected_missing,
        "status": expected_status,
    }
    expected_hash = canonical_json_sha256(unsigned)
    if _require_sha256(raw.get("coverage_sha256"), "coverage_result.coverage_sha256") != expected_hash:
        raise ContractValidationError("coverage_sha256 does not match canonical coverage result")
    return {**unsigned, "coverage_sha256": expected_hash}


def build_manifest_result(
    manifest_type: str,
    source_set: Mapping[str, Any],
    outcome: str,
    *,
    coverage: Mapping[str, Any] | None = None,
    policy_sha256: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a hash-bound, non-authoritative successor manifest result.

    ``COMPLETE`` requires a complete coverage result. The generic contract cannot
    manufacture a completion claim from a source digest alone. Stage-specific
    modules remain responsible for their terminal, eligibility, policy, and
    domain validations before calling this builder.
    """

    if outcome not in _MANIFEST_OUTCOMES:
        raise ContractValidationError("manifest outcome is unsupported")
    normalized_coverage = validate_coverage_result(coverage) if coverage is not None else None
    if outcome == "COMPLETE" and (normalized_coverage is None or normalized_coverage["status"] != "COMPLETE"):
        raise ContractValidationError("COMPLETE manifest requires COMPLETE coverage")
    normalized_attributes = _json_copy(dict(_require_mapping(attributes or {}, "manifest attributes")))
    unsigned = {
        "schema": MANIFEST_RESULT_SCHEMA,
        "manifest_type": _require_nonempty_string(manifest_type, "manifest_type"),
        "outcome": outcome,
        "source_set": validate_canonical_source_set(source_set),
        "coverage": normalized_coverage,
        "policy_sha256": _require_sha256(policy_sha256, "policy_sha256") if policy_sha256 is not None else None,
        "attributes": normalized_attributes,
        "non_authority_claims": non_authority_claims(),
    }
    return {**unsigned, "manifest_sha256": canonical_json_sha256(unsigned)}


def validate_manifest_result(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a v2 result including its source set, coverage prerequisite, and hash."""

    raw = _require_mapping(manifest, "manifest_result")
    _require_exact_keys(
        raw,
        {
            "schema",
            "manifest_type",
            "outcome",
            "source_set",
            "coverage",
            "policy_sha256",
            "attributes",
            "non_authority_claims",
            "manifest_sha256",
        },
        "manifest_result",
    )
    if raw.get("schema") != MANIFEST_RESULT_SCHEMA:
        raise ContractValidationError("manifest_result schema is unsupported")
    outcome = raw.get("outcome")
    if outcome not in _MANIFEST_OUTCOMES:
        raise ContractValidationError("manifest_result outcome is unsupported")
    coverage_raw = raw.get("coverage")
    normalized_coverage = validate_coverage_result(coverage_raw) if coverage_raw is not None else None
    if outcome == "COMPLETE" and (normalized_coverage is None or normalized_coverage["status"] != "COMPLETE"):
        raise ContractValidationError("COMPLETE manifest requires COMPLETE coverage")
    normalized_attributes = _json_copy(dict(_require_mapping(raw.get("attributes"), "manifest_result.attributes")))
    unsigned = {
        "schema": MANIFEST_RESULT_SCHEMA,
        "manifest_type": _require_nonempty_string(raw.get("manifest_type"), "manifest_result.manifest_type"),
        "outcome": outcome,
        "source_set": validate_canonical_source_set(raw.get("source_set")),
        "coverage": normalized_coverage,
        "policy_sha256": _require_sha256(raw.get("policy_sha256"), "manifest_result.policy_sha256")
        if raw.get("policy_sha256") is not None
        else None,
        "attributes": normalized_attributes,
        "non_authority_claims": validate_non_authority_claims(raw.get("non_authority_claims")),
    }
    expected_hash = canonical_json_sha256(unsigned)
    if _require_sha256(raw.get("manifest_sha256"), "manifest_result.manifest_sha256") != expected_hash:
        raise ContractValidationError("manifest_sha256 does not match canonical manifest result")
    return {**unsigned, "manifest_sha256": expected_hash}


def _load_json_object(path: str | Path) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"cannot read JSON from {path}") from exc
    return _require_mapping(value, f"JSON at {path}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline contract CLI; no network or external storage is contacted."""

    parser = argparse.ArgumentParser(description="Validate opt-in Orderflow Edge Lab v2 integrity contracts.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    canonical_parser = subcommands.add_parser("canonical-json", help="emit canonical JSON and its SHA-256")
    canonical_parser.add_argument("input", help="path to a JSON value")
    file_parser = subcommands.add_parser("verify-file", help="verify local file bytes against a file identity JSON object")
    file_parser.add_argument("file", help="local file to hash")
    file_parser.add_argument("identity", help="expected file identity JSON object")
    manifest_parser = subcommands.add_parser("validate-manifest", help="validate a v2 manifest result JSON object")
    manifest_parser.add_argument("manifest", help="manifest result JSON object")
    args = parser.parse_args(argv)

    try:
        if args.command == "canonical-json":
            value = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = {
                "canonical_json": canonical_json_bytes(value).decode("utf-8"),
                "canonical_sha256": canonical_json_sha256(value),
                "verification_scope": "canonical_local_json_only",
                "non_authority_claims": non_authority_claims(),
            }
            print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            return 0
        if args.command == "verify-file":
            result = verify_file_identity(args.file, _load_json_object(args.identity))
            print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            return 0 if result["status"] == "VERIFIED_LOCAL_BYTES" else 1
        if args.command == "validate-manifest":
            result = validate_manifest_result(_load_json_object(args.manifest))
            print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            return 0
    except (ContractValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "status": "INVALID"}, sort_keys=True), file=sys.stderr)
        return 2
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())

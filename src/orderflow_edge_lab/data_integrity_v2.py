"""Opt-in v2 capture-pair integrity and strict replay contracts."""

from __future__ import annotations


import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    ContractValidationError,
    build_canonical_source_set,
    build_coverage_result,
    build_file_identity,
    build_manifest_result,
    build_source_record,
    canonical_json_bytes,
    canonical_json_sha256,
    non_authority_claims,
    observed_value,
    validate_canonical_source_set,
    validate_file_identity,
    validate_manifest_result,
    validate_non_authority_claims,
    verify_file_identity,
)
from orderflow_edge_lab.mexc_orderflow import MexcOrderFlowError, iter_jsonl


CAPTURE_PAIR_SCHEMA = "orderflow_edge_lab.capture_pair_manifest.v2"
CAPTURE_ELIGIBILITY_SCHEMA = "orderflow_edge_lab.capture_eligibility_result.v2"
CAPTURE_ELIGIBILITY_POLICY_SCHEMA = "orderflow_edge_lab.capture_eligibility_policy.v2"
REPLAY_SELECTION_POLICY_SCHEMA = "orderflow_edge_lab.capture_replay_selection_policy.v2"
REPLAY_AVAILABILITY_SCHEMA = "orderflow_edge_lab.capture_replay_availability.v2"
STRICT_REPLAY_SCHEMA = "orderflow_edge_lab.strict_replay_output.v2"


class DataIntegrityV2Error(ValueError):
    """Raised when a prospective v2 integrity or eligibility contract fails."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DataIntegrityV2Error(f"{field} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        extra = ",".join(sorted(actual - expected))
        details = "; ".join(
            item for item in (f"missing={missing}" if missing else "", f"extra={extra}" if extra else "") if item
        )
        raise DataIntegrityV2Error(f"{field} has unsupported shape ({details})")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataIntegrityV2Error(f"{field} must be a nonempty string")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise DataIntegrityV2Error(f"{field} must be a SHA-256")
    lowered = value.lower()
    if any(char not in "0123456789abcdef" for char in lowered):
        raise DataIntegrityV2Error(f"{field} must be a SHA-256")
    return lowered


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise DataIntegrityV2Error(f"{field} must be a positive integer")
    return value


def _normal_json(value: object, field: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except ContractValidationError as exc:
        raise DataIntegrityV2Error(f"{field} is not ordinary canonical JSON: {exc}") from exc


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataIntegrityV2Error(f"{field} must be a timezone-aware ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataIntegrityV2Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataIntegrityV2Error(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_before_or_equal(left: str, right: str) -> bool:
    return datetime.fromisoformat(left.replace("Z", "+00:00")) <= datetime.fromisoformat(right.replace("Z", "+00:00"))


def _names(values: object, field: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise DataIntegrityV2Error(f"{field} must be a nonempty array")
    normalized = [_string(value, f"{field} item") for value in values]
    if len(normalized) != len(set(normalized)):
        raise DataIntegrityV2Error(f"{field} must not contain duplicates")
    return normalized


def _schema_versions(values: object, field: str) -> list[int]:
    if not isinstance(values, list) or not values:
        raise DataIntegrityV2Error(f"{field} must be a nonempty array")
    normalized = [_positive_int(value, f"{field} item") for value in values]
    if len(normalized) != len(set(normalized)):
        raise DataIntegrityV2Error(f"{field} must not contain duplicates")
    return sorted(normalized)


def _fsync_directory(path: Path) -> None:
    """Persist local directory entry changes; this makes no external-storage claim."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_exclusive_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise DataIntegrityV2Error(f"refusing to overwrite existing output: {path}")
    partial = path.with_name(path.name + ".partial")
    if partial.exists():
        raise DataIntegrityV2Error(f"refusing to overwrite existing partial output: {partial}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        handle.write(canonical_json_bytes(payload) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    _fsync_directory(path.parent)


def _write_jsonl_atomic(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise DataIntegrityV2Error(f"refusing to overwrite existing output: {path}")
    partial = path.with_name(path.name + ".partial")
    if partial.exists():
        raise DataIntegrityV2Error(f"refusing to overwrite existing partial output: {partial}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        for record in records:
            handle.write(canonical_json_bytes(record) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    _fsync_directory(path.parent)


def _json_object_file(path: str | Path, field: str) -> Mapping[str, Any]:
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataIntegrityV2Error(f"cannot read {field}: {path}") from exc
    return _mapping(loaded, field)


def _capture_file_metadata(path: str | Path, *, kind: str, capture_id: str) -> dict[str, Any]:
    """Require one final terminal summary but retain non-policy event details."""
    target = Path(path)
    if not target.is_file():
        raise DataIntegrityV2Error(f"{kind} capture file is missing: {target}")
    if target.name.endswith(".partial"):
        raise DataIntegrityV2Error(f"{kind} capture file is partial, not complete")
    try:
        records = list(iter_jsonl(target))
    except (OSError, MexcOrderFlowError) as exc:
        raise DataIntegrityV2Error(f"{kind} capture JSONL is invalid") from exc
    if len(records) < 2:
        raise DataIntegrityV2Error(f"{kind} capture needs a session and final summary")
    first = records[0]
    expected_session_type = "session" if kind == "raw" else "feature_session"
    if first.get("record_type") != expected_session_type:
        raise DataIntegrityV2Error(f"{kind} capture must begin with {expected_session_type}")
    if first.get("capture_id") != capture_id:
        raise DataIntegrityV2Error(f"{kind} session capture_id does not match pair capture_id")
    schema_keys = ("schema_version", "feature_schema_version") if kind == "feature" else ("schema_version",)
    session_schema = next((first.get(key) for key in schema_keys if type(first.get(key)) is int and first[key] > 0), None)
    if session_schema is None:
        raise DataIntegrityV2Error(f"{kind} session requires a positive schema version")
    symbols = _names(first.get("symbols"), f"{kind} session symbols")
    summaries = [index for index, item in enumerate(records) if item.get("record_type") == "session_summary"]
    if len(summaries) != 1:
        raise DataIntegrityV2Error(f"{kind} capture must contain exactly one session_summary")
    if summaries[0] != len(records) - 1:
        raise DataIntegrityV2Error(f"{kind} capture has records after session_summary")
    terminal = records[-1]
    if terminal.get("capture_id") != capture_id:
        raise DataIntegrityV2Error(f"{kind} terminal capture_id does not match pair capture_id")
    ended_at_ns = _positive_int(terminal.get("ended_at_ns"), f"{kind} terminal ended_at_ns")
    return {
        "file_name": target.name,
        "identity": build_file_identity(target, logical_name=target.name),
        "record_count": len(records),
        "session_schema_version": session_schema,
        "symbols": symbols,
        "terminal": {
            "record_index": len(records) - 1,
            "record_sha256": canonical_json_sha256(terminal),
            "ended_at_ns": ended_at_ns,
        },
    }


def _pair_file_part(value: object, kind: str) -> dict[str, Any]:
    raw = _mapping(value, kind)
    _exact_keys(raw, {"file_name", "identity", "record_count", "session_schema_version", "symbols", "terminal"}, kind)
    name = _string(raw.get("file_name"), f"{kind}.file_name")
    if Path(name).name != name or name.endswith(".partial"):
        raise DataIntegrityV2Error(f"{kind}.file_name must be a final basename")
    terminal = _mapping(raw.get("terminal"), f"{kind}.terminal")
    _exact_keys(terminal, {"record_index", "record_sha256", "ended_at_ns"}, f"{kind}.terminal")
    record_count = _positive_int(raw.get("record_count"), f"{kind}.record_count")
    record_index = _positive_int(terminal.get("record_index"), f"{kind}.terminal.record_index")
    if record_index != record_count - 1:
        raise DataIntegrityV2Error(f"{kind}.terminal.record_index must be the final record")
    return {
        "file_name": name,
        "identity": validate_file_identity(_mapping(raw.get("identity"), f"{kind}.identity")),
        "record_count": record_count,
        "session_schema_version": _positive_int(raw.get("session_schema_version"), f"{kind}.session_schema_version"),
        "symbols": _names(raw.get("symbols"), f"{kind}.symbols"),
        "terminal": {
            "record_index": record_index,
            "record_sha256": _sha256(terminal.get("record_sha256"), f"{kind}.terminal.record_sha256"),
            "ended_at_ns": _positive_int(terminal.get("ended_at_ns"), f"{kind}.terminal.ended_at_ns"),
        },
    }


def _pair_unsigned(
    *,
    capture_id: str,
    raw: Mapping[str, Any],
    features: Mapping[str, Any],
    capture_interval: Mapping[str, Any],
    source_set: Mapping[str, Any],
    policy_sha256: str | None,
    manifest_result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": CAPTURE_PAIR_SCHEMA,
        "analysis": "capture_pair_manifest_v2",
        "capture_id": capture_id,
        "completed": True,
        "raw": _normal_json(raw, "raw"),
        "features": _normal_json(features, "features"),
        "capture_interval": _normal_json(capture_interval, "capture_interval"),
        "source_set": _normal_json(source_set, "source_set"),
        "policy_sha256": policy_sha256,
        "manifest_result": _normal_json(manifest_result, "manifest_result"),
        "non_authority_claims": non_authority_claims(),
    }


def build_capture_pair_manifest_v2(
    raw_path: str | Path,
    feature_path: str | Path,
    *,
    capture_id: str,
    capture_interval: Mapping[str, Any],
    policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a hash-bound final marker from two terminally complete local files.

    This does not assert that two pre-existing files were atomically published.
    ``CapturePairWriterV2`` is the prospective writer that emits this marker only
    after both partial files are fsynced and renamed.  Strict consumers require
    the marker, not merely two final-looking filenames.
    """
    normalized_id = _string(capture_id, "capture_id")
    raw = _capture_file_metadata(raw_path, kind="raw", capture_id=normalized_id)
    features = _capture_file_metadata(feature_path, kind="feature", capture_id=normalized_id)
    if raw["symbols"] != features["symbols"]:
        raise DataIntegrityV2Error("raw and feature session symbols must match exactly")
    interval = _normal_json(capture_interval, "capture_interval")
    try:
        coverage = build_coverage_result(
            "capture_pair_artifacts",
            interval,
            [
                {"observation_id": "features", "observation": observed_value(1)},
                {"observation_id": "raw", "observation": observed_value(1)},
            ],
        )
    except ContractValidationError as exc:
        raise DataIntegrityV2Error("capture_interval is invalid") from exc
    source_set = build_canonical_source_set(
        [
            build_source_record("capture_features", features["identity"]),
            build_source_record("capture_raw", raw["identity"]),
        ]
    )
    normalized_policy = _sha256(policy_sha256, "policy_sha256") if policy_sha256 is not None else None
    manifest_result = build_manifest_result(
        "capture_pair_v2",
        source_set,
        "COMPLETE",
        coverage=coverage,
        policy_sha256=normalized_policy,
        attributes={
            "capture_id": normalized_id,
            "completed": True,
            "feature_terminal_sha256": features["terminal"]["record_sha256"],
            "raw_terminal_sha256": raw["terminal"]["record_sha256"],
        },
    )
    unsigned = _pair_unsigned(
        capture_id=normalized_id,
        raw=raw,
        features=features,
        capture_interval=interval,
        source_set=source_set,
        policy_sha256=normalized_policy,
        manifest_result=manifest_result,
    )
    return {**unsigned, "pair_manifest_sha256": canonical_json_sha256(unsigned)}


def validate_capture_pair_manifest_v2(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate marker syntax, cross-links, false authority claims, and self-hash."""
    raw_manifest = _mapping(manifest, "capture_pair_manifest")
    _exact_keys(
        raw_manifest,
        {
            "schema", "analysis", "capture_id", "completed", "raw", "features",
            "capture_interval", "source_set", "policy_sha256", "manifest_result",
            "non_authority_claims", "pair_manifest_sha256",
        },
        "capture_pair_manifest",
    )
    if raw_manifest.get("schema") != CAPTURE_PAIR_SCHEMA or raw_manifest.get("analysis") != "capture_pair_manifest_v2":
        raise DataIntegrityV2Error("capture_pair_manifest schema or analysis is unsupported")
    if raw_manifest.get("completed") is not True:
        raise DataIntegrityV2Error("capture_pair_manifest completed must be true")
    capture_id = _string(raw_manifest.get("capture_id"), "capture_id")
    normalized_raw = _pair_file_part(raw_manifest.get("raw"), "raw")
    normalized_features = _pair_file_part(raw_manifest.get("features"), "features")
    if normalized_raw["symbols"] != normalized_features["symbols"]:
        raise DataIntegrityV2Error("capture_pair_manifest raw and features symbols differ")
    source_set = validate_canonical_source_set(_mapping(raw_manifest.get("source_set"), "source_set"))
    expected_source_set = build_canonical_source_set(
        [
            build_source_record("capture_features", normalized_features["identity"]),
            build_source_record("capture_raw", normalized_raw["identity"]),
        ]
    )
    if source_set != expected_source_set:
        raise DataIntegrityV2Error("capture_pair_manifest source_set does not bind exact raw and feature identities")
    interval = _normal_json(raw_manifest.get("capture_interval"), "capture_interval")
    try:
        coverage = build_coverage_result(
            "capture_pair_artifacts",
            interval,
            [
                {"observation_id": "features", "observation": observed_value(1)},
                {"observation_id": "raw", "observation": observed_value(1)},
            ],
        )
    except ContractValidationError as exc:
        raise DataIntegrityV2Error("capture_pair_manifest capture_interval is invalid") from exc
    normalized_policy = _sha256(raw_manifest.get("policy_sha256"), "policy_sha256") if raw_manifest.get("policy_sha256") is not None else None
    manifest_result = validate_manifest_result(_mapping(raw_manifest.get("manifest_result"), "manifest_result"))
    expected_manifest_result = build_manifest_result(
        "capture_pair_v2",
        source_set,
        "COMPLETE",
        coverage=coverage,
        policy_sha256=normalized_policy,
        attributes={
            "capture_id": capture_id,
            "completed": True,
            "feature_terminal_sha256": normalized_features["terminal"]["record_sha256"],
            "raw_terminal_sha256": normalized_raw["terminal"]["record_sha256"],
        },
    )
    if manifest_result != expected_manifest_result:
        raise DataIntegrityV2Error("capture_pair_manifest generic completion result is not cross-linked")
    claims = validate_non_authority_claims(_mapping(raw_manifest.get("non_authority_claims"), "non_authority_claims"))
    unsigned = _pair_unsigned(
        capture_id=capture_id,
        raw=normalized_raw,
        features=normalized_features,
        capture_interval=interval,
        source_set=source_set,
        policy_sha256=normalized_policy,
        manifest_result=manifest_result,
    )
    expected_hash = canonical_json_sha256(unsigned)
    if _sha256(raw_manifest.get("pair_manifest_sha256"), "pair_manifest_sha256") != expected_hash:
        raise DataIntegrityV2Error("capture_pair_manifest self-hash does not match")
    return {**unsigned, "non_authority_claims": claims, "pair_manifest_sha256": expected_hash}


def load_capture_pair_manifest_v2(path: str | Path) -> dict[str, Any]:
    """Load the final pair completion marker; partial or absent markers never fall back."""
    target = Path(path)
    if target.name.endswith(".partial"):
        raise DataIntegrityV2Error("partial pair markers are not completion markers")
    return validate_capture_pair_manifest_v2(_json_object_file(target, "capture pair manifest"))


def verify_capture_pair_v2(
    manifest: Mapping[str, Any], raw_path: str | Path, feature_path: str | Path
) -> dict[str, Any]:
    """Verify all local bytes and terminal content before a strict consumer writes."""
    normalized = validate_capture_pair_manifest_v2(manifest)
    raw_target, feature_target = Path(raw_path), Path(feature_path)
    if raw_target.name != normalized["raw"]["file_name"]:
        raise DataIntegrityV2Error("raw path basename does not match pair marker")
    if feature_target.name != normalized["features"]["file_name"]:
        raise DataIntegrityV2Error("feature path basename does not match pair marker")
    checks: dict[str, Any] = {}
    for label, target, expected, kind in (
        ("raw", raw_target, normalized["raw"], "raw"),
        ("features", feature_target, normalized["features"], "feature"),
    ):
        result = verify_file_identity(target, expected["identity"])
        if result["status"] != "VERIFIED_LOCAL_BYTES":
            raise DataIntegrityV2Error(f"{label} local bytes do not match capture pair marker")
        observed = _capture_file_metadata(target, kind=kind, capture_id=normalized["capture_id"])
        if observed != expected:
            raise DataIntegrityV2Error(f"{label} terminal/session structure does not match capture pair marker")
        checks[label] = result
    return {
        "schema": "orderflow_edge_lab.capture_pair_verification.v2",
        "analysis": "verify_capture_pair_v2",
        "capture_id": normalized["capture_id"],
        "pair_manifest_sha256": normalized["pair_manifest_sha256"],
        "source_set": normalized["source_set"],
        "raw_verification": checks["raw"],
        "feature_verification": checks["features"],
        "status": "VERIFIED_CAPTURE_PAIR_LOCAL_BYTES",
        "verification_scope": "local_bytes_and_terminal_structure_only",
        "non_authority_claims": non_authority_claims(),
    }


class CapturePairWriterV2:
    """Prospective partial writer with a final authoritative pair marker.

    In an exception/kill path only ``.partial`` diagnostics are retained.  The
    final marker, not the two individually atomic renames, is the completion
    authority seen by strict replay and eligibility consumers.
    """

    def __init__(
        self,
        output_dir: str | Path,
        *,
        capture_id: str,
        raw_file_name: str,
        feature_file_name: str,
        capture_interval: Mapping[str, Any],
        raw_session: Mapping[str, Any],
        feature_session: Mapping[str, Any],
        policy_sha256: str | None = None,
    ) -> None:
        self.capture_id = _string(capture_id, "capture_id")
        self.capture_interval = _normal_json(capture_interval, "capture_interval")
        self.policy_sha256 = _sha256(policy_sha256, "policy_sha256") if policy_sha256 is not None else None
        if Path(self.capture_id).name != self.capture_id or self.capture_id in {".", ".."}:
            raise DataIntegrityV2Error("capture_id must be a safe basename")
        root = Path(output_dir)
        raw_name, feature_name = _string(raw_file_name, "raw_file_name"), _string(feature_file_name, "feature_file_name")
        if Path(raw_name).name != raw_name or Path(feature_name).name != feature_name or raw_name == feature_name:
            raise DataIntegrityV2Error("v2 raw and feature names must be distinct basenames")
        if raw_name.endswith(".partial") or feature_name.endswith(".partial"):
            raise DataIntegrityV2Error("v2 final names cannot be partial names")
        self.raw_path, self.feature_path = root / raw_name, root / feature_name
        self.manifest_path = root / f"{self.capture_id}_capture_pair_v2.json"
        self.raw_partial_path = self.raw_path.with_name(self.raw_path.name + ".partial")
        self.feature_partial_path = self.feature_path.with_name(self.feature_path.name + ".partial")
        for candidate in (self.raw_path, self.feature_path, self.manifest_path, self.raw_partial_path, self.feature_partial_path):
            if candidate.exists():
                raise DataIntegrityV2Error(f"refusing to overwrite capture artifact: {candidate}")
        root.mkdir(parents=True, exist_ok=True)
        self._raw = self.raw_partial_path.open("xb")
        try:
            self._features = self.feature_partial_path.open("xb")
        except Exception:
            self._raw.close()
            raise
        self._closed = False
        self._finalized = False
        self._write(self._raw, self._validate_session(raw_session, "raw"))
        self._write(self._features, self._validate_session(feature_session, "feature"))

    def _validate_session(self, session: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
        item = _mapping(session, f"{kind}_session")
        expected_type = "session" if kind == "raw" else "feature_session"
        if item.get("record_type") != expected_type or item.get("capture_id") != self.capture_id:
            raise DataIntegrityV2Error(f"{kind}_session must declare {expected_type} and this capture_id")
        _names(item.get("symbols"), f"{kind}_session.symbols")
        keys = ("schema_version", "feature_schema_version") if kind == "feature" else ("schema_version",)
        if not any(type(item.get(key)) is int and item[key] > 0 for key in keys):
            raise DataIntegrityV2Error(f"{kind}_session requires a positive schema version")
        return item

    @staticmethod
    def _write(handle: Any, record: Mapping[str, Any]) -> None:
        handle.write(canonical_json_bytes(record) + b"\n")
        handle.flush()

    def write_raw(self, record: Mapping[str, Any]) -> None:
        if self._closed:
            raise DataIntegrityV2Error("capture pair writer is closed")
        self._write(self._raw, _mapping(record, "raw record"))

    def write_feature(self, record: Mapping[str, Any]) -> None:
        if self._closed:
            raise DataIntegrityV2Error("capture pair writer is closed")
        self._write(self._features, _mapping(record, "feature record"))

    def _close_partial_handles(self) -> None:
        if self._closed:
            return
        for handle in (self._raw, self._features):
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
        self._closed = True

    def abort(self) -> None:
        """Fsync diagnostic partial bytes without emitting final names or a marker."""
        self._close_partial_handles()

    def finalize(self, raw_summary: Mapping[str, Any], feature_summary: Mapping[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise DataIntegrityV2Error("capture pair writer is already closed")
        for kind, summary, handle in (("raw", raw_summary, self._raw), ("feature", feature_summary, self._features)):
            item = _mapping(summary, f"{kind}_summary")
            if item.get("record_type") != "session_summary" or item.get("capture_id") != self.capture_id:
                raise DataIntegrityV2Error(f"{kind}_summary must be a session_summary for this capture_id")
            _positive_int(item.get("ended_at_ns"), f"{kind}_summary.ended_at_ns")
            self._write(handle, item)
        self._close_partial_handles()
        os.replace(self.raw_partial_path, self.raw_path)
        _fsync_directory(self.raw_path.parent)
        os.replace(self.feature_partial_path, self.feature_path)
        _fsync_directory(self.feature_path.parent)
        manifest = build_capture_pair_manifest_v2(
            self.raw_path, self.feature_path, capture_id=self.capture_id,
            capture_interval=self.capture_interval, policy_sha256=self.policy_sha256,
        )
        _write_json_exclusive_atomic(self.manifest_path, manifest)
        self._finalized = True
        return manifest

    def __enter__(self) -> "CapturePairWriterV2":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._finalized:
            self.abort()


def _validate_eligibility_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(policy, "eligibility_policy")
    expected = {
        "schema", "policy_id", "declared_at_utc", "accepted_raw_session_schema_versions",
        "accepted_feature_session_schema_versions", "expected_symbols", "allowed_raw_record_types",
        "allowed_feature_record_types", "require_monotonic_feature_received_at_ns", "require_quality_report",
        "accepted_quality_analyses", "eligible_quality_statuses", "policy_sha256",
    }
    _exact_keys(raw, expected, "eligibility_policy")
    if raw.get("schema") != CAPTURE_ELIGIBILITY_POLICY_SCHEMA:
        raise DataIntegrityV2Error("eligibility_policy schema is unsupported")
    unsigned = {
        "schema": CAPTURE_ELIGIBILITY_POLICY_SCHEMA,
        "policy_id": _string(raw.get("policy_id"), "eligibility_policy.policy_id"),
        "declared_at_utc": _utc(raw.get("declared_at_utc"), "eligibility_policy.declared_at_utc"),
        "accepted_raw_session_schema_versions": _schema_versions(raw.get("accepted_raw_session_schema_versions"), "accepted_raw_session_schema_versions"),
        "accepted_feature_session_schema_versions": _schema_versions(raw.get("accepted_feature_session_schema_versions"), "accepted_feature_session_schema_versions"),
        "expected_symbols": _names(raw.get("expected_symbols"), "expected_symbols"),
        "allowed_raw_record_types": _names(raw.get("allowed_raw_record_types"), "allowed_raw_record_types"),
        "allowed_feature_record_types": _names(raw.get("allowed_feature_record_types"), "allowed_feature_record_types"),
        "require_monotonic_feature_received_at_ns": raw.get("require_monotonic_feature_received_at_ns"),
        "require_quality_report": raw.get("require_quality_report"),
        "accepted_quality_analyses": _names(raw.get("accepted_quality_analyses"), "accepted_quality_analyses"),
        "eligible_quality_statuses": _names(raw.get("eligible_quality_statuses"), "eligible_quality_statuses"),
    }
    if type(unsigned["require_monotonic_feature_received_at_ns"]) is not bool or type(unsigned["require_quality_report"]) is not bool:
        raise DataIntegrityV2Error("eligibility policy boolean fields must be booleans")
    expected_hash = canonical_json_sha256(unsigned)
    if _sha256(raw.get("policy_sha256"), "eligibility_policy.policy_sha256") != expected_hash:
        raise DataIntegrityV2Error("eligibility_policy self-hash does not match")
    return {**unsigned, "policy_sha256": expected_hash}


def build_capture_eligibility_policy_v2(
    *,
    policy_id: str,
    declared_at_utc: str,
    accepted_raw_session_schema_versions: Sequence[int],
    accepted_feature_session_schema_versions: Sequence[int],
    expected_symbols: Sequence[str],
    allowed_raw_record_types: Sequence[str],
    allowed_feature_record_types: Sequence[str],
    require_monotonic_feature_received_at_ns: bool,
    require_quality_report: bool,
    accepted_quality_analyses: Sequence[str],
    eligible_quality_statuses: Sequence[str],
) -> dict[str, Any]:
    """Build a structural policy only from caller-supplied, predeclared choices."""
    unsigned = {
        "schema": CAPTURE_ELIGIBILITY_POLICY_SCHEMA,
        "policy_id": _string(policy_id, "policy_id"),
        "declared_at_utc": _utc(declared_at_utc, "declared_at_utc"),
        "accepted_raw_session_schema_versions": _schema_versions(list(accepted_raw_session_schema_versions), "accepted_raw_session_schema_versions"),
        "accepted_feature_session_schema_versions": _schema_versions(list(accepted_feature_session_schema_versions), "accepted_feature_session_schema_versions"),
        "expected_symbols": _names(list(expected_symbols), "expected_symbols"),
        "allowed_raw_record_types": _names(list(allowed_raw_record_types), "allowed_raw_record_types"),
        "allowed_feature_record_types": _names(list(allowed_feature_record_types), "allowed_feature_record_types"),
        "require_monotonic_feature_received_at_ns": require_monotonic_feature_received_at_ns,
        "require_quality_report": require_quality_report,
        "accepted_quality_analyses": _names(list(accepted_quality_analyses), "accepted_quality_analyses"),
        "eligible_quality_statuses": _names(list(eligible_quality_statuses), "eligible_quality_statuses"),
    }
    if type(require_monotonic_feature_received_at_ns) is not bool or type(require_quality_report) is not bool:
        raise DataIntegrityV2Error("policy boolean values must be booleans")
    return {**unsigned, "policy_sha256": canonical_json_sha256(unsigned)}


def _capture_records(path: Path) -> list[Mapping[str, Any]]:
    try:
        return list(iter_jsonl(path))
    except (OSError, MexcOrderFlowError) as exc:
        raise DataIntegrityV2Error(f"cannot read capture JSONL: {path}") from exc


def _quality_identity_and_reasons(
    quality_path: str | Path | None, feature_sha256: str, policy: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, list[str], Mapping[str, Any] | None]:
    if quality_path is None:
        return None, (["quality_report_required"] if policy["require_quality_report"] else []), None
    target = Path(quality_path)
    try:
        report = _json_object_file(target, "quality report")
        identity = build_file_identity(target, logical_name=target.name)
    except (DataIntegrityV2Error, ContractValidationError):
        return None, ["quality_report_invalid"], None
    reasons: list[str] = []
    if report.get("analysis") not in policy["accepted_quality_analyses"]:
        reasons.append("unsupported_quality_analysis")
    if report.get("source_sha256") != feature_sha256:
        reasons.append("quality_source_sha256_mismatch")
    status = report.get("status")
    if status not in policy["eligible_quality_statuses"]:
        reasons.append(f"quality_status_not_eligible:{status}")
    return identity, reasons, report


def _structural_eligibility_reasons(
    raw_path: Path, feature_path: Path, pair: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[str]:
    reasons: list[str] = []
    if not _utc_before_or_equal(policy["declared_at_utc"], pair["capture_interval"]["start_utc"]):
        reasons.append("policy_declared_after_capture_start")
    if pair["raw"]["session_schema_version"] not in policy["accepted_raw_session_schema_versions"]:
        reasons.append(f"unsupported_raw_session_schema:{pair['raw']['session_schema_version']}")
    if pair["features"]["session_schema_version"] not in policy["accepted_feature_session_schema_versions"]:
        reasons.append(f"unsupported_feature_session_schema:{pair['features']['session_schema_version']}")
    expected = policy["expected_symbols"]
    if pair["raw"]["symbols"] != expected or pair["features"]["symbols"] != expected:
        reasons.append("pair_symbols_do_not_match_predeclared_policy")
    for kind, records, allowed in (
        ("raw", _capture_records(raw_path), policy["allowed_raw_record_types"]),
        ("feature", _capture_records(feature_path), policy["allowed_feature_record_types"]),
    ):
        if pair["raw"]["session_schema_version"] < 3:
            reasons.append("unknown_legacy_terminal")
        terminal = records[-1].get("session_terminal_v2")
        if terminal is None:
            reasons.append(f"missing_{kind}_ingestion_terminal_v2")
        else:
            from orderflow_edge_lab.ingestion_v2 import validate_session_terminal_v2
            try:
                validated = validate_session_terminal_v2(terminal)
                if validated["outcome"] != "COMPLETE":
                    reasons.append(f"incomplete_{kind}_ingestion_terminal_v2")
                if validated["attributes"]["requested_interval"] != pair["capture_interval"]:
                    reasons.append(f"{kind}_terminal_capture_interval_mismatch")
                if sorted(state["symbol"] for state in validated["attributes"]["symbol_states"]) != sorted(expected):
                    reasons.append(f"{kind}_terminal_symbols_mismatch")
            except ValueError:
                reasons.append(f"invalid_{kind}_ingestion_terminal_v2")
        previous_received: int | None = None
        for index, record in enumerate(records):
            is_session = index == 0
            is_summary = index == len(records) - 1
            record_type = record.get("record_type")
            if not is_session and not is_summary:
                if record_type not in allowed:
                    reasons.append(f"unsupported_{kind}_record_type:{record_type}")
                symbol = record.get("symbol")
                if symbol is not None and symbol not in expected:
                    reasons.append(f"unknown_{kind}_symbol:{symbol}")
            if kind == "feature" and policy["require_monotonic_feature_received_at_ns"] and not is_session and not is_summary:
                received = record.get("received_at_ns")
                if type(received) is not int or received <= 0:
                    reasons.append("invalid_feature_received_at_ns")
                else:
                    if previous_received is not None and received < previous_received:
                        reasons.append("feature_received_at_ns_regression")
                    previous_received = received
    raw_terminal = _capture_records(raw_path)[-1].get("session_terminal_v2")
    feature_terminal = _capture_records(feature_path)[-1].get("session_terminal_v2")
    if raw_terminal != feature_terminal:
        reasons.append("pair_ingestion_terminals_mismatch")
    return reasons


def _eligibility_unsigned(
    *,
    pair: Mapping[str, Any],
    policy: Mapping[str, Any],
    quality_identity: Mapping[str, Any] | None,
    quality_status: object,
    reasons: list[str],
    source_set: Mapping[str, Any],
    manifest_result: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = not reasons
    return {
        "schema": CAPTURE_ELIGIBILITY_SCHEMA,
        "analysis": "replay_eligibility_v2",
        "capture_id": pair["capture_id"],
        "eligibility_status": "ELIGIBLE" if eligible else "INELIGIBLE",
        "prospective_aggregation_eligible": eligible,
        "verification_status": "verified" if eligible else "verified_pair_but_ineligible",
        "ineligible_reasons": reasons,
        "policy_sha256": policy["policy_sha256"],
        "pair_manifest_sha256": pair["pair_manifest_sha256"],
        "raw_identity": pair["raw"]["identity"],
        "feature_identity": pair["features"]["identity"],
        "quality_identity": _normal_json(quality_identity, "quality_identity") if quality_identity is not None else None,
        "quality_status": quality_status if isinstance(quality_status, (str, type(None))) else None,
        "source_set": _normal_json(source_set, "source_set"),
        "manifest_result": _normal_json(manifest_result, "manifest_result"),
        "non_authority_claims": non_authority_claims(),
    }


def replay_eligibility_v2(
    manifest: Mapping[str, Any],
    raw_path: str | Path,
    feature_path: str | Path,
    *,
    eligibility_policy: Mapping[str, Any],
    quality_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Produce a hash-bound eligible/ineligible prospective replay decision.

    Missing, malformed, partial, or mismatched pairs raise before a decision can
    be published.  A fully verified pair that fails caller-declared structural
    rules is retained as an explicit ``INELIGIBLE`` result rather than discarded.
    """
    pair = validate_capture_pair_manifest_v2(manifest)
    verify_capture_pair_v2(pair, raw_path, feature_path)
    policy = _validate_eligibility_policy(eligibility_policy)
    reasons = _structural_eligibility_reasons(Path(raw_path), Path(feature_path), pair, policy)
    quality_identity, quality_reasons, quality_report = _quality_identity_and_reasons(
        quality_report_path, pair["features"]["identity"]["sha256"], policy
    )
    reasons.extend(quality_reasons)
    reasons = sorted(set(reasons))
    source_records = [
        build_source_record("capture_features", pair["features"]["identity"]),
        build_source_record("capture_raw", pair["raw"]["identity"]),
    ]
    if quality_identity is not None:
        source_records.append(build_source_record("capture_quality", quality_identity))
    source_set = build_canonical_source_set(source_records)
    outcome = "COMPLETE" if not reasons else "DIAGNOSTIC_ONLY"
    manifest_result = build_manifest_result(
        "capture_eligibility_v2", source_set, outcome,
        coverage=build_coverage_result(
            "capture_pair_artifacts", pair["capture_interval"],
            [
                {"observation_id": "features", "observation": observed_value(1)},
                {"observation_id": "raw", "observation": observed_value(1)},
            ],
        ),
        policy_sha256=policy["policy_sha256"],
        attributes={
            "capture_id": pair["capture_id"], "eligible": not reasons,
            "pair_manifest_sha256": pair["pair_manifest_sha256"],
        },
    )
    unsigned = _eligibility_unsigned(
        pair=pair, policy=policy, quality_identity=quality_identity,
        quality_status=quality_report.get("status") if quality_report is not None else None,
        reasons=reasons, source_set=source_set, manifest_result=manifest_result,
    )
    return {**unsigned, "eligibility_sha256": canonical_json_sha256(unsigned)}


def validate_replay_eligibility_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "replay_eligibility")
    expected = {
        "schema", "analysis", "capture_id", "eligibility_status", "prospective_aggregation_eligible",
        "verification_status", "ineligible_reasons", "policy_sha256", "pair_manifest_sha256",
        "raw_identity", "feature_identity", "quality_identity", "quality_status", "source_set",
        "manifest_result", "non_authority_claims", "eligibility_sha256",
    }
    _exact_keys(raw, expected, "replay_eligibility")
    if raw.get("schema") != CAPTURE_ELIGIBILITY_SCHEMA or raw.get("analysis") != "replay_eligibility_v2":
        raise DataIntegrityV2Error("replay eligibility schema or analysis is unsupported")
    eligible = raw.get("prospective_aggregation_eligible")
    if type(eligible) is not bool:
        raise DataIntegrityV2Error("prospective_aggregation_eligible must be boolean")
    if raw.get("eligibility_status") != ("ELIGIBLE" if eligible else "INELIGIBLE"):
        raise DataIntegrityV2Error("eligibility status does not match eligibility boolean")
    reasons = raw.get("ineligible_reasons")
    if not isinstance(reasons, list) or any(not isinstance(reason, str) or not reason for reason in reasons) or reasons != sorted(set(reasons)):
        raise DataIntegrityV2Error("ineligible_reasons must be a sorted unique string array")
    if eligible and reasons:
        raise DataIntegrityV2Error("eligible result cannot contain ineligible reasons")
    if not eligible and not reasons:
        raise DataIntegrityV2Error("ineligible result requires at least one reason")
    if raw.get("verification_status") != ("verified" if eligible else "verified_pair_but_ineligible"):
        raise DataIntegrityV2Error("verification_status does not match eligibility")
    source_set = validate_canonical_source_set(_mapping(raw.get("source_set"), "source_set"))
    manifest_result = validate_manifest_result(_mapping(raw.get("manifest_result"), "manifest_result"))
    claims = validate_non_authority_claims(_mapping(raw.get("non_authority_claims"), "non_authority_claims"))
    normalized = {
        "schema": CAPTURE_ELIGIBILITY_SCHEMA,
        "analysis": "replay_eligibility_v2",
        "capture_id": _string(raw.get("capture_id"), "capture_id"),
        "eligibility_status": raw["eligibility_status"],
        "prospective_aggregation_eligible": eligible,
        "verification_status": raw["verification_status"],
        "ineligible_reasons": reasons,
        "policy_sha256": _sha256(raw.get("policy_sha256"), "policy_sha256"),
        "pair_manifest_sha256": _sha256(raw.get("pair_manifest_sha256"), "pair_manifest_sha256"),
        "raw_identity": validate_file_identity(_mapping(raw.get("raw_identity"), "raw_identity")),
        "feature_identity": validate_file_identity(_mapping(raw.get("feature_identity"), "feature_identity")),
        "quality_identity": validate_file_identity(_mapping(raw["quality_identity"], "quality_identity")) if raw.get("quality_identity") is not None else None,
        "quality_status": raw.get("quality_status") if isinstance(raw.get("quality_status"), (str, type(None))) else None,
        "source_set": source_set,
        "manifest_result": manifest_result,
        "non_authority_claims": claims,
    }
    expected_hash = canonical_json_sha256(normalized)
    if _sha256(raw.get("eligibility_sha256"), "eligibility_sha256") != expected_hash:
        raise DataIntegrityV2Error("eligibility self-hash does not match")
    expected_sources = [
        build_source_record("capture_raw", normalized["raw_identity"]),
        build_source_record("capture_features", normalized["feature_identity"]),
    ]
    if normalized["quality_identity"] is not None:
        expected_sources.append(build_source_record("capture_quality", normalized["quality_identity"]))
    if source_set != build_canonical_source_set(expected_sources) or manifest_result["source_set"] != source_set:
        raise DataIntegrityV2Error("eligibility source_set does not bind exact artifact identities")
    if (manifest_result["policy_sha256"] != normalized["policy_sha256"]
            or manifest_result["outcome"] != ("COMPLETE" if eligible else "DIAGNOSTIC_ONLY")
            or manifest_result["attributes"] != {
                "capture_id": normalized["capture_id"], "eligible": eligible,
                "pair_manifest_sha256": normalized["pair_manifest_sha256"]}):
        raise DataIntegrityV2Error("eligibility manifest does not bind decision/policy/pair")
    return {**normalized, "eligibility_sha256": expected_hash}


def require_prospective_aggregation_eligible_v2(record: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed for legacy inspection and any v2 record not explicitly eligible."""
    if record.get("verification_status") == "legacy_unverified":
        raise DataIntegrityV2Error("legacy_unverified output is not eligible for prospective aggregation")
    normalized = validate_replay_eligibility_v2(record)
    if not normalized["prospective_aggregation_eligible"]:
        raise DataIntegrityV2Error("capture eligibility is INELIGIBLE for prospective aggregation")
    return normalized


def build_replay_selection_policy_v2(
    *, policy_id: str, declared_at_utc: str, selection_scope: str, capture_ids: Sequence[str]
) -> dict[str, Any]:
    """Build a deterministic pre-capture selection policy with no outcome field."""
    if selection_scope not in {"ALL_SCHEDULED_BATCHES", "CAPTURE_IDS"}:
        raise DataIntegrityV2Error("selection_scope must be ALL_SCHEDULED_BATCHES or CAPTURE_IDS")
    ids = [_string(value, "capture_ids item") for value in capture_ids]
    if len(ids) != len(set(ids)) or ids != sorted(ids):
        raise DataIntegrityV2Error("capture_ids must be sorted and unique")
    if selection_scope == "ALL_SCHEDULED_BATCHES" and ids:
        raise DataIntegrityV2Error("ALL_SCHEDULED_BATCHES requires an empty capture_ids list")
    if selection_scope == "CAPTURE_IDS" and not ids:
        raise DataIntegrityV2Error("CAPTURE_IDS requires at least one capture_id")
    unsigned = {
        "schema": REPLAY_SELECTION_POLICY_SCHEMA,
        "policy_id": _string(policy_id, "policy_id"),
        "declared_at_utc": _utc(declared_at_utc, "declared_at_utc"),
        "selection_scope": selection_scope,
        "capture_ids": ids,
    }
    return {**unsigned, "policy_sha256": canonical_json_sha256(unsigned)}


def _validate_selection_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(policy, "replay_selection_policy")
    _exact_keys(raw, {"schema", "policy_id", "declared_at_utc", "selection_scope", "capture_ids", "policy_sha256"}, "replay_selection_policy")
    if raw.get("schema") != REPLAY_SELECTION_POLICY_SCHEMA:
        raise DataIntegrityV2Error("replay selection policy schema is unsupported")
    rebuilt = build_replay_selection_policy_v2(
        policy_id=_string(raw.get("policy_id"), "policy_id"),
        declared_at_utc=_utc(raw.get("declared_at_utc"), "declared_at_utc"),
        selection_scope=raw.get("selection_scope"),
        capture_ids=raw.get("capture_ids") if isinstance(raw.get("capture_ids"), list) else [],
    )
    if _sha256(raw.get("policy_sha256"), "replay_selection_policy.policy_sha256") != rebuilt["policy_sha256"]:
        raise DataIntegrityV2Error("replay selection policy self-hash does not match")
    return rebuilt


def build_replay_availability_record_v2(
    *,
    capture_id: str,
    selection_policy: Mapping[str, Any],
    selection_policy_identity: Mapping[str, Any],
    retention_deadline_utc: str,
    raw_path: str | Path | None = None,
    feature_path: str | Path | None = None,
    pair_manifest: Mapping[str, Any] | None = None,
    artifact_name: str | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Record replayability for every batch without fabricating durable storage.

    A record can be ``NONREPLAYABLE`` with only the immutable policy file as a
    source.  When all three pair inputs are available they must verify exactly;
    successful status is explicitly limited to currently checked local bytes.
    """
    normalized_id = _string(capture_id, "capture_id")
    policy = _validate_selection_policy(selection_policy)
    policy_identity = validate_file_identity(_mapping(selection_policy_identity, "selection_policy_identity"))
    deadline = _utc(retention_deadline_utc, "retention_deadline_utc")
    required = policy["selection_scope"] == "ALL_SCHEDULED_BATCHES" or normalized_id in policy["capture_ids"]
    source_records = [build_source_record("capture_replay_selection_policy", policy_identity)]
    reasons: list[str] = []
    raw_identity: dict[str, Any] | None = None
    feature_identity: dict[str, Any] | None = None
    pair_hash: str | None = None
    pair_coverage: Mapping[str, Any] | None = None
    if raw_path is None:
        reasons.append("raw_not_retained_or_not_supplied")
    elif Path(raw_path).is_file():
        raw_identity = build_file_identity(raw_path, logical_name=Path(raw_path).name)
        source_records.append(build_source_record("capture_raw", raw_identity))
    else:
        reasons.append("raw_not_retained_or_not_supplied")
    if feature_path is None:
        reasons.append("features_not_retained_or_not_supplied")
    elif Path(feature_path).is_file():
        feature_identity = build_file_identity(feature_path, logical_name=Path(feature_path).name)
        source_records.append(build_source_record("capture_features", feature_identity))
    else:
        reasons.append("features_not_retained_or_not_supplied")
    if pair_manifest is None:
        reasons.append("capture_pair_marker_missing")
    elif raw_identity is not None and feature_identity is not None:
        try:
            verified_pair = validate_capture_pair_manifest_v2(pair_manifest)
            if verified_pair["capture_id"] != normalized_id:
                raise DataIntegrityV2Error("capture id mismatch")
            verify_capture_pair_v2(verified_pair, raw_path, feature_path)
            pair_hash = verified_pair["pair_manifest_sha256"]
            pair_coverage = verified_pair["manifest_result"]["coverage"]
        except DataIntegrityV2Error:
            reasons.append("capture_pair_not_verifiable")
    else:
        reasons.append("capture_pair_not_verifiable")
    if required and reasons:
        reasons.append("required_replay_pair_unavailable")
    if artifact_name is not None:
        artifact_name = _string(artifact_name, "artifact_name")
    if artifact_id is not None:
        artifact_id = _string(artifact_id, "artifact_id")
    reasons = sorted(set(reasons))
    replayable = not reasons
    source_set = build_canonical_source_set(source_records)
    manifest_result = build_manifest_result(
        "capture_replay_availability_v2", source_set,
        "COMPLETE" if replayable else "DIAGNOSTIC_ONLY",
        coverage=pair_coverage,
        policy_sha256=policy["policy_sha256"],
        attributes={
            "capture_id": normalized_id,
            "replay_pair_required": required,
            "replayability_status": "REPLAYABLE_LOCAL_BYTES" if replayable else "NONREPLAYABLE",
        },
    )
    unsigned = {
        "schema": REPLAY_AVAILABILITY_SCHEMA,
        "analysis": "capture_replay_availability_v2",
        "capture_id": normalized_id,
        "selection_policy_sha256": policy["policy_sha256"],
        "selection_policy_identity": policy_identity,
        "replay_pair_required": required,
        "retention_deadline_utc": deadline,
        "artifact_name": artifact_name,
        "artifact_id": artifact_id,
        "raw_identity": raw_identity,
        "feature_identity": feature_identity,
        "pair_manifest_sha256": pair_hash,
        "raw_replay_available": replayable,
        "replayability_status": "REPLAYABLE_LOCAL_BYTES" if replayable else "NONREPLAYABLE",
        "nonreplayable_reasons": reasons,
        "source_set": source_set,
        "manifest_result": manifest_result,
        "verification_scope": "current_local_bytes_only",
        "non_authority_claims": non_authority_claims(),
    }
    return {**unsigned, "availability_sha256": canonical_json_sha256(unsigned)}


def validate_replay_availability_record_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "replay_availability")
    expected = {
        "schema", "analysis", "capture_id", "selection_policy_sha256", "selection_policy_identity",
        "replay_pair_required", "retention_deadline_utc", "artifact_name", "artifact_id", "raw_identity", "feature_identity",
        "pair_manifest_sha256", "raw_replay_available", "replayability_status", "nonreplayable_reasons",
        "source_set", "manifest_result", "verification_scope", "non_authority_claims", "availability_sha256",
    }
    _exact_keys(raw, expected, "replay_availability")
    if raw.get("schema") != REPLAY_AVAILABILITY_SCHEMA or raw.get("analysis") != "capture_replay_availability_v2":
        raise DataIntegrityV2Error("replay availability schema or analysis is unsupported")
    replayable = raw.get("raw_replay_available")
    if type(replayable) is not bool:
        raise DataIntegrityV2Error("raw_replay_available must be boolean")
    if raw.get("replayability_status") != ("REPLAYABLE_LOCAL_BYTES" if replayable else "NONREPLAYABLE"):
        raise DataIntegrityV2Error("replayability status does not match availability")
    reasons = raw.get("nonreplayable_reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons) or reasons != sorted(set(reasons)):
        raise DataIntegrityV2Error("nonreplayable_reasons must be a sorted unique string array")
    if replayable and reasons:
        raise DataIntegrityV2Error("replayable local bytes cannot carry nonreplayable reasons")
    if not replayable and not reasons:
        raise DataIntegrityV2Error("nonreplayable record must name a reason")
    normalized = {
        "schema": REPLAY_AVAILABILITY_SCHEMA,
        "analysis": "capture_replay_availability_v2",
        "capture_id": _string(raw.get("capture_id"), "capture_id"),
        "selection_policy_sha256": _sha256(raw.get("selection_policy_sha256"), "selection_policy_sha256"),
        "selection_policy_identity": validate_file_identity(_mapping(raw.get("selection_policy_identity"), "selection_policy_identity")),
        "replay_pair_required": raw.get("replay_pair_required"),
        "retention_deadline_utc": _utc(raw.get("retention_deadline_utc"), "retention_deadline_utc"),
        "artifact_name": _string(raw["artifact_name"], "artifact_name") if raw.get("artifact_name") is not None else None,
        "artifact_id": _string(raw["artifact_id"], "artifact_id") if raw.get("artifact_id") is not None else None,
        "raw_identity": validate_file_identity(_mapping(raw["raw_identity"], "raw_identity")) if raw.get("raw_identity") is not None else None,
        "feature_identity": validate_file_identity(_mapping(raw["feature_identity"], "feature_identity")) if raw.get("feature_identity") is not None else None,
        "pair_manifest_sha256": _sha256(raw["pair_manifest_sha256"], "pair_manifest_sha256") if raw.get("pair_manifest_sha256") is not None else None,
        "raw_replay_available": replayable,
        "replayability_status": raw["replayability_status"],
        "nonreplayable_reasons": reasons,
        "source_set": validate_canonical_source_set(_mapping(raw.get("source_set"), "source_set")),
        "manifest_result": validate_manifest_result(_mapping(raw.get("manifest_result"), "manifest_result")),
        "verification_scope": "current_local_bytes_only",
        "non_authority_claims": validate_non_authority_claims(_mapping(raw.get("non_authority_claims"), "non_authority_claims")),
    }
    if type(normalized["replay_pair_required"]) is not bool:
        raise DataIntegrityV2Error("replay_pair_required must be boolean")
    expected_hash = canonical_json_sha256(normalized)
    if _sha256(raw.get("availability_sha256"), "availability_sha256") != expected_hash:
        raise DataIntegrityV2Error("availability self-hash does not match")
    return {**normalized, "availability_sha256": expected_hash}


def _run_legacy_replay_to_partial(
    raw_path: Path, work_path: Path, *, trade_window_seconds: float, imbalance_levels: int
) -> tuple[int, list[Mapping[str, Any]]]:
    """Use the established offline engine only under a non-final work filename."""
    if work_path.exists() or work_path.with_name(work_path.name + ".manifest.json").exists():
        raise DataIntegrityV2Error(f"strict replay work path already exists: {work_path}")
    from orderflow_edge_lab.cli.mexc_replay import replay as legacy_replay

    emitted = legacy_replay(
        raw_path, work_path,
        trade_window_seconds=trade_window_seconds, imbalance_levels=imbalance_levels,
    )
    return emitted, list(iter_jsonl(work_path))


def strict_replay_v2(
    manifest: Mapping[str, Any],
    raw_path: str | Path,
    feature_path: str | Path,
    output_path: str | Path,
    *,
    eligibility_policy: Mapping[str, Any],
    quality_report_path: str | Path | None = None,
    trade_window_seconds: float = 10.0,
    imbalance_levels: int = 10,
) -> dict[str, Any]:
    """Replay only a verified eligible pair and publish a provenance-bound output.

    Pair marker/byte/terminal/policy checks all complete before the requested
    output is opened.  The pre-existing replay algorithm is invoked only into a
    ``.partial`` work file, then its feature records are wrapped in a v2 session
    record carrying exact raw and pair identities before a final atomic rename.
    """
    if trade_window_seconds <= 0 or imbalance_levels < 1:
        raise DataIntegrityV2Error("strict replay parameters must be positive")
    pair = validate_capture_pair_manifest_v2(manifest)
    eligibility = replay_eligibility_v2(
        pair, raw_path, feature_path,
        eligibility_policy=eligibility_policy, quality_report_path=quality_report_path,
    )
    require_prospective_aggregation_eligible_v2(eligibility)
    target = Path(output_path)
    if target.exists():
        raise DataIntegrityV2Error(f"refusing to overwrite existing output: {target}")
    raw_target = Path(raw_path)
    work_path = target.with_name(target.name + ".strict-replay-work.partial")
    if pair["raw"]["session_schema_version"] >= 3:
        normalized_events = [
            {**record["payload"], "record_type": "feature"}
            for record in _capture_records(raw_target)
            if record.get("record_type") == "raw_frame_received"
            and isinstance(record.get("payload"), Mapping)
            and record["payload"].get("event_type") in {"snapshot", "depth", "trade"}
        ]
        captured_events = [record for record in _capture_records(Path(feature_path)) if record.get("record_type") == "feature"]
        if normalized_events != captured_events:
            raise DataIntegrityV2Error("v3 raw receipt reconstruction does not match captured features")
        emitted = len(normalized_events)
        legacy_records = [{"record_type": "replay_session", "feature_schema_version": 3}, *normalized_events]
    else:
        emitted, legacy_records = _run_legacy_replay_to_partial(
            raw_target, work_path,
            trade_window_seconds=trade_window_seconds, imbalance_levels=imbalance_levels,
        )
    if not legacy_records or legacy_records[0].get("record_type") != "replay_session":
        raise DataIntegrityV2Error("legacy replay did not produce a replay_session")
    session = {
        "record_type": "strict_replay_session",
        "schema": STRICT_REPLAY_SCHEMA,
        "analysis": "mexc_strict_replay_v2",
        "verification_status": "verified",
        "prospective_aggregation_eligible": True,
        "capture_id": pair["capture_id"],
        "pair_manifest_sha256": pair["pair_manifest_sha256"],
        "eligibility_sha256": eligibility["eligibility_sha256"],
        "raw_identity": pair["raw"]["identity"],
        "feature_identity": pair["features"]["identity"],
        "source_session_schema_version": pair["raw"]["session_schema_version"],
        "feature_schema_version": legacy_records[0].get("feature_schema_version"),
        "trade_window_seconds": trade_window_seconds,
        "imbalance_levels": imbalance_levels,
        "source_set": eligibility["source_set"],
        "verification_scope": "verified_local_bytes_and_terminal_structure_only",
        "non_authority_claims": non_authority_claims(),
    }
    _write_jsonl_atomic(target, [session, *legacy_records[1:]])
    # Work output is an implementation detail rather than a usable evidence file.
    work_path.unlink(missing_ok=True)
    work_path.with_name(work_path.name + ".manifest.json").unlink(missing_ok=True)
    return {"output": str(target), "features_emitted": emitted, "session": session}


def legacy_inspect_replay_v2(
    raw_path: str | Path,
    output_path: str | Path,
    *,
    trade_window_seconds: float = 10.0,
    imbalance_levels: int = 10,
) -> dict[str, Any]:
    """Run an explicitly non-eligible legacy inspection path; never a strict fallback."""
    if trade_window_seconds <= 0 or imbalance_levels < 1:
        raise DataIntegrityV2Error("legacy inspection parameters must be positive")
    target = Path(output_path)
    if target.exists():
        raise DataIntegrityV2Error(f"refusing to overwrite existing output: {target}")
    raw_target = Path(raw_path)
    work_path = target.with_name(target.name + ".legacy-inspect-work.partial")
    raw_records = _capture_records(raw_target)
    if not raw_records or raw_records[0].get("record_type") != "session":
        raise DataIntegrityV2Error("inspection input must begin with a session")
    source_schema = raw_records[0].get("schema_version", 1)
    if type(source_schema) is not int or source_schema not in {1, 2, 3}:
        raise DataIntegrityV2Error("unsupported inspection source schema")
    if source_schema == 3:
        # These are caller-supplied normalized receipt payloads, not verified
        # reconstructed market data.  No pair/terminal eligibility is inferred.
        inspection_records = [
            {**record["payload"], "record_type": "feature"}
            for record in raw_records[1:]
            if record.get("record_type") == "raw_frame_received"
            and isinstance(record.get("payload"), Mapping)
            and record["payload"].get("event_type") in {"snapshot", "depth", "trade"}
        ]
        emitted = len(inspection_records)
        legacy_records = [{"record_type": "replay_session", "feature_schema_version": 3}, *inspection_records]
    else:
        emitted, legacy_records = _run_legacy_replay_to_partial(
            raw_target, work_path,
            trade_window_seconds=trade_window_seconds, imbalance_levels=imbalance_levels,
        )
    if not legacy_records or legacy_records[0].get("record_type") != "replay_session":
        raise DataIntegrityV2Error("legacy replay did not produce a replay_session")
    session = {
        "record_type": "legacy_inspection_session",
        "schema": STRICT_REPLAY_SCHEMA,
        "analysis": "mexc_legacy_inspection_v2",
        "verification_status": "legacy_unverified",
        "prospective_aggregation_eligible": False,
        "source_file": raw_target.name,
        "source_local_identity": build_file_identity(raw_target, logical_name=raw_target.name),
        "source_session_schema_version": source_schema,
        "inspection_adapter": "unverified_v3_receipt_payloads" if source_schema == 3 else "legacy_replay_engine",
        "trade_window_seconds": trade_window_seconds,
        "imbalance_levels": imbalance_levels,
        "verification_scope": "legacy_inspection_only",
        "non_authority_claims": non_authority_claims(),
    }
    _write_jsonl_atomic(target, [session, *legacy_records[1:]])
    work_path.unlink(missing_ok=True)
    work_path.with_name(work_path.name + ".manifest.json").unlink(missing_ok=True)
    return {"output": str(target), "features_emitted": emitted, "session": session}


def build_state_report_integrity_binding_v2(
    state_report_path: str | Path, eligibility: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind a new state-report sidecar to verified raw/features/quality/eligibility.

    Existing v1 state reports are intentionally untouched.  This new companion
    artifact allows a prospective consumer to reject a report that lacks its
    capture-pair and eligibility identities.
    """
    decision = require_prospective_aggregation_eligible_v2(eligibility)
    state_identity = build_file_identity(state_report_path, logical_name=Path(state_report_path).name)
    sources = [
        build_source_record("capture_features", decision["feature_identity"]),
        build_source_record("capture_raw", decision["raw_identity"]),
        build_source_record("state_report", state_identity),
    ]
    if decision["quality_identity"] is not None:
        sources.append(build_source_record("capture_quality", decision["quality_identity"]))
    source_set = build_canonical_source_set(sources)
    unsigned = {
        "schema": "orderflow_edge_lab.state_report_integrity_binding.v2",
        "analysis": "state_report_integrity_binding_v2",
        "state_report_identity": state_identity,
        "capture_id": decision["capture_id"],
        "raw_identity": decision["raw_identity"],
        "feature_identity": decision["feature_identity"],
        "quality_identity": decision["quality_identity"],
        "eligibility_sha256": decision["eligibility_sha256"],
        "eligibility_policy_sha256": decision["policy_sha256"],
        "pair_manifest_sha256": decision["pair_manifest_sha256"],
        "source_set": source_set,
        "non_authority_claims": non_authority_claims(),
    }
    return {**unsigned, "binding_sha256": canonical_json_sha256(unsigned)}


def _read_json(path: str | Path, field: str) -> Mapping[str, Any]:
    return _json_object_file(path, field)


def _emit_json(value: Mapping[str, Any], output: Path | None) -> None:
    if output is None:
        print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    else:
        _write_json_exclusive_atomic(output, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline opt-in v2 capture-pair verification, eligibility, and strict replay. No network or trading actions."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-pair", help="verify a final pair marker and local raw/features before use")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--raw", type=Path, required=True)
    verify.add_argument("--features", type=Path, required=True)
    verify.add_argument("--output", type=Path)
    eligibility = commands.add_parser("eligibility", help="produce an eligible/ineligible structural replay decision")
    for item in (eligibility,):
        item.add_argument("--manifest", type=Path, required=True)
        item.add_argument("--raw", type=Path, required=True)
        item.add_argument("--features", type=Path, required=True)
        item.add_argument("--policy", type=Path, required=True)
        item.add_argument("--quality-report", type=Path)
        item.add_argument("--output", type=Path, required=True)
    strict = commands.add_parser("strict-replay", help="verify pair and eligibility before publishing replay output")
    strict.add_argument("--manifest", type=Path, required=True)
    strict.add_argument("--raw", type=Path, required=True)
    strict.add_argument("--features", type=Path, required=True)
    strict.add_argument("--policy", type=Path, required=True)
    strict.add_argument("--quality-report", type=Path)
    strict.add_argument("--output", type=Path, required=True)
    strict.add_argument("--trade-window-seconds", type=float, default=10.0)
    strict.add_argument("--imbalance-levels", type=int, default=10)
    legacy = commands.add_parser("legacy-inspect", help="explicitly replay legacy raw input as aggregation-ineligible inspection")
    legacy.add_argument("--raw", type=Path, required=True)
    legacy.add_argument("--output", type=Path, required=True)
    legacy.add_argument("--trade-window-seconds", type=float, default=10.0)
    legacy.add_argument("--imbalance-levels", type=int, default=10)
    availability = commands.add_parser("availability", help="record deterministic replay availability or nonreplayability for one batch")
    availability.add_argument("--capture-id", required=True)
    availability.add_argument("--selection-policy", type=Path, required=True)
    availability.add_argument("--retention-deadline-utc", required=True)
    availability.add_argument("--raw", type=Path)
    availability.add_argument("--features", type=Path)
    availability.add_argument("--manifest", type=Path)
    availability.add_argument("--artifact-name")
    availability.add_argument("--artifact-id")
    availability.add_argument("--output", type=Path, required=True)
    bind = commands.add_parser("bind-state-report", help="write a v2 state-report identity sidecar from an eligible decision")
    bind.add_argument("--state-report", type=Path, required=True)
    bind.add_argument("--eligibility", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    aggregate = commands.add_parser("validate-aggregation-input", help="fail unless an eligibility result is explicitly prospective-eligible")
    aggregate.add_argument("eligibility", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-pair":
            result = verify_capture_pair_v2(load_capture_pair_manifest_v2(args.manifest), args.raw, args.features)
            _emit_json(result, args.output)
        elif args.command == "eligibility":
            result = replay_eligibility_v2(
                load_capture_pair_manifest_v2(args.manifest), args.raw, args.features,
                eligibility_policy=_read_json(args.policy, "eligibility policy"), quality_report_path=args.quality_report,
            )
            _emit_json(result, args.output)
        elif args.command == "strict-replay":
            result = strict_replay_v2(
                load_capture_pair_manifest_v2(args.manifest), args.raw, args.features, args.output,
                eligibility_policy=_read_json(args.policy, "eligibility policy"), quality_report_path=args.quality_report,
                trade_window_seconds=args.trade_window_seconds, imbalance_levels=args.imbalance_levels,
            )
            print(json.dumps({"output": result["output"], "features_emitted": result["features_emitted"]}, sort_keys=True))
        elif args.command == "legacy-inspect":
            result = legacy_inspect_replay_v2(
                args.raw, args.output, trade_window_seconds=args.trade_window_seconds, imbalance_levels=args.imbalance_levels,
            )
            print(json.dumps({"output": result["output"], "features_emitted": result["features_emitted"], "verification_status": "legacy_unverified"}, sort_keys=True))
        elif args.command == "availability":
            policy = _read_json(args.selection_policy, "selection policy")
            result = build_replay_availability_record_v2(
                capture_id=args.capture_id,
                selection_policy=policy,
                selection_policy_identity=build_file_identity(args.selection_policy, logical_name=args.selection_policy.name),
                retention_deadline_utc=args.retention_deadline_utc,
                raw_path=args.raw, feature_path=args.features,
                pair_manifest=load_capture_pair_manifest_v2(args.manifest) if args.manifest is not None else None,
                artifact_name=args.artifact_name, artifact_id=args.artifact_id,
            )
            _emit_json(result, args.output)
        elif args.command == "bind-state-report":
            _emit_json(build_state_report_integrity_binding_v2(args.state_report, _read_json(args.eligibility, "eligibility")), args.output)
        elif args.command == "validate-aggregation-input":
            result = require_prospective_aggregation_eligible_v2(_read_json(args.eligibility, "eligibility"))
            print(json.dumps({"capture_id": result["capture_id"], "status": "ELIGIBLE_FOR_PROSPECTIVE_AGGREGATION"}, sort_keys=True))
        else:
            raise AssertionError("unreachable")
        return 0
    except (DataIntegrityV2Error, ContractValidationError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "INVALID_OR_INELIGIBLE"}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc


class ResearchProtocolError(ValueError):
    pass


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ResearchProtocolError("timestamp must be a nonempty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchProtocolError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ResearchProtocolError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _source_from_audit(report: dict[str, Any], audit_path: Path) -> dict[str, Any]:
    if report.get("schema_version") != 2:
        raise ResearchProtocolError(f"export audit schema v2 required: {audit_path}")
    timestamps = report.get("timestamps")
    if not isinstance(timestamps, dict):
        raise ResearchProtocolError(f"audit missing timestamps metadata: {audit_path}")
    digest = report.get("source_sha256")
    if not _valid_sha256(digest):
        raise ResearchProtocolError(f"audit has invalid source sha256: {audit_path}")
    minimum = timestamps.get("minimum")
    maximum = timestamps.get("maximum")
    if not isinstance(minimum, str) or not isinstance(maximum, str):
        raise ResearchProtocolError(f"audit lacks parsed timestamp range: {audit_path}")
    start = _parse_utc(minimum)
    end = _parse_utc(maximum)
    if end < start:
        raise ResearchProtocolError(f"audit timestamp range is reversed: {audit_path}")
    eligibility = report.get("research_eligibility")
    return {
        "audit_path": str(audit_path),
        "audit_sha256": _canonical_sha256(report),
        "source_name": report.get("source_file"),
        "source_sha256": str(digest).lower(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "row_count": report.get("rows"),
        "symbols": report.get("symbols"),
        "trade_flow_eligible": eligibility.get("trade_flow") if isinstance(eligibility, dict) else None,
        "bbo_ofi_eligible": eligibility.get("bbo_ofi") if isinstance(eligibility, dict) else None,
    }


def classify_timestamp(
    timestamp: datetime,
    *,
    discovery_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    embargo: timedelta,
) -> str:
    ts = timestamp.astimezone(UTC)
    if ts <= discovery_end:
        return "discovery"
    if ts <= discovery_end + embargo:
        return "embargo_discovery_validation"
    if ts <= validation_end:
        return "validation"
    if ts <= validation_end + embargo:
        return "embargo_validation_holdout"
    if ts <= holdout_end:
        return "holdout"
    return "post_holdout"


def build_research_freeze(
    audit_reports: Iterable[tuple[Path, dict[str, Any]]],
    *,
    discovery_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    embargo_seconds: int = 0,
    protocol_name: str = "default",
) -> dict[str, Any]:
    discovery_end = discovery_end.astimezone(UTC)
    validation_end = validation_end.astimezone(UTC)
    holdout_end = holdout_end.astimezone(UTC)
    if type(embargo_seconds) is not int or embargo_seconds < 0:
        raise ResearchProtocolError("embargo_seconds must be a nonnegative integer")
    embargo = timedelta(seconds=embargo_seconds)
    if not discovery_end < validation_end < holdout_end:
        raise ResearchProtocolError("require discovery_end < validation_end < holdout_end")
    if discovery_end + embargo >= validation_end:
        raise ResearchProtocolError("discovery embargo consumes validation period")
    if validation_end + embargo >= holdout_end:
        raise ResearchProtocolError("validation embargo consumes holdout period")
    if not isinstance(protocol_name, str) or not protocol_name.strip():
        raise ResearchProtocolError("protocol_name must be nonempty")

    sources = [_source_from_audit(report, path) for path, report in audit_reports]
    if not sources:
        raise ResearchProtocolError("at least one export audit is required")
    source_hashes = [source["source_sha256"] for source in sources]
    if len(source_hashes) != len(set(source_hashes)):
        raise ResearchProtocolError("duplicate source bytes are not allowed")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": protocol_name.strip(),
        "partition_policy": {
            "discovery_end": discovery_end.isoformat(),
            "validation_start_exclusive": (discovery_end + embargo).isoformat(),
            "validation_end": validation_end.isoformat(),
            "holdout_start_exclusive": (validation_end + embargo).isoformat(),
            "holdout_end": holdout_end.isoformat(),
            "embargo_seconds": embargo_seconds,
        },
        "sources": sorted(sources, key=lambda row: (row["start"], row["source_sha256"])),
        "rules": [
            "Strategy design and feature selection may use discovery data only.",
            "Validation may be inspected for candidate rejection or promotion decisions but must not be relabeled as holdout evidence after tuning.",
            "Holdout remains untouched until the candidate specification and decision thresholds are frozen.",
            "Embargo intervals are excluded from model fitting and performance claims.",
            "Any source-byte change requires a new research freeze manifest.",
        ],
        "verified_out_of_sample_evidence": False,
        "live_order_transmission_supported": False,
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def load_audit(path: str | Path) -> tuple[Path, dict[str, Any]]:
    audit_path = Path(path)
    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchProtocolError(f"cannot read audit JSON: {audit_path}") from exc
    if not isinstance(payload, dict):
        raise ResearchProtocolError(f"audit JSON must be an object: {audit_path}")
    return audit_path, payload


def verify_freeze(manifest: dict[str, Any]) -> bool:
    if manifest.get("schema_version") != 1:
        return False
    expected = manifest.get("manifest_sha256")
    if not _valid_sha256(expected):
        return False
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected

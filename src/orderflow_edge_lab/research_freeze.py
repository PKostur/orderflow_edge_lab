from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


UTC = timezone.utc


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_aware(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError(f"{field} must be timezone aware")
    return dt.astimezone(UTC)


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("freeze time must be timezone aware")
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_research_freeze(
    strategy_config: str | Path,
    *,
    frozen_at: datetime | None = None,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    path = Path(strategy_config)
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("strategy config must be valid UTF-8 JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("strategy config must be a JSON object")

    when = frozen_at or datetime.now(tz=UTC)
    body: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "prospective_out_of_sample_registration",
        "frozen_at_utc": _utc_iso(when),
        "strategy_id": strategy_id,
        "strategy_config": {
            "name": path.name,
            "sha256": _sha256_bytes(raw),
            "canonical_json_sha256": _sha256_bytes(_canonical(parsed).encode("utf-8")),
        },
        "rules": {
            "dataset_first_event_must_be_after_freeze": True,
            "strategy_config_hash_must_remain_unchanged": True,
            "passing_data_quality_is_not_profitability_evidence": True,
        },
    }
    body["registration_sha256"] = _sha256_bytes(_canonical(body).encode("utf-8"))
    return body


def validate_research_freeze(freeze: object) -> dict[str, Any]:
    if not isinstance(freeze, dict):
        raise ValueError("research freeze must be a JSON object")
    item = dict(freeze)
    supplied = item.pop("registration_sha256", None)
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise ValueError("research freeze has no valid registration hash")
    if _sha256_bytes(_canonical(item).encode("utf-8")) != supplied:
        raise ValueError("research freeze registration hash mismatch")
    if item.get("schema_version") != 1 or item.get("purpose") != "prospective_out_of_sample_registration":
        raise ValueError("unsupported research freeze schema")
    _parse_aware(item.get("frozen_at_utc"), "frozen_at_utc")
    config = item.get("strategy_config")
    if not isinstance(config, dict):
        raise ValueError("research freeze is missing strategy_config")
    for key in ("sha256", "canonical_json_sha256"):
        digest = config.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"invalid strategy_config {key}")
    return dict(freeze)


def verify_strategy_config(freeze: Mapping[str, Any], strategy_config: str | Path) -> bool:
    validate_research_freeze(dict(freeze))
    raw = Path(strategy_config).read_bytes()
    expected = freeze["strategy_config"]["sha256"]
    return _sha256_bytes(raw) == expected


def audit_prospective_dataset(
    freeze: Mapping[str, Any],
    export_audit: Mapping[str, Any],
    *,
    require_ofi: bool = False,
) -> dict[str, Any]:
    validate_research_freeze(dict(freeze))
    frozen_at = _parse_aware(freeze["frozen_at_utc"], "frozen_at_utc")

    if export_audit.get("schema_version") != 1:
        raise ValueError("unsupported export audit schema")
    time_range = export_audit.get("time_range")
    if not isinstance(time_range, Mapping):
        raise ValueError("export audit is missing time_range; regenerate it with the current auditor")
    first_event = _parse_aware(time_range.get("first_event_utc"), "time_range.first_event_utc")
    last_event = _parse_aware(time_range.get("last_event_utc"), "time_range.last_event_utc")
    if last_event < first_event:
        raise ValueError("export audit time range is inverted")

    eligibility = export_audit.get("research_eligibility")
    if not isinstance(eligibility, Mapping):
        raise ValueError("export audit is missing research_eligibility")
    structural_ok = bool(eligibility.get("bbo_ofi" if require_ofi else "trade_flow"))
    prospective = first_event > frozen_at
    source_sha = export_audit.get("source_sha256")
    source_hash_valid = isinstance(source_sha, str) and len(source_sha) == 64 and all(c in "0123456789abcdef" for c in source_sha)

    failures: list[str] = []
    if not prospective:
        failures.append("dataset_not_prospective_to_strategy_freeze")
    if not structural_ok:
        failures.append("dataset_failed_required_structural_quality_gate")
    if not source_hash_valid:
        failures.append("dataset_source_hash_missing_or_invalid")

    duration = (last_event - first_event).total_seconds()
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("invalid export audit duration")

    return {
        "schema_version": 1,
        "freeze_registration_sha256": freeze["registration_sha256"],
        "strategy_config_sha256": freeze["strategy_config"]["sha256"],
        "dataset_source_sha256": source_sha,
        "required_research_mode": "bbo_ofi" if require_ofi else "trade_flow",
        "frozen_at_utc": freeze["frozen_at_utc"],
        "dataset_first_event_utc": time_range["first_event_utc"],
        "dataset_last_event_utc": time_range["last_event_utc"],
        "dataset_duration_seconds": duration,
        "prospective": prospective,
        "structural_quality_passed": structural_ok,
        "passed": not failures,
        "failures": failures,
        "interpretation": (
            "A pass establishes prospective registration and structural data eligibility only. "
            "It does not establish statistical significance, economic significance, or profitability."
        ),
    }

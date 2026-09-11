"""Fail-closed analysis for DeepCharts/dxFeed endpoint watcher reports.

A watcher capture can identify likely network peers used by DeepCharts. It cannot
establish that an endpoint is an externally usable API, that credentials are valid,
or that the user's entitlement permits independent access.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
from typing import Any, Mapping


UTC = timezone.utc
_ALLOWED_CONFIDENCE = {"high", "medium", "low", "unclassified"}


class EndpointCaptureError(ValueError):
    """Raised when a capture is malformed or violates the safe capture contract."""


@dataclass(frozen=True)
class RankedEndpoint:
    process_name: str
    pid: int
    remote_address: str
    remote_port: int
    reverse_dns: str | None
    confidence: str
    evidence: tuple[str, ...]
    samples_seen: int
    score: int
    reasons: tuple[str, ...]


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EndpointCaptureError(f"{field} must be a timestamp string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EndpointCaptureError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise EndpointCaptureError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _require_bool(report: Mapping[str, Any], field: str, expected: bool) -> None:
    value = report.get(field)
    if type(value) is not bool or value is not expected:
        raise EndpointCaptureError(f"{field} must be {str(expected).lower()}")


def _score_observation(row: Mapping[str, Any]) -> RankedEndpoint:
    try:
        process_name = str(row["process_name"]).strip()
        pid = int(row["pid"])
        address = str(ipaddress.ip_address(str(row["remote_address"]).strip()))
        port = int(row["remote_port"])
        confidence = str(row["confidence"]).strip().lower()
        samples_seen = int(row["samples_seen"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise EndpointCaptureError("observation contains invalid identity fields") from exc
    if not process_name or pid <= 0 or not 1 <= port <= 65535 or samples_seen <= 0:
        raise EndpointCaptureError("observation contains out-of-range identity fields")
    if confidence not in _ALLOWED_CONFIDENCE:
        raise EndpointCaptureError("observation confidence is invalid")

    reverse_dns_raw = row.get("reverse_dns")
    if reverse_dns_raw is None:
        reverse_dns = None
    elif isinstance(reverse_dns_raw, str):
        reverse_dns = reverse_dns_raw.strip().rstrip(".").lower() or None
    else:
        raise EndpointCaptureError("reverse_dns must be a string or null")

    raw_evidence = row.get("evidence", [])
    if not isinstance(raw_evidence, list) or any(not isinstance(item, str) for item in raw_evidence):
        raise EndpointCaptureError("observation evidence must be a list of strings")
    evidence = tuple(sorted(set(item.strip() for item in raw_evidence if item.strip())))

    first_seen = _parse_utc(row.get("first_seen_utc"), "first_seen_utc")
    last_seen = _parse_utc(row.get("last_seen_utc"), "last_seen_utc")
    if last_seen < first_seen:
        raise EndpointCaptureError("observation last_seen_utc precedes first_seen_utc")

    score = 0
    reasons: list[str] = []
    if reverse_dns and "dxfeed" in reverse_dns:
        score += 100
        reasons.append("reverse_dns_contains_dxfeed")
    if port == 7300:
        score += 45
        reasons.append("native_demo_port_indicator")
    if port == 443:
        score += 10
        reasons.append("generic_tls_port")
    if samples_seen >= 3:
        score += 5
        reasons.append("repeated_observation")

    # Trust independently derivable facts over a producer supplied confidence label.
    if "reverse_dns_contains_dxfeed" in evidence and not (reverse_dns and "dxfeed" in reverse_dns):
        raise EndpointCaptureError("dxFeed DNS evidence is inconsistent with reverse_dns")
    if "remote_port_7300" in evidence and port != 7300:
        raise EndpointCaptureError("port evidence is inconsistent with remote_port")
    if "tls_port_443" in evidence and port != 443:
        raise EndpointCaptureError("TLS evidence is inconsistent with remote_port")

    return RankedEndpoint(
        process_name=process_name,
        pid=pid,
        remote_address=address,
        remote_port=port,
        reverse_dns=reverse_dns,
        confidence=confidence,
        evidence=evidence,
        samples_seen=samples_seen,
        score=score,
        reasons=tuple(reasons),
    )


def analyze_capture(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and rank a watcher report without inferring external API rights."""
    if not isinstance(report, Mapping):
        raise EndpointCaptureError("capture report must be an object")
    if report.get("schema_version") != 1:
        raise EndpointCaptureError("unsupported capture schema_version")
    if report.get("method") != "powershell_established_tcp_watch":
        raise EndpointCaptureError("unexpected capture method")
    _require_bool(report, "credential_access", False)
    _require_bool(report, "process_memory_access", False)
    _require_bool(report, "command_line_access", False)

    started = _parse_utc(report.get("started_at_utc"), "started_at_utc")
    ended = _parse_utc(report.get("ended_at_utc"), "ended_at_utc")
    if ended <= started:
        raise EndpointCaptureError("capture must have a positive duration")

    observations = report.get("observations")
    if not isinstance(observations, list):
        raise EndpointCaptureError("observations must be a list")
    declared_count = report.get("endpoint_count")
    if type(declared_count) is not int or declared_count != len(observations):
        raise EndpointCaptureError("endpoint_count does not match observations")

    ranked = [_score_observation(row) for row in observations]
    ranked.sort(key=lambda item: (-item.score, item.process_name.lower(), item.remote_address, item.remote_port))

    top_score = ranked[0].score if ranked else 0
    top = [item for item in ranked if item.score == top_score and top_score > 0]
    unique_high_signal = len(top) == 1 and top_score >= 45
    candidate = asdict(top[0]) if unique_high_signal else None

    return {
        "schema_version": 1,
        "analysis_type": "deepcharts_network_peer_ranking",
        "capture_started_at_utc": started.isoformat(),
        "capture_ended_at_utc": ended.isoformat(),
        "ranked_endpoints": [asdict(item) for item in ranked],
        "candidate": candidate,
        "candidate_is_unambiguous": unique_high_signal,
        "external_api_authorized": False,
        "safe_for_independent_connection": False,
        "next_gate": (
            "verify entitlement supplied external API connection details before any independent connection attempt"
            if candidate is not None
            else "collect a less ambiguous DeepCharts dxFeed reconnect capture"
        ),
        "limitations": [
            "Network peer observation does not establish external API entitlement.",
            "Port 7300 is only an indicator; port 443 is generic TLS and weak evidence.",
            "A likely dxFeed peer must not receive account credentials unless the entitlement explicitly supplies that endpoint for external use.",
        ],
    }


def analyze_capture_file(path: str | Path) -> dict[str, Any]:
    capture_path = Path(path)
    try:
        report = json.loads(capture_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EndpointCaptureError("capture file cannot be read as JSON") from exc
    return analyze_capture(report)

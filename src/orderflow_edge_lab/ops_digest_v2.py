"""Daily wait-window ops digest: one hashed artifact per day during accumulation.

This is an **aggregation layer only**. It calls the existing observability
builders (review clock, capture health) and reads already-committed operational
manifests. It re-implements no counting logic, touches no strategy definition,
and computes no verdict.

Its purpose is to make a silent failure visible: if the capture scheduler stops,
if the daily clock report stops arriving, if the cumulative ledger stops growing,
or if a required artifact is no longer retrievable, the digest for that day says
so in one place.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from orderflow_edge_lab.capture_health import DEFAULT_DATA_DIR, build_health_summary
from orderflow_edge_lab.review_clock import DEFAULT_CONFIG as DEFAULT_CLOCK_CONFIG
from orderflow_edge_lab.review_clock import clock_report
from orderflow_edge_lab.review_clock import parse_utc

DEFAULT_LEDGER_MANIFEST = Path("research/DISCOVERY_LEDGER_MANIFEST_2026_09_29.json")

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


class OpsDigestError(ValueError):
    """Raised when a digest input cannot be read."""


def _load_manifest(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OpsDigestError(f"ledger manifest is not valid JSON: {exc}") from exc
    return payload if isinstance(payload, dict) else None


def _normalize_acquisition(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize an explicit CI inventory acquisition fact; never infer it from [] ."""

    if value is None:
        return {
            "status": "NOT_PROVIDED",
            "pages_fetched": None,
            "retrieved_at_utc": None,
            "error": None,
        }
    if not isinstance(value, Mapping):
        raise OpsDigestError("inventory acquisition status must be an object")
    status = value.get("status")
    if status not in {"ACQUIRED", "FAILED"}:
        raise OpsDigestError("inventory acquisition status must be ACQUIRED or FAILED")
    pages = value.get("pages_fetched")
    if type(pages) is not int or pages < 0:
        raise OpsDigestError("inventory acquisition pages_fetched must be a nonnegative integer")
    retrieved = value.get("retrieved_at_utc")
    if not isinstance(retrieved, str):
        raise OpsDigestError("inventory acquisition retrieved_at_utc must be an offset-aware timestamp")
    parse_utc(retrieved, "inventory acquisition retrieved_at_utc")
    error = value.get("error")
    if status == "ACQUIRED" and error is not None:
        raise OpsDigestError("successful inventory acquisition must not carry an error")
    if status == "FAILED" and (not isinstance(error, str) or not error.strip()):
        raise OpsDigestError("failed inventory acquisition must include an error")
    return {
        "status": status,
        "pages_fetched": pages,
        "retrieved_at_utc": parse_utc(retrieved, "inventory acquisition retrieved_at_utc").isoformat().replace("+00:00", "Z"),
        "error": error,
    }


def _normalize_ledger_retrieval(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep artifact identity/retrieval facts distinct from ledger contents."""

    if value is None:
        return {
            "status": "NOT_PROVIDED",
            "artifact_id": None,
            "artifact_created_at_utc": None,
            "retrieved_at_utc": None,
            "error": None,
        }
    if not isinstance(value, Mapping):
        raise OpsDigestError("ledger retrieval status must be an object")
    status = value.get("status")
    if status not in {"ACQUIRED", "FAILED", "NOT_FOUND"}:
        raise OpsDigestError("ledger retrieval status must be ACQUIRED, FAILED, or NOT_FOUND")
    normalized: dict[str, Any] = {
        "status": status,
        "artifact_id": value.get("artifact_id"),
        "artifact_created_at_utc": value.get("artifact_created_at_utc"),
        "retrieved_at_utc": value.get("retrieved_at_utc"),
        "error": value.get("error"),
    }
    for key in ("artifact_created_at_utc", "retrieved_at_utc"):
        if normalized[key] is not None:
            if not isinstance(normalized[key], str):
                raise OpsDigestError(f"ledger retrieval {key} must be an offset-aware timestamp")
            normalized[key] = parse_utc(normalized[key], f"ledger retrieval {key}").isoformat().replace("+00:00", "Z")
    if status == "FAILED" and (not isinstance(normalized["error"], str) or not normalized["error"].strip()):
        raise OpsDigestError("failed ledger retrieval must include an error")
    return normalized


def build_ops_digest(
    *,
    clock_config: Path | str = DEFAULT_CLOCK_CONFIG,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    ledger_manifest: Path | str | None = DEFAULT_LEDGER_MANIFEST,
    coverage_report: Mapping[str, Any] | None = None,
    inventory_acquisition: Mapping[str, Any] | None = None,
    ledger_retrieval: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    stale_after_hours: float = 26.0,
    ledger_heartbeat_cadence_hours: float | None = None,
    ledger_heartbeat_grace_hours: float | None = None,
) -> dict[str, Any]:
    """Build the daily digest from the existing observability reports."""

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    clock = clock_report(clock_config, now=moment)
    health = build_health_summary(data_dir, now=moment, stale_after_hours=stale_after_hours)
    manifest = _load_manifest(ledger_manifest)
    acquisition = _normalize_acquisition(inventory_acquisition)
    retrieval = _normalize_ledger_retrieval(ledger_retrieval)
    if (ledger_heartbeat_cadence_hours is None) != (ledger_heartbeat_grace_hours is None):
        raise OpsDigestError("ledger heartbeat cadence and grace must be declared together")
    if ledger_heartbeat_cadence_hours is not None and (
        not isinstance(ledger_heartbeat_cadence_hours, (int, float))
        or isinstance(ledger_heartbeat_cadence_hours, bool)
        or ledger_heartbeat_cadence_hours <= 0
        or not isinstance(ledger_heartbeat_grace_hours, (int, float))
        or isinstance(ledger_heartbeat_grace_hours, bool)
        or ledger_heartbeat_grace_hours < 0
    ):
        raise OpsDigestError("ledger heartbeat cadence must be positive and grace nonnegative hours")

    alerts: list[dict[str, Any]] = []
    if acquisition["status"] == "FAILED":
        alerts.append(
            {
                "severity": "error",
                "code": "inventory_acquisition_failed",
                "detail": acquisition["error"],
            }
        )
    for finding in health["findings"]:
        if finding["severity"] in {"warning", "error"}:
            alerts.append(
                {
                    "severity": finding["severity"],
                    "code": f"capture_{finding['code']}",
                    "detail": finding["detail"],
                }
            )
    if not health["data_dir_exists"]:
        alerts.append(
            {
                "severity": "warning",
                "code": "capture_directory_absent",
                "detail": f"no capture directory at {health['data_dir']}; freshness cannot be assessed",
            }
        )
    if manifest is None:
        alerts.append(
            {
                "severity": "warning",
                "code": "ledger_manifest_unavailable",
                "detail": f"no readable ledger manifest at {ledger_manifest}",
            }
        )
    ledger_heartbeat_utc = None
    ledger_manifest_sha256 = None
    if manifest is not None:
        canonical_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)
        ledger_manifest_sha256 = hashlib.sha256(canonical_manifest.encode("utf-8")).hexdigest()
        try:
            updated = parse_utc(manifest.get("updated_at_utc"), "ledger manifest updated_at_utc")
        except (TypeError, ValueError, OpsDigestError) as exc:
            alerts.append(
                {
                    "severity": "error",
                    "code": "ledger_manifest_invalid",
                    "detail": str(exc),
                }
            )
        else:
            ledger_heartbeat_utc = updated.isoformat().replace("+00:00", "Z")
            if ledger_heartbeat_cadence_hours is not None:
                age_hours = (moment - updated).total_seconds() / 3600.0
                threshold = float(ledger_heartbeat_cadence_hours) + float(ledger_heartbeat_grace_hours)
                if age_hours > threshold:
                    alerts.append(
                        {
                            "severity": "error",
                            "code": "ledger_heartbeat_stale",
                            "detail": (
                                f"ledger heartbeat is {round(age_hours, 3)}h old; caller-declared "
                                f"cadence plus grace is {threshold}h"
                            ),
                        }
                    )
    coverage_summary = None
    if coverage_report is not None:
        coverage_summary = {
            "requirements_total": coverage_report.get("requirements_total"),
            "requirements_satisfied": coverage_report.get("requirements_satisfied"),
            "coverage_ok": coverage_report.get("coverage_ok"),
            "report_sha256": coverage_report.get("report_sha256"),
        }
        for finding in coverage_report.get("findings", []):
            if finding.get("severity") in {"warning", "error"}:
                alerts.append(
                    {
                        "severity": finding["severity"],
                        "code": f"coverage_{finding['code']}",
                        "detail": f"{finding.get('requirement_id')}: {finding.get('detail')}",
                    }
                )

        if coverage_report.get("coverage_ok") is False and not any(
            alert["code"].startswith("coverage_") and alert["severity"] == "error" for alert in alerts
        ):
            alerts.append(
                {
                    "severity": "error",
                    "code": "coverage_report_not_ok",
                    "detail": "coverage report declared coverage_ok=false without an error finding",
                }
            )

    highest = max(
        (alert["severity"] for alert in alerts),
        key=lambda severity: _SEVERITY_ORDER.get(severity, 0),
        default="info",
    )
    watches = [
        {
            "watch_id": watch["watch_id"],
            "priority": watch.get("priority"),
            "open_watch": watch.get("open_watch"),
            "terminal_state": watch.get("terminal_state"),
            "elapsed_days": watch.get("elapsed_days"),
            "earliest_review_utc": watch.get("earliest_review_utc"),
            "days_until_earliest_review": watch.get("days_until_earliest_review"),
            "review_window_matured": watch.get("review_window_matured"),
            "review_gate_type": watch.get("review_gate_type"),
        }
        for watch in clock["watches"]
    ]

    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": "wait-window-ops-digest-v1",
        "status": "reporting_only",
        "generated_at_utc": moment.isoformat().replace("+00:00", "Z"),
        "digest_status": "attention_required" if highest in {"warning", "error"} else "ok",
        "highest_alert_severity": highest,
        "watch_clock": {
            "watch_count": clock["watch_count"],
            "watches": watches,
            "summary": clock["summary"],
        },
        "capture_health": {
            "data_dir": health["data_dir"],
            "data_dir_exists": health["data_dir_exists"],
            "capture_counts": health["capture_counts"],
            "newest_capture_started_utc": health["newest_capture_started_utc"],
            "hours_since_newest_capture": health["hours_since_newest_capture"],
            "stale_after_hours": health["stale_after_hours"],
            "stale": health["stale"],
            "report_sha256": health["report_sha256"],
        },
        "ledger": {
            "path": str(ledger_manifest) if ledger_manifest is not None else None,
            "available": manifest is not None,
            "batch_count": (manifest or {}).get("batch_count"),
            "updated_at_utc": (manifest or {}).get("updated_at_utc"),
            "manifest_sha256": ledger_manifest_sha256,
            "heartbeat_utc": ledger_heartbeat_utc,
            "heartbeat_cadence_hours": ledger_heartbeat_cadence_hours,
            "heartbeat_grace_hours": ledger_heartbeat_grace_hours,
            "retrieval": retrieval,
        },
        "inventory_acquisition": acquisition,
        "coverage": coverage_summary,
        "alerts": alerts,
        "operational_check_conclusion": "FAIL" if highest == "error" else "PASS",
        "claims": {
            "computes_strategy_verdicts": False,
            "inspects_strategy_pnl": False,
            "counts_prospective_batches": False,
            "promotes_any_strategy": False,
            "live_order_transmission_supported": False,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["digest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def digest_markdown(digest: Mapping[str, Any]) -> str:
    """Render the digest for a GitHub step summary or a local review."""

    lines = [
        "# Wait-window ops digest",
        "",
        f"- Status: **{digest['digest_status']}** (highest alert severity: {digest['highest_alert_severity']})",
        f"- Operational health conclusion: **{digest['operational_check_conclusion']}**",
        f"- Generated: {digest['generated_at_utc']}",
        f"- Digest sha256: `{digest['digest_sha256']}`",
        "",
        "## Watch clock",
        "",
        "| Watch | Elapsed (days) | Earliest review | Days remaining | Matured |",
        "|---|---|---|---|---|",
    ]
    for watch in digest["watch_clock"]["watches"]:
        lines.append(
            "| {watch} | {elapsed} | {earliest} | {remaining} | {matured} |".format(
                watch=watch["watch_id"],
                elapsed=watch["elapsed_days"],
                earliest=watch["earliest_review_utc"] or "(non-calendar gate)",
                remaining=watch["days_until_earliest_review"],
                matured=watch["review_window_matured"],
            )
        )
    health = digest["capture_health"]
    lines.extend(
        [
            "",
            "## Capture health",
            "",
            f"- Data dir: `{health['data_dir']}` (exists: {health['data_dir_exists']})",
            f"- Counts: {health['capture_counts']}",
            f"- Newest capture: {health['newest_capture_started_utc']} "
            f"({health['hours_since_newest_capture']}h old, stale threshold {health['stale_after_hours']}h)",
            f"- Stale: {health['stale']}",
            "",
            "## Ledger",
            "",
            f"- Manifest: `{digest['ledger']['path']}` (available: {digest['ledger']['available']})",
            f"- Batch count: {digest['ledger']['batch_count']} "
            f"(updated {digest['ledger']['updated_at_utc']})",
            f"- Heartbeat: {digest['ledger']['heartbeat_utc']} "
            f"(cadence={digest['ledger']['heartbeat_cadence_hours']}, "
            f"grace={digest['ledger']['heartbeat_grace_hours']})",
            f"- Retrieval status: {digest['ledger']['retrieval']['status']}; "
            f"manifest sha256: `{digest['ledger']['manifest_sha256']}`",
            "",
            "## Artifact inventory acquisition",
            "",
            f"- Status: {digest['inventory_acquisition']['status']} "
            f"(pages={digest['inventory_acquisition']['pages_fetched']}, "
            f"retrieved={digest['inventory_acquisition']['retrieved_at_utc']})",
            "",
        ]
    )
    if digest["coverage"]:
        lines.extend(
            [
                "## Coverage",
                "",
                f"- Requirements satisfied: {digest['coverage']['requirements_satisfied']}"
                f"/{digest['coverage']['requirements_total']}"
                f" (coverage_ok={digest['coverage']['coverage_ok']})",
                "",
            ]
        )
    if digest["alerts"]:
        lines.append("## Alerts")
        lines.append("")
        for alert in digest["alerts"]:
            lines.append(f"- [{alert['severity']}] `{alert['code']}`: {alert['detail']}")
    else:
        lines.append("No alerts.")
    lines.append("")
    return "\n".join(lines)

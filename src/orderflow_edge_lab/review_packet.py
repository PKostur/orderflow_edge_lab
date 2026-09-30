"""Review packet assembly for predeclared prospective reviews.

This module produces a **skeleton** review document from two frozen inputs:

1. the predeclared watch configuration (what was promised to be reviewed), and
2. the counting report produced by the frozen pipeline (what has been observed).

It copies pipeline-reported numbers verbatim, pins the SHA-256 of every input it
read, and leaves every verdict cell empty. It computes no verdict, no
significance test, no threshold, and no promotion decision, and it refuses to
render a review body for a watch whose predeclared window has not matured.

Its purpose is to remove the manual, error-prone step of extracting a frozen
counting report out of a large CI artifact while the review itself stays a human
decision recorded in `research/`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_SESSION_WATCH_CONFIG = Path("config/session_development_watch_v1.json")
DEFAULT_FORWARD_WATCH_CONFIG = Path("config/evidence_v2_session_forward_watch_v1.json")

SESSION_WATCH_ANALYSIS = "prospective_session_development_watch"


class ReviewPacketError(ValueError):
    """Raised when a review packet cannot be assembled from the frozen inputs."""


def _load_object(path: Path | str, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReviewPacketError(f"{context}: file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewPacketError(f"{context}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReviewPacketError(f"{context}: expected a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_session_watch_packet(
    report: Mapping[str, Any],
    watch_config: Mapping[str, Any],
    *,
    source_path: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    """Build a review skeleton for a frozen session-development watch report."""

    if report.get("analysis") != SESSION_WATCH_ANALYSIS:
        raise ReviewPacketError(
            f"expected analysis == {SESSION_WATCH_ANALYSIS!r}, got {report.get('analysis')!r}"
        )
    config_watches = {
        str(watch["watch_id"]): watch
        for watch in watch_config.get("watches", [])
        if isinstance(watch, Mapping) and watch.get("watch_id")
    }
    requirement = dict(watch_config.get("prospective_review_requirement") or {})
    predeclared_metrics = [str(item) for item in requirement.get("evaluate", [])]

    watches: list[dict[str, Any]] = []
    open_cells = 0
    ready_watches = 0
    for observed in report.get("watches", []):
        if not isinstance(observed, Mapping):
            continue
        watch_id = str(observed.get("watch_id"))
        frozen = config_watches.get(watch_id, {})
        ready = bool(observed.get("ready_for_review"))
        ready_watches += 1 if ready else 0
        cells: list[dict[str, Any]] = []
        for cell in observed.get("cells", []):
            if not isinstance(cell, Mapping):
                continue
            cells.append(
                {
                    "cell_id": f"{watch_id}:{int(cell['horizon_ms'])}ms@{float(cell['fee_bps_round_trip'])}bps",
                    "horizon_ms": cell.get("horizon_ms"),
                    "fee_bps_round_trip": cell.get("fee_bps_round_trip"),
                    "pipeline_reported_metrics": {
                        key: cell.get(key)
                        for key in (
                            "observations",
                            "independent_batches",
                            "calendar_days",
                            "gross_mean_bps",
                            "net_mean_bps",
                            "net_median_bps",
                            "cumulative_net_bps",
                            "win_rate",
                            "profit_factor",
                            "positive_batch_fraction",
                            "positive_day_fraction",
                            "max_drawdown_bps",
                            "largest_positive_batch_share",
                        )
                    },
                    "verdict": None,
                    "verdict_requires_human_review": True,
                }
            )
            open_cells += 1
        watches.append(
            {
                "watch_id": watch_id,
                "present_in_frozen_config": bool(frozen),
                "family": observed.get("family"),
                "direction": observed.get("direction"),
                "session_phase": observed.get("session_phase"),
                "conditions": observed.get("conditions"),
                "prospective_watch_start_utc": observed.get("prospective_watch_start_utc"),
                "pipeline_status": observed.get("status"),
                "ready_for_review": ready,
                "pipeline_counts": {
                    "prospective_unique_signals": observed.get("prospective_unique_signals"),
                    "prospective_independent_batches": observed.get("prospective_independent_batches"),
                    "prospective_calendar_days": observed.get("prospective_calendar_days"),
                },
                "review_requirement": observed.get("review_requirement"),
                "predeclared_metrics_to_evaluate": predeclared_metrics,
                "development_snapshot_verbatim": observed.get("development_snapshot_30s_4bps"),
                "cells_awaiting_verdict": cells,
            }
        )

    # Reviews are per-watch: a packet is usable as soon as one watch in the report
    # has met its own frozen gate, and each watch keeps its own ready flag.
    return _packet_envelope(
        packet_kind="session_watch_review",
        watch_ids=[watch["watch_id"] for watch in watches],
        source_path=source_path,
        generated_at=generated_at,
        packet_status="READY_FOR_HUMAN_REVIEW" if ready_watches else "AWAITING_REVIEW_WINDOW",
        window_matured=ready_watches > 0,
        body={
            "watches_ready_for_review": ready_watches,
            "watches_total": len(watches),
            "frozen_config_metrics": predeclared_metrics,
            "frozen_config_promotion_forbidden_until_new_evidence": requirement.get(
                "promotion_forbidden_until_new_evidence"
            ),
            "frozen_config_future_rows_rule": requirement.get(
                "future_rows_must_have_signal_observed_after_watch_start"
            ),
            "threshold_note": (
                "The frozen session watch declares which metrics to evaluate but no numeric "
                "pass/fail threshold. This packet therefore records values only and leaves every "
                "cell verdict empty for the review owner to decide and sign."
            ),
            "watches": watches,
        },
        open_verdict_cells=open_cells,
    )


def build_forward_watch_packet(
    report: Mapping[str, Any],
    watch_config: Mapping[str, Any],
    *,
    source_path: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    """Build a review skeleton for the frozen cross-strategy forward watch."""

    watch_id = report.get("watch_id") or watch_config.get("watch_id")
    if not watch_id:
        raise ReviewPacketError("forward watch report has no watch_id")
    reporting = dict(watch_config.get("reporting") or {})
    review_after_days = int(reporting.get("review_after_calendar_days", 0))
    days_elapsed = report.get("days_elapsed")
    matured = isinstance(days_elapsed, (int, float)) and float(days_elapsed) >= review_after_days

    metric_cells = [
        {
            "metric": str(metric),
            "reviewed_value": None,
            "verdict": None,
            "verdict_requires_human_review": True,
        }
        for metric in reporting.get("metrics", [])
    ]

    return _packet_envelope(
        packet_kind="forward_watch_review",
        watch_ids=[str(watch_id)],
        source_path=source_path,
        generated_at=generated_at,
        packet_status="READY_FOR_HUMAN_REVIEW" if matured else "AWAITING_REVIEW_WINDOW",
        window_matured=matured,
        body={
            "primary_hypothesis_statement": (watch_config.get("primary_hypothesis") or {}).get("statement"),
            "review_after_calendar_days": review_after_days,
            "no_early_pass_fail": reporting.get("no_early_pass_fail"),
            "forbidden_actions": list(watch_config.get("forbidden", [])),
            "pipeline_status": report.get("status"),
            "pipeline_as_of_utc": report.get("as_of_utc"),
            "pipeline_days_elapsed": days_elapsed,
            "pipeline_observation_verbatim": report.get("primary_observation"),
            "metric_cells_awaiting_verdict": metric_cells,
        },
        open_verdict_cells=len(metric_cells),
        extra_notes=(
            []
            if matured
            else [
                "The predeclared review window has not matured. No review body is rendered and no "
                "pass/fail statement may be recorded from this packet."
            ]
        ),
    )


def _packet_envelope(
    *,
    packet_kind: str,
    watch_ids: list[str],
    source_path: Path,
    generated_at: datetime,
    packet_status: str,
    window_matured: bool,
    body: dict[str, Any],
    open_verdict_cells: int,
    extra_notes: list[str] | None = None,
) -> dict[str, Any]:
    notes = [
        "Every number in this packet is copied verbatim from the frozen counting pipeline.",
        "This packet computes no verdict, no significance test, and no promotion decision.",
        "Counts are never recomputed from cumulative artifacts.",
    ]
    notes.extend(extra_notes or [])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": "prospective-review-packet-v1",
        "status": "skeleton_only",
        "packet_kind": packet_kind,
        "packet_status": packet_status,
        "window_matured": window_matured,
        "generated_at_utc": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "watch_ids": watch_ids,
        "source_reports": [
            {
                "path": str(source_path),
                "sha256": _sha256_file(source_path),
                "size_bytes": source_path.stat().st_size,
            }
        ],
        "open_verdict_cells": open_verdict_cells,
        "notes": notes,
        **body,
        "claims": {
            "computes_strategy_verdicts": False,
            "inspects_strategy_pnl": False,
            "recomputes_pipeline_counts": False,
            "alters_frozen_definitions": False,
            "promotes_any_strategy": False,
            "live_order_transmission_supported": False,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["packet_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def build_review_packet(
    report_path: Path | str,
    *,
    session_watch_config: Path | str = DEFAULT_SESSION_WATCH_CONFIG,
    forward_watch_config: Path | str = DEFAULT_FORWARD_WATCH_CONFIG,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch on the frozen report shape and assemble the matching packet."""

    source = Path(report_path)
    report = _load_object(source, "counting report")
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if report.get("analysis") == SESSION_WATCH_ANALYSIS:
        config = _load_object(session_watch_config, "session watch config")
        return build_session_watch_packet(
            report, config, source_path=source, generated_at=generated_at
        )
    if report.get("watch_id") and "days_elapsed" in report:
        config = _load_object(forward_watch_config, "forward watch config")
        return build_forward_watch_packet(
            report, config, source_path=source, generated_at=generated_at
        )
    raise ReviewPacketError(
        "unrecognised counting report: expected a frozen session-watch report "
        f"(analysis == {SESSION_WATCH_ANALYSIS!r}) or a frozen forward-watch report "
        "(watch_id + days_elapsed)"
    )


def review_packet_markdown(packet: Mapping[str, Any]) -> str:
    """Render the packet as a review skeleton with empty verdict cells."""

    source = packet["source_reports"][0]
    lines = [
        f"# Review packet — {packet['packet_kind']}",
        "",
        f"- Packet status: **{packet['packet_status']}**",
        f"- Predeclared window matured: {packet['window_matured']}",
        f"- Generated: {packet['generated_at_utc']}",
        f"- Watch IDs: {', '.join(packet['watch_ids'])}",
        f"- Source report: `{source['path']}` (sha256 `{source['sha256']}`)",
        f"- Verdict cells awaiting a recorded human decision: {packet['open_verdict_cells']}",
        "",
        "This packet is a skeleton. It reports pipeline numbers verbatim and computes no verdict.",
        "",
    ]
    for note in packet["notes"]:
        lines.append(f"- {note}")
    lines.append("")

    if packet["packet_kind"] == "session_watch_review":
        lines.extend(
            [
                "## Predeclared metrics to evaluate",
                "",
                *[f"- `{metric}`" for metric in packet["frozen_config_metrics"]],
                "",
                "## Watches",
                "",
            ]
        )
        for watch in packet["watches"]:
            counts = watch["pipeline_counts"]
            lines.extend(
                [
                    f"### {watch['watch_id']}",
                    "",
                    f"- Pipeline status: `{watch['pipeline_status']}` (ready_for_review={watch['ready_for_review']})",
                    f"- Counts: {counts['prospective_unique_signals']} signals / "
                    f"{counts['prospective_independent_batches']} batches / "
                    f"{counts['prospective_calendar_days']} days",
                    f"- Gate: `{watch['review_requirement']}`",
                    "",
                    "| Cell | Observations | Net mean (bps) | Cum (bps) | PF | Verdict |",
                    "|---|---|---|---|---|---|",
                ]
            )
            for cell in watch["cells_awaiting_verdict"]:
                metrics = cell["pipeline_reported_metrics"]
                lines.append(
                    "| {cell} | {obs} | {net} | {cum} | {pf} | _(to be recorded)_ |".format(
                        cell=cell["cell_id"],
                        obs=metrics["observations"],
                        net=metrics["net_mean_bps"],
                        cum=metrics["cumulative_net_bps"],
                        pf=metrics["profit_factor"],
                    )
                )
            lines.append("")
    else:
        lines.extend(
            [
                "## Frozen hypothesis",
                "",
                f"> {packet['primary_hypothesis_statement']}",
                "",
                f"- Review after: {packet['review_after_calendar_days']} calendar days "
                f"(no early pass/fail: {packet['no_early_pass_fail']})",
                f"- Pipeline status: `{packet['pipeline_status']}` as of {packet['pipeline_as_of_utc']} "
                f"(days elapsed {packet['pipeline_days_elapsed']})",
                "",
                "## Predeclared metrics awaiting a recorded decision",
                "",
                "| Metric | Reviewed value | Verdict |",
                "|---|---|---|",
            ]
        )
        for cell in packet["metric_cells_awaiting_verdict"]:
            lines.append(f"| `{cell['metric']}` | _(to be recorded)_ | _(to be recorded)_ |")
        lines.append("")
        if packet["forbidden_actions"]:
            lines.append("## Forbidden actions (frozen)")
            lines.append("")
            for action in packet["forbidden_actions"]:
                lines.append(f"- `{action}`")
            lines.append("")

    lines.extend(
        [
            "## Sign-off",
            "",
            "- Verdicts recorded by: _(name)_",
            "- Date (UTC): _(date)_",
            "- Terminal state assigned: _(falsified | not established | conditional promote)_",
            "",
        ]
    )
    return "\n".join(lines)

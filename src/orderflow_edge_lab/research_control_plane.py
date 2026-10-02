from __future__ import annotations

from typing import Any, Mapping


class ResearchControlPlaneError(ValueError):
    pass


def _strategy_progress(shadow: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for report in shadow.get("reports") or []:
        p = report.get("evidence_progress") or {}
        rows[str(report["audit_id"])] = {
            "completed_trade_count": int(p.get("completed_trade_count") or 0),
            "open_post_start_snapshot_count": int(
                p.get("open_post_start_snapshot_count") or 0
            ),
            "completed_observed_symbol_count": int(
                p.get("completed_observed_symbol_count") or 0
            ),
            "ready_for_review": bool(report.get("ready_for_review")),
        }
    return rows


def _operational_progress(operational: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for report in operational.get("strategies") or []:
        rows[str(report["audit_id"])] = {
            "current_long_symbol_count": int(
                report.get("current_long_symbol_count") or 0
            ),
            "current_short_symbol_count": int(
                report.get("current_short_symbol_count") or 0
            ),
            "current_flat_symbol_count": int(
                report.get("current_flat_symbol_count") or 0
            ),
            "carried_pre_start_position_count": int(
                report.get("carried_pre_start_position_count") or 0
            ),
            "post_start_position_change_count": int(
                report.get("post_start_position_change_count") or 0
            ),
            "median_position_age_hours": report.get("median_position_age_hours"),
            "symbols_with_post_start_change": list(
                report.get("symbols_with_post_start_change") or []
            ),
        }
    return rows


def build_control_plane_status(
    shadow: Mapping[str, Any],
    decision: Mapping[str, Any],
    action: Mapping[str, Any],
    operational: Mapping[str, Any],
) -> dict[str, Any]:
    if shadow.get("analysis") != "universal_session_alignment_prospective_shadow":
        raise ResearchControlPlaneError("unsupported shadow report")
    if decision.get("analysis") != "jev_research_decision_layer_v1":
        raise ResearchControlPlaneError("unsupported Jev decision report")
    if action.get("analysis") != "jev_research_action_v1":
        raise ResearchControlPlaneError("unsupported Jev action report")
    if operational.get("analysis") != "universal_shadow_operational_monitor_v1":
        raise ResearchControlPlaneError("unsupported operational monitor")

    watch_id = str(shadow.get("watch_id"))
    if str((decision.get("state") or {}).get("watch_id")) != watch_id:
        raise ResearchControlPlaneError("decision watch_id mismatch")
    if str(action.get("watch_id")) != watch_id:
        raise ResearchControlPlaneError("action watch_id mismatch")
    if str(operational.get("watch_id")) != watch_id:
        raise ResearchControlPlaneError("operational watch_id mismatch")
    if str(action.get("decision_id")) != str(decision.get("decision_id")):
        raise ResearchControlPlaneError("action decision_id mismatch")

    op_claims = operational.get("claims") or {}
    if not bool(op_claims.get("not_prospective_evidence")):
        raise ResearchControlPlaneError("operational monitor must remain non-evidence")
    authority = action.get("authority_boundary") or {}
    if any(bool(value) for value in authority.values()):
        raise ResearchControlPlaneError("action authority boundary violated")

    evidence = _strategy_progress(shadow)
    operations = _operational_progress(operational)
    completed_total = sum(
        row["completed_trade_count"] for row in evidence.values()
    )
    open_total = sum(
        row["open_post_start_snapshot_count"] for row in evidence.values()
    )
    post_start_changes = sum(
        row["post_start_position_change_count"] for row in operations.values()
    )
    selected_action = str((decision.get("policy") or {}).get("selected_action") or "")
    action_status = str((action.get("result") or {}).get("status") or "")
    all_ready = bool((shadow.get("evidence_progress") or {}).get("all_strategies_ready"))

    if selected_action == "stop_protocol_breach" or action_status == "BLOCKED":
        stage = "HALTED_PROTOCOL_BREACH"
    elif str(shadow.get("status")) == "PRE_START":
        stage = "PRE_START"
    elif all_ready:
        stage = "READY_FOR_REVIEW"
    elif completed_total > 0:
        stage = "ACCUMULATING_COMPLETED_EVIDENCE"
    elif open_total > 0 or post_start_changes > 0:
        stage = "WAITING_FOR_COMPLETIONS"
    else:
        stage = "WAITING_FOR_FIRST_POST_START_CHANGE"

    return {
        "schema_version": 1,
        "analysis": "research_control_plane_status_v1",
        "watch_id": watch_id,
        "as_of_utc": shadow.get("as_of_utc"),
        "stage": stage,
        "shadow_status": shadow.get("status"),
        "prospective_start_utc": shadow.get("prospective_start_utc"),
        "latest_execution_boundary_utc": operational.get(
            "latest_execution_boundary_utc"
        ),
        "execution_boundaries_since_start_including_start": operational.get(
            "execution_boundaries_since_start_including_start"
        ),
        "evidence": {
            "total_completed_trade_count": completed_total,
            "total_open_post_start_snapshot_count": open_total,
            "per_strategy": evidence,
        },
        "operations": {
            "total_post_start_position_change_count": post_start_changes,
            "per_strategy": operations,
        },
        "decision": {
            "decision_id": decision.get("decision_id"),
            "provider": decision.get("provider"),
            "provider_resolution": decision.get("provider_resolution"),
            "model": decision.get("model"),
            "selected_action": selected_action,
            "selection_source": (decision.get("policy") or {}).get(
                "selection_source"
            ),
            "action_status": action_status,
        },
        "claims": {
            "single_status_surface_only": True,
            "does_not_change_frozen_shadow": True,
            "does_not_change_jev_v1": True,
            "operational_telemetry_not_evidence": True,
            "live_trading_authorized": False,
            "leverage_authorized": False,
            "strategy_promotion_authorized": False,
        },
    }

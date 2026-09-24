from __future__ import annotations

from typing import Any, Mapping


class JevResearchActionError(ValueError):
    pass


def _strategy_counts(shadow_report: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    for report in shadow_report.get("reports") or []:
        progress = report.get("evidence_progress") or {}
        rows[str(report["audit_id"])] = {
            "completed_trade_count": int(progress.get("completed_trade_count") or 0),
            "open_post_start_snapshot_count": int(
                progress.get("open_post_start_snapshot_count") or 0
            ),
            "completed_observed_symbol_count": int(
                progress.get("completed_observed_symbol_count") or 0
            ),
        }
    return rows


def _coverage_report(shadow_report: Mapping[str, Any]) -> dict[str, Any]:
    hypotheses: list[dict[str, Any]] = []
    for report in shadow_report.get("reports") or []:
        audit_id = str(report["audit_id"])
        for row in report.get("hypothesis_sample_progress") or []:
            aligned = int(row.get("aligned_completed_trade_count") or 0)
            comparison = int(row.get("comparison_completed_trade_count") or 0)
            paired = int(row.get("paired_observed_symbol_count") or 0)
            hypotheses.append(
                {
                    "audit_id": audit_id,
                    "hypothesis_id": str(row["hypothesis_id"]),
                    "aligned_completed_trade_count": aligned,
                    "comparison_completed_trade_count": comparison,
                    "paired_observed_symbol_count": paired,
                    "both_states_observed": bool(row.get("both_states_observed")),
                    "coverage_gap": (
                        "NO_COMPLETED_OBSERVATIONS"
                        if aligned + comparison == 0
                        else "ONE_STATE_MISSING"
                        if aligned == 0 or comparison == 0
                        else "NO_PAIRED_SYMBOLS"
                        if paired == 0
                        else "BOTH_STATES_OBSERVED"
                    ),
                }
            )
    return {
        "hypotheses": hypotheses,
        "hypothesis_count": len(hypotheses),
        "both_states_observed_count": sum(
            bool(row["both_states_observed"]) for row in hypotheses
        ),
        "paired_symbol_coverage_count": sum(
            int(row["paired_observed_symbol_count"]) > 0 for row in hypotheses
        ),
    }


def _data_quality_report(shadow_report: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    source = shadow_report.get("source") or {}
    symbols = [str(value) for value in source.get("symbols") or []]
    hashes = shadow_report.get("source_sha256") or {}
    if not symbols:
        issues.append("missing_frozen_symbol_universe")
    missing_hashes = [symbol for symbol in symbols if symbol not in hashes]
    if missing_hashes:
        issues.append(f"missing_source_hashes:{','.join(missing_hashes)}")

    claims = shadow_report.get("claims") or {}
    required_true = (
        "pre_start_entries_excluded_from_scoring",
        "terminal_snapshot_liquidations_excluded_from_completed_trade_scoring",
        "labels_do_not_gate_trade_generation",
        "formal_verdict_withheld_until_review_requirements",
    )
    for key in required_true:
        if not bool(claims.get(key)):
            issues.append(f"integrity_claim_false:{key}")

    forbidden_true = (
        "candidate_promoted",
        "session_filter_authorized",
        "live_trading_authorized",
        "leverage_authorized",
        "profitable_edge_established",
    )
    for key in forbidden_true:
        if bool(claims.get(key)):
            issues.append(f"forbidden_claim_true:{key}")

    return {
        "status": "ISSUES_FOUND" if issues else "NO_OBVIOUS_ISSUE",
        "issues": issues,
        "frozen_symbol_count": len(symbols),
        "source_hash_count": len(hashes),
    }


def execute_research_action(
    shadow_report: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if shadow_report.get("analysis") != "universal_session_alignment_prospective_shadow":
        raise JevResearchActionError("unsupported shadow report")
    if decision.get("analysis") != "jev_research_decision_layer_v1":
        raise JevResearchActionError("unsupported Jev decision artifact")

    state = decision.get("state") or {}
    if str(state.get("watch_id")) != str(shadow_report.get("watch_id")):
        raise JevResearchActionError("decision and shadow watch_id mismatch")

    policy = decision.get("policy") or {}
    selected = str(policy.get("selected_action") or "")
    allowed = {
        "collect_more_evidence",
        "inspect_data_quality",
        "inspect_state_coverage",
        "prepare_formal_review",
        "stop_protocol_breach",
    }
    if selected not in allowed:
        raise JevResearchActionError(f"unsupported selected action: {selected}")

    if selected == "collect_more_evidence":
        result = {
            "status": "ACCUMULATE_UNCHANGED",
            "strategy_counts": _strategy_counts(shadow_report),
            "message": "Keep the frozen prospective watch unchanged and accumulate evidence.",
        }
    elif selected == "inspect_data_quality":
        result = _data_quality_report(shadow_report)
    elif selected == "inspect_state_coverage":
        result = {
            "status": "DESCRIPTIVE_INSPECTION_ONLY",
            **_coverage_report(shadow_report),
        }
    elif selected == "prepare_formal_review":
        all_ready = bool((shadow_report.get("evidence_progress") or {}).get("all_strategies_ready"))
        result = {
            "status": "READY" if all_ready else "NOT_READY",
            "all_strategies_ready": all_ready,
            "strategy_counts": _strategy_counts(shadow_report),
        }
    else:
        result = {
            "status": "BLOCKED",
            "protocol_breach_reasons": list(policy.get("protocol_breach_reasons") or []),
        }

    return {
        "schema_version": 1,
        "analysis": "jev_research_action_v1",
        "watch_id": str(shadow_report.get("watch_id")),
        "decision_id": str(decision.get("decision_id")),
        "provider": decision.get("provider"),
        "model": decision.get("model"),
        "selected_action": selected,
        "result": result,
        "authority_boundary": {
            "changes_frozen_shadow": False,
            "changes_strategy_rules": False,
            "changes_positions": False,
            "transmits_orders": False,
            "authorizes_promotion": False,
            "authorizes_leverage": False,
        },
    }

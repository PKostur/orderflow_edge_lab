from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any, Mapping

ACTION_OPTIONS = (
    "collect_more_evidence",
    "inspect_data_quality",
    "inspect_state_coverage",
    "prepare_formal_review",
    "stop_protocol_breach",
)
UNCERTAINTY_OPTIONS = (
    "sample_size",
    "state_coverage",
    "data_quality",
    "mixed_strategy_results",
    "none",
)
MATURITY_LEVELS = (
    "pre_start: prospective boundary not reached",
    "early: prospective evidence exists but is sparse",
    "accumulating: evidence is growing but review gates are not met",
    "review_ready: frozen review gates are met",
    "invalid: protocol integrity is compromised",
)


class JevResearchDecisionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JevDecisionConfig:
    model: str = "jev-latest"
    min_choice_confidence: float = 0.65
    timeout_s: float = 3.0


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def build_research_state(shadow_report: Mapping[str, Any]) -> dict[str, Any]:
    if shadow_report.get("analysis") != "universal_session_alignment_prospective_shadow":
        raise JevResearchDecisionError("unsupported report analysis")
    reports = shadow_report.get("reports")
    if not isinstance(reports, list) or not reports:
        raise JevResearchDecisionError("shadow report has no strategy reports")

    strategy_rows: list[dict[str, Any]] = []
    for report in reports:
        progress = report.get("evidence_progress") or {}
        summary = report.get("summary") or {}
        hypothesis_progress = report.get("hypothesis_sample_progress") or []
        strategy_rows.append(
            {
                "audit_id": str(report["audit_id"]),
                "formal_verdict": str(report.get("formal_verdict", "UNKNOWN")),
                "ready_for_review": bool(report.get("ready_for_review")),
                "completed_trade_count": int(progress.get("completed_trade_count") or 0),
                "open_post_start_snapshot_count": int(
                    progress.get("open_post_start_snapshot_count") or 0
                ),
                "completed_observed_symbol_count": int(
                    progress.get("completed_observed_symbol_count") or 0
                ),
                "completed_symbol_coverage_fraction": _finite_or_none(
                    progress.get("completed_symbol_coverage_fraction")
                ),
                "equal_weight_symbol_sleeve_completed_trade_return": _finite_or_none(
                    summary.get("equal_weight_symbol_sleeve_completed_trade_return")
                ),
                "equal_weight_symbol_sleeve_max_drawdown": _finite_or_none(
                    summary.get("equal_weight_symbol_sleeve_max_drawdown")
                ),
                "expectancy_bps": _finite_or_none(summary.get("expectancy_bps")),
                "win_rate": _finite_or_none(summary.get("win_rate")),
                "correct_direction_rate": _finite_or_none(
                    summary.get("correct_direction_rate")
                ),
                "hypothesis_state_coverage": [
                    {
                        "hypothesis_id": str(item["hypothesis_id"]),
                        "aligned_completed_trade_count": int(
                            item.get("aligned_completed_trade_count") or 0
                        ),
                        "comparison_completed_trade_count": int(
                            item.get("comparison_completed_trade_count") or 0
                        ),
                        "paired_observed_symbol_count": int(
                            item.get("paired_observed_symbol_count") or 0
                        ),
                        "both_states_observed": bool(item.get("both_states_observed")),
                    }
                    for item in hypothesis_progress
                ],
            }
        )

    claims = dict(shadow_report.get("claims") or {})
    forbidden_claims = {
        key: bool(claims.get(key))
        for key in (
            "candidate_promoted",
            "session_filter_authorized",
            "live_trading_authorized",
            "leverage_authorized",
            "profitable_edge_established",
        )
    }
    protocol_integrity_flags = {
        "labels_do_not_gate_trade_generation": bool(
            claims.get("labels_do_not_gate_trade_generation")
        ),
        "formal_verdict_withheld_until_review_requirements": bool(
            claims.get("formal_verdict_withheld_until_review_requirements")
        ),
        "pre_start_entries_excluded_from_scoring": bool(
            claims.get("pre_start_entries_excluded_from_scoring")
        ),
        "terminal_snapshot_liquidations_excluded_from_completed_trade_scoring": bool(
            claims.get(
                "terminal_snapshot_liquidations_excluded_from_completed_trade_scoring"
            )
        ),
    }
    progress = shadow_report.get("evidence_progress") or {}
    total_completed = sum(row["completed_trade_count"] for row in strategy_rows)
    total_open = sum(row["open_post_start_snapshot_count"] for row in strategy_rows)
    return {
        "watch_id": str(shadow_report.get("watch_id")),
        "status": str(shadow_report.get("status")),
        "prospective_start_utc": str(shadow_report.get("prospective_start_utc")),
        "as_of_utc": str(shadow_report.get("as_of_utc")),
        "calendar_days_elapsed": int(shadow_report.get("calendar_days_elapsed") or 0),
        "ready_strategy_count": int(progress.get("ready_strategy_count") or 0),
        "strategy_count": int(progress.get("strategy_count") or len(strategy_rows)),
        "all_strategies_ready": bool(progress.get("all_strategies_ready")),
        "total_completed_trade_count": total_completed,
        "total_open_post_start_snapshot_count": total_open,
        "has_any_post_start_observation": bool(total_completed or total_open),
        "strategies": strategy_rows,
        "protocol_integrity_flags": protocol_integrity_flags,
        "forbidden_claims": forbidden_claims,
        "decision_scope": "research_orchestration_only",
        "never_authorized": [
            "strategy_promotion",
            "live_trading",
            "leverage",
            "signal_rule_changes",
            "frozen_hypothesis_changes",
        ],
    }


def build_question_specs() -> dict[str, dict[str, Any]]:
    return {
        "research_action": {
            "type": "choice",
            "instructions": (
                "Choose the most useful next research action from the allowed set. "
                "When there are no post-start observations, prefer collecting more evidence "
                "unless the supplied state shows a concrete data-quality problem. "
                "Do not recommend live trading, leverage, strategy promotion, or changing "
                "frozen definitions."
            ),
            "criteria": {
                "collect_more_evidence": "Keep the frozen shadow accumulating unchanged.",
                "inspect_data_quality": "Investigate source integrity, missingness, or accounting anomalies.",
                "inspect_state_coverage": "Inspect whether frozen comparison states and symbols are adequately represented.",
                "prepare_formal_review": "Prepare the frozen review package after deterministic review gates are met.",
                "stop_protocol_breach": "Stop because frozen protocol integrity appears compromised.",
            },
        },
        "dominant_uncertainty": {
            "type": "choice",
            "instructions": "Which uncertainty currently limits interpretation the most?",
            "criteria": {name: None for name in UNCERTAINTY_OPTIONS},
        },
        "protocol_intact": {
            "type": "noul",
            "instructions": "Does the supplied state indicate that the frozen research protocol remains intact?",
            "criteria": {
                "true": "No supplied fact indicates a frozen-protocol breach.",
                "false": "At least one supplied fact indicates a frozen-protocol breach.",
            },
        },
        "evidence_maturity": {
            "type": "score",
            "instructions": "Rate the maturity of the prospective evidence only.",
            "criteria": list(MATURITY_LEVELS),
        },
    }


def deterministic_protocol_breach(state: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    flags = state.get("protocol_integrity_flags") or {}
    for key, value in flags.items():
        if not bool(value):
            reasons.append(f"required_integrity_flag_false:{key}")
    forbidden = state.get("forbidden_claims") or {}
    for key, value in forbidden.items():
        if bool(value):
            reasons.append(f"forbidden_claim_true:{key}")
    for row in state.get("strategies") or []:
        if str(row.get("formal_verdict")) != "WITHHELD":
            reasons.append(f"early_formal_verdict:{row.get('audit_id')}")
    return reasons


def offline_judgments(state: Mapping[str, Any]) -> dict[str, Any]:
    breach = deterministic_protocol_breach(state)
    if breach:
        action = "stop_protocol_breach"
        uncertainty = "data_quality"
        maturity = 4.0
    elif bool(state.get("all_strategies_ready")):
        action = "prepare_formal_review"
        uncertainty = "none"
        maturity = 3.0
    elif str(state.get("status")) == "PRE_START":
        action = "collect_more_evidence"
        uncertainty = "sample_size"
        maturity = 0.0
    elif not bool(state.get("has_any_post_start_observation")):
        action = "collect_more_evidence"
        uncertainty = "sample_size"
        maturity = 1.0
    elif int(state.get("total_completed_trade_count") or 0) == 0:
        action = "collect_more_evidence"
        uncertainty = "sample_size"
        maturity = 1.0
    else:
        strategies = state.get("strategies") or []
        sparse_states = any(
            any(not item.get("both_states_observed") for item in row.get("hypothesis_state_coverage") or [])
            for row in strategies
        )
        action = "inspect_state_coverage" if sparse_states else "collect_more_evidence"
        uncertainty = "state_coverage" if sparse_states else "sample_size"
        maturity = 2.0 if int(state.get("calendar_days_elapsed") or 0) > 0 else 1.0
    return {
        "provider": "offline_deterministic",
        "model": "none",
        "research_action": {
            "choice": action,
            "confidence": 1.0,
            "probabilities": {action: 1.0},
        },
        "dominant_uncertainty": {
            "choice": uncertainty,
            "confidence": 1.0,
            "probabilities": {uncertainty: 1.0},
        },
        "protocol_intact": {
            "noul": 0.0 if breach else 1.0,
        },
        "evidence_maturity": {
            "score": maturity,
            "confidence": 1.0,
        },
    }


def _choice_payload(value: Any) -> dict[str, Any]:
    return {
        "choice": str(value.choice),
        "confidence": float(value.confidence),
        "probabilities": {
            str(k): float(v) for k, v in dict(value.probabilities).items()
        },
    }


async def call_typesafe_jev(
    state: Mapping[str, Any],
    *,
    config: JevDecisionConfig = JevDecisionConfig(),
) -> dict[str, Any]:
    if not os.getenv("TYPESAFE_API_KEY"):
        raise JevResearchDecisionError("TYPESAFE_API_KEY is required for provider=jev")
    try:
        from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, Score
    except ImportError as exc:
        raise JevResearchDecisionError(
            "typesafe-sdk is not installed; install the project with the jev extra"
        ) from exc

    specs = build_question_specs()
    questions = {
        "research_action": Choice(
            instructions=specs["research_action"]["instructions"],
            criteria=specs["research_action"]["criteria"],
        ),
        "dominant_uncertainty": Choice(
            instructions=specs["dominant_uncertainty"]["instructions"],
            criteria=specs["dominant_uncertainty"]["criteria"],
        ),
        "protocol_intact": Noul(
            instructions=specs["protocol_intact"]["instructions"],
            criteria=specs["protocol_intact"]["criteria"],
        ),
        "evidence_maturity": Score(
            instructions=specs["evidence_maturity"]["instructions"],
            criteria=specs["evidence_maturity"]["criteria"],
        ),
    }
    async with AsyncTypeSafeClient(
        model=config.model,
        retry=RetryPolicy(max_retries=1, timeout=config.timeout_s),
    ) as client:
        response = await client.system_one(state=dict(state), questions=questions)
    return {
        "provider": "typesafe_jev",
        "model": str(response.model),
        "request_id": getattr(response, "request_id", None),
        "research_action": _choice_payload(response.choices["research_action"]),
        "dominant_uncertainty": _choice_payload(
            response.choices["dominant_uncertainty"]
        ),
        "protocol_intact": {
            "noul": float(response.nouls["protocol_intact"].noul),
        },
        "evidence_maturity": {
            "score": float(response.scores["evidence_maturity"].score),
            "confidence": float(
                response.scores["evidence_maturity"].confidence
            ),
        },
    }


def allowed_actions(state: Mapping[str, Any]) -> tuple[str, ...]:
    if deterministic_protocol_breach(state):
        return ("stop_protocol_breach",)
    if bool(state.get("all_strategies_ready")):
        return (
            "prepare_formal_review",
            "inspect_data_quality",
            "inspect_state_coverage",
        )
    if int(state.get("total_completed_trade_count") or 0) == 0:
        return (
            "collect_more_evidence",
            "inspect_data_quality",
        )
    return (
        "collect_more_evidence",
        "inspect_data_quality",
        "inspect_state_coverage",
    )


def apply_policy(
    state: Mapping[str, Any],
    judgments: Mapping[str, Any],
    *,
    min_choice_confidence: float = 0.65,
) -> dict[str, Any]:
    breach = deterministic_protocol_breach(state)
    allowed = allowed_actions(state)
    proposed = str((judgments.get("research_action") or {}).get("choice", ""))
    confidence = float(
        (judgments.get("research_action") or {}).get("confidence") or 0.0
    )

    if breach:
        selected = "stop_protocol_breach"
        source = "hard_protocol_veto"
    elif proposed in allowed and confidence >= min_choice_confidence:
        selected = proposed
        provider = str(judgments.get("provider") or "")
        if provider == "typesafe_jev":
            source = "jev_bounded_choice"
        elif provider == "offline_deterministic":
            source = "offline_bounded_choice"
        else:
            source = "bounded_choice"
    elif bool(state.get("all_strategies_ready")):
        selected = "prepare_formal_review"
        source = "deterministic_fallback"
    else:
        selected = "collect_more_evidence"
        source = "deterministic_fallback"

    return {
        "selected_action": selected,
        "selection_source": source,
        "allowed_actions": list(allowed),
        "proposed_action": proposed or None,
        "proposed_action_confidence": confidence,
        "protocol_breach_reasons": breach,
        "hard_vetoes": {
            "strategy_promotion_authorized": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
            "frozen_definition_changes_authorized": False,
        },
    }


async def decide(
    shadow_report: Mapping[str, Any],
    *,
    provider: str = "auto",
    config: JevDecisionConfig = JevDecisionConfig(),
) -> dict[str, Any]:
    state = build_research_state(shadow_report)
    provider = str(provider).lower()
    if provider not in {"auto", "jev", "offline"}:
        raise JevResearchDecisionError("provider must be auto, jev, or offline")

    if provider == "offline":
        judgments = offline_judgments(state)
    elif provider == "jev":
        judgments = await call_typesafe_jev(state, config=config)
    else:
        if os.getenv("TYPESAFE_API_KEY"):
            try:
                judgments = await call_typesafe_jev(state, config=config)
            except JevResearchDecisionError:
                judgments = offline_judgments(state)
        else:
            judgments = offline_judgments(state)

    policy = apply_policy(
        state,
        judgments,
        min_choice_confidence=config.min_choice_confidence,
    )
    contract = {
        "state": state,
        "questions": build_question_specs(),
    }
    return {
        "schema_version": 1,
        "analysis": "jev_research_decision_layer_v1",
        "decision_id": sha256(_canonical_json(contract).encode("utf-8")).hexdigest(),
        "provider": judgments.get("provider"),
        "model": judgments.get("model"),
        "decision_config": {
            "requested_model": config.model,
            "min_choice_confidence": config.min_choice_confidence,
            "timeout_s": config.timeout_s,
        },
        "state": state,
        "judgments": judgments,
        "policy": policy,
        "claims": {
            "research_orchestration_only": True,
            "frozen_shadow_unchanged": True,
            "jev_cannot_promote_strategy": True,
            "jev_cannot_authorize_live_trading": True,
            "jev_cannot_authorize_leverage": True,
            "jev_cannot_change_frozen_definitions": True,
        },
    }


def decide_sync(
    shadow_report: Mapping[str, Any],
    *,
    provider: str = "auto",
    config: JevDecisionConfig = JevDecisionConfig(),
) -> dict[str, Any]:
    return asyncio.run(decide(shadow_report, provider=provider, config=config))

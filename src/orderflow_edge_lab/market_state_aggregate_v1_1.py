from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .market_state_aggregate import aggregate_market_state_reports


class MarketStateAggregateV11Error(ValueError):
    pass


def _load_protocol(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_name") != "regime-research-v1.1":
        raise MarketStateAggregateV11Error("not a regime-research-v1.1 protocol")
    return payload


def _eligible_report_paths(report_paths: Iterable[str | Path], minimum_batch_id: str) -> list[Path]:
    eligible: list[Path] = []
    for source in report_paths:
        path = Path(source)
        payload = json.loads(path.read_text(encoding="utf-8"))
        batch_id = str(payload.get("batch_id") or "")
        if batch_id and batch_id >= minimum_batch_id:
            eligible.append(path)
    return eligible


def build_v1_1_state_screen(
    report_paths: Iterable[str | Path],
    protocol_path: str | Path,
) -> dict[str, Any]:
    protocol = _load_protocol(protocol_path)
    rules = protocol["state_screen"]
    minimum_batch_id = str(protocol["evidence_start_batch_id"])
    eligible_paths = _eligible_report_paths(report_paths, minimum_batch_id)

    if not eligible_paths:
        return {
            "schema_version": 1,
            "experiment": "regime_research_v1_1_market_state_screen",
            "protocol_name": protocol["protocol_name"],
            "protocol_frozen_at_utc": protocol["frozen_at_utc"],
            "evidence_start_batch_id": minimum_batch_id,
            "status": "waiting_for_forward_batches",
            "independent_batch_count": 0,
            "eligible_state_association_count": 0,
            "eligible_incremental_feature_count": 0,
            "association_summary": [],
            "incremental_information": [],
            "claims": dict(protocol["claims"]),
        }

    base = aggregate_market_state_reports(
        eligible_paths,
        minimum_independent_batches=int(rules["minimum_independent_batches"]),
        minimum_positive_batch_fraction=float(rules["minimum_dominant_sign_fraction"]),
        minimum_association_observations=int(rules["minimum_association_observations_per_batch"]),
        redundancy_abs_spearman_threshold=float(rules["redundancy_abs_spearman_threshold"]),
    )

    min_abs = float(rules["minimum_median_abs_spearman"])
    eligible_associations = 0
    for row in base.get("association_summary", []):
        effect = abs(float(row.get("median_spearman") or 0.0)) >= min_abs
        row["v1_1_effect_size_floor_passed"] = effect
        row["v1_1_eligible_state_association"] = bool(row.get("stable_sign_across_batches") and effect)
        eligible_associations += int(row["v1_1_eligible_state_association"])

    min_partial = float(rules["minimum_median_abs_partial_spearman"])
    eligible_incremental = 0
    for row in base.get("incremental_information", []):
        value = row.get("median_partial_spearman")
        effect = value is not None and abs(float(value)) >= min_partial
        row["v1_1_effect_size_floor_passed"] = effect
        row["v1_1_eligible_incremental_feature"] = bool(
            row.get("stable_incremental_sign_across_batches") and effect
        )
        eligible_incremental += int(row["v1_1_eligible_incremental_feature"])

    enough_batches = int(base.get("independent_batch_count") or 0) >= int(rules["minimum_independent_batches"])
    base.update(
        {
            "experiment": "regime_research_v1_1_market_state_screen",
            "protocol_name": protocol["protocol_name"],
            "protocol_frozen_at_utc": protocol["frozen_at_utc"],
            "evidence_start_batch_id": minimum_batch_id,
            "status": "screen_ready" if enough_batches else "collecting_forward_batches",
            "eligible_state_association_count": eligible_associations,
            "eligible_incremental_feature_count": eligible_incremental,
            "v1_1_readiness": {
                "minimum_independent_batches": int(rules["minimum_independent_batches"]),
                "minimum_median_abs_spearman": min_abs,
                "minimum_median_abs_partial_spearman": min_partial,
                "enough_forward_batches": enough_batches,
                "state_hypothesis_available_for_separate_conditioning_test": bool(
                    enough_batches and eligible_associations > 0
                ),
                "automatic_strategy_conditioning_permitted": False,
            },
            "claims": {
                **dict(protocol["claims"]),
                "market_state_first": True,
                "strategy_pnl_used": False,
                "effect_size_floor_applied": True,
                "incremental_information_checked": True,
                "state_screen_is_not_strategy_promotion": True,
            },
        }
    )
    return base

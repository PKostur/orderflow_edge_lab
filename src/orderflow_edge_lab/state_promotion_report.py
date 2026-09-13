from __future__ import annotations

from typing import Any, Mapping


class StatePromotionReportError(ValueError):
    pass


def _cluster_maps(feature_redundancy: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    feature_to_cluster: dict[str, str] = {}
    feature_to_representative: dict[str, str] = {}
    clusters = feature_redundancy.get("clusters", [])
    representatives = feature_redundancy.get("representatives", {})
    for index, cluster in enumerate(clusters, start=1):
        cluster_id = f"cluster_{index}"
        representative = representatives.get(cluster_id)
        if representative is None:
            continue
        for feature in cluster:
            feature_name = str(feature)
            feature_to_cluster[feature_name] = cluster_id
            feature_to_representative[feature_name] = str(representative)
    return feature_to_cluster, feature_to_representative


def _incremental_map(rows: list[Mapping[str, Any]]) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    output: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("research_family")),
            str(row.get("feature")),
            str(row.get("target")),
        )
        output[key] = row
    return output


def build_state_promotion_report(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    if aggregate.get("experiment") != "regime_research_v1_1_market_state_screen":
        raise StatePromotionReportError("input is not a regime-research-v1.1 market-state screen")

    redundancy = aggregate.get("feature_redundancy", {})
    feature_to_cluster, feature_to_representative = _cluster_maps(redundancy)
    incremental = _incremental_map(list(aggregate.get("incremental_information", [])))

    rows: list[dict[str, Any]] = []
    for association in aggregate.get("association_summary", []):
        family = str(association.get("research_family"))
        feature = str(association.get("feature"))
        target = str(association.get("target"))
        cluster_id = feature_to_cluster.get(feature)
        representative = feature_to_representative.get(feature)
        is_representative = representative is None or representative == feature
        incremental_row = incremental.get((family, feature, target))
        incremental_passed = None
        if incremental_row is not None:
            incremental_passed = bool(incremental_row.get("v1_1_eligible_incremental_feature"))

        state_screen_passed = bool(association.get("v1_1_eligible_state_association"))
        v1_conditioning_candidate = bool(state_screen_passed and is_representative)
        rows.append(
            {
                "research_family": family,
                "feature": feature,
                "target": target,
                "independent_batches": int(association.get("independent_batches") or 0),
                "total_observations": int(association.get("total_observations") or 0),
                "median_spearman": association.get("median_spearman"),
                "dominant_sign": association.get("dominant_sign"),
                "dominant_sign_fraction": association.get("dominant_sign_fraction"),
                "effect_size_floor_passed": bool(association.get("v1_1_effect_size_floor_passed")),
                "state_screen_passed": state_screen_passed,
                "redundancy_cluster": cluster_id,
                "cluster_representative": representative,
                "is_pnl_independent_cluster_representative": is_representative,
                "incremental_partial_spearman": (
                    incremental_row.get("median_partial_spearman") if incremental_row is not None else None
                ),
                "incremental_information_passed": incremental_passed,
                "eligible_for_strategy_conditioning_v1_freeze": v1_conditioning_candidate,
            }
        )

    rows.sort(key=lambda row: (row["research_family"], row["feature"], row["target"]))
    eligible = [row for row in rows if row["eligible_for_strategy_conditioning_v1_freeze"]]
    readiness = aggregate.get("v1_1_readiness", {})
    return {
        "schema_version": 1,
        "experiment": "state_promotion_report_v1",
        "source_protocol": aggregate.get("protocol_name"),
        "source_status": aggregate.get("status"),
        "evidence_start_batch_id": aggregate.get("evidence_start_batch_id"),
        "independent_batch_count": int(aggregate.get("independent_batch_count") or 0),
        "minimum_independent_batches": readiness.get("minimum_independent_batches"),
        "screen_ready": bool(readiness.get("enough_forward_batches")),
        "candidate_count": len(eligible),
        "candidates": rows,
        "selection_rule": (
            "lexical reporting only; no strategy PnL, PF, expectancy, or return field is used for ranking or selection"
        ),
        "claims": {
            "market_state_first": True,
            "strategy_pnl_used": False,
            "pnl_fields_present": False,
            "redundancy_representative_required_for_strategy_conditioning_v1": True,
            "secondary_redundant_feature_requires_separate_versioned_protocol": True,
            "cross_pair_transfer_still_required": True,
            "transfer_is_not_untouched_oos": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

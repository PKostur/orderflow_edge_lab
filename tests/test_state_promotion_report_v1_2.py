from orderflow_edge_lab.state_promotion_report_v1_2 import (
    StatePromotionReportV12Error,
    build_state_promotion_report_v1_2,
)


def _aggregate() -> dict:
    return {
        "experiment": "regime_research_v1_2_market_state_screen",
        "protocol_name": "regime-research-v1.2",
        "status": "screen_ready",
        "evidence_start_utc": "2026-09-13T02:00:00Z",
        "evidence_start_batch_id": "20260913T020000Z",
        "independent_batch_count": 5,
        "association_summary": [
            {
                "research_family": "liquidity_microstructure",
                "feature": "spread_bps",
                "target": "future_spread_5s",
                "independent_batches": 5,
                "total_observations": 200,
                "median_spearman": 0.31,
                "dominant_sign": 1,
                "dominant_sign_fraction": 1.0,
                "v1_2_effect_size_floor_passed": True,
                "v1_2_eligible_state_association": True,
            },
            {
                "research_family": "liquidity_microstructure",
                "feature": "microprice_edge_bps",
                "target": "future_spread_5s",
                "independent_batches": 5,
                "total_observations": 200,
                "median_spearman": 0.29,
                "dominant_sign": 1,
                "dominant_sign_fraction": 1.0,
                "v1_2_effect_size_floor_passed": True,
                "v1_2_eligible_state_association": True,
            },
        ],
        "feature_redundancy": {
            "clusters": [["spread_bps", "microprice_edge_bps"]],
            "representatives": {"cluster_1": "spread_bps"},
        },
        "incremental_information": [
            {
                "research_family": "liquidity_microstructure",
                "feature": "microprice_edge_bps",
                "target": "future_spread_5s",
                "median_partial_spearman": 0.04,
                "v1_2_eligible_incremental_feature": False,
            }
        ],
        "dependence_audit": {
            "independent_cluster_count": 5,
            "collapsed_report_count": 2,
        },
        "v1_2_readiness": {
            "minimum_independent_batches": 5,
            "enough_forward_dependence_clusters": True,
        },
    }


def test_only_pnl_independent_cluster_representative_is_conditioning_candidate() -> None:
    report = build_state_promotion_report_v1_2(_aggregate())
    assert report["screen_ready"] is True
    assert report["independent_dependence_cluster_count"] == 5
    assert report["collapsed_report_count"] == 2
    assert report["candidate_count"] == 1
    candidates = {row["feature"]: row for row in report["candidates"]}
    assert candidates["spread_bps"]["eligible_for_strategy_conditioning_v1_1_freeze"] is True
    assert candidates["microprice_edge_bps"]["eligible_for_strategy_conditioning_v1_1_freeze"] is False
    assert report["claims"]["strategy_pnl_used"] is False
    assert report["claims"]["dependence_clusters_counted_instead_of_raw_capture_ids"] is True


def test_rejects_non_v1_2_input() -> None:
    aggregate = _aggregate()
    aggregate["experiment"] = "regime_research_v1_1_market_state_screen"
    try:
        build_state_promotion_report_v1_2(aggregate)
    except StatePromotionReportV12Error:
        pass
    else:
        raise AssertionError("expected StatePromotionReportV12Error")

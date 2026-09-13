from orderflow_edge_lab.state_promotion_report import build_state_promotion_report


def test_state_promotion_report_keeps_pnl_out_and_requires_representative() -> None:
    aggregate = {
        "experiment": "regime_research_v1_1_market_state_screen",
        "protocol_name": "regime-research-v1.1",
        "status": "screen_ready",
        "evidence_start_batch_id": "20260912T210000Z",
        "independent_batch_count": 5,
        "v1_1_readiness": {
            "minimum_independent_batches": 5,
            "enough_forward_batches": True,
        },
        "association_summary": [
            {
                "research_family": "liquidity_stability_deterioration",
                "feature": "spread_bps",
                "target": "future_spread_bps_5s",
                "independent_batches": 5,
                "total_observations": 500,
                "median_spearman": 0.42,
                "dominant_sign": "positive",
                "dominant_sign_fraction": 1.0,
                "v1_1_effect_size_floor_passed": True,
                "v1_1_eligible_state_association": True,
            },
            {
                "research_family": "directionality_vs_chop",
                "feature": "trade_velocity_per_second",
                "target": "directionality_efficiency_30s",
                "independent_batches": 5,
                "total_observations": 500,
                "median_spearman": 0.18,
                "dominant_sign": "positive",
                "dominant_sign_fraction": 0.8,
                "v1_1_effect_size_floor_passed": True,
                "v1_1_eligible_state_association": True,
            },
        ],
        "feature_redundancy": {
            "clusters": [["rolling_trade_count_10s", "trade_velocity_per_second"]],
            "representatives": {"cluster_1": "rolling_trade_count_10s"},
        },
        "incremental_information": [
            {
                "research_family": "directionality_vs_chop",
                "feature": "trade_velocity_per_second",
                "target": "directionality_efficiency_30s",
                "median_partial_spearman": 0.03,
                "v1_1_eligible_incremental_feature": False,
            }
        ],
    }

    report = build_state_promotion_report(aggregate)

    assert report["candidate_count"] == 1
    assert report["claims"]["strategy_pnl_used"] is False
    assert report["claims"]["pnl_fields_present"] is False
    by_feature = {row["feature"]: row for row in report["candidates"]}
    assert by_feature["spread_bps"]["eligible_for_strategy_conditioning_v1_freeze"] is True
    assert by_feature["trade_velocity_per_second"]["eligible_for_strategy_conditioning_v1_freeze"] is False
    assert by_feature["trade_velocity_per_second"]["incremental_information_passed"] is False


def test_state_promotion_report_is_not_ready_before_batch_floor() -> None:
    aggregate = {
        "experiment": "regime_research_v1_1_market_state_screen",
        "protocol_name": "regime-research-v1.1",
        "status": "collecting_forward_batches",
        "evidence_start_batch_id": "20260912T210000Z",
        "independent_batch_count": 2,
        "v1_1_readiness": {
            "minimum_independent_batches": 5,
            "enough_forward_batches": False,
        },
        "association_summary": [],
        "feature_redundancy": {"clusters": [], "representatives": {}},
        "incremental_information": [],
    }

    report = build_state_promotion_report(aggregate)

    assert report["screen_ready"] is False
    assert report["candidate_count"] == 0

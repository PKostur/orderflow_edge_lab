import json

from orderflow_edge_lab.strategy_conditioning_freeze_v1_1 import (
    StrategyConditioningFreezeV11Error,
    build_strategy_conditioning_freeze_v1_1,
    verify_strategy_conditioning_freeze_v1_1,
)


def _protocol() -> dict:
    return {
        "protocol_name": "strategy-conditioning-v1.1",
        "upstream_state_protocol": "regime-research-v1.2",
        "baseline_strategy_protocol": "discovery-v1",
        "frozen_after_commit": "abc",
        "eligibility": {
            "required_state_screen_status": "screen_ready",
            "minimum_independent_dependence_clusters": 5,
            "minimum_dominant_sign_fraction": 0.8,
            "minimum_median_abs_spearman": 0.1,
            "dependence_gap_seconds": 300,
            "require_pnl_independent_redundancy_representative": True,
        },
        "trial_design": {"maximum_features": 1},
        "evaluation": {"required_outputs": []},
        "claims": {
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }


def _screen() -> dict:
    return {
        "experiment": "regime_research_v1_2_market_state_screen",
        "protocol_name": "regime-research-v1.2",
        "status": "screen_ready",
        "v1_2_readiness": {"enough_forward_dependence_clusters": True},
        "claims": {"strategy_pnl_used": False},
        "dependence_audit": {
            "independent_cluster_count": 5,
            "collapsed_report_count": 1,
            "dependence_gap_seconds": 300,
        },
        "association_summary": [
            {
                "research_family": "liquidity_microstructure",
                "feature": "spread_bps",
                "target": "future_spread_5s",
                "v1_2_eligible_state_association": True,
                "independent_batches": 5,
                "dominant_sign": 1,
                "dominant_sign_fraction": 1.0,
                "median_spearman": 0.3,
                "total_observations": 250,
            }
        ],
        "feature_redundancy": {
            "clusters": [["spread_bps", "microprice_edge_bps"]],
            "representatives": {"cluster_1": "spread_bps"},
        },
    }


def test_builds_manifest_from_v1_2_dependence_clusters(tmp_path) -> None:
    protocol_path = tmp_path / "protocol.json"
    screen_path = tmp_path / "screen.json"
    protocol_path.write_text(json.dumps(_protocol()), encoding="utf-8")
    screen_path.write_text(json.dumps(_screen()), encoding="utf-8")

    frozen = build_strategy_conditioning_freeze_v1_1(
        screen_path,
        protocol_path,
        research_family="liquidity_microstructure",
        feature="spread_bps",
        target="future_spread_5s",
    )

    assert frozen["experiment"] == "strategy_conditioning_v1_1_freeze"
    assert frozen["state_hypothesis"]["independent_dependence_clusters"] == 5
    assert frozen["dependence_audit"]["dependence_gap_seconds"] == 300
    assert frozen["claims"]["state_screen_passed_before_strategy_pnl_test"] is True
    assert verify_strategy_conditioning_freeze_v1_1(frozen) is True


def test_rejects_redundant_nonrepresentative(tmp_path) -> None:
    protocol_path = tmp_path / "protocol.json"
    screen_path = tmp_path / "screen.json"
    protocol_path.write_text(json.dumps(_protocol()), encoding="utf-8")
    screen = _screen()
    screen["association_summary"][0]["feature"] = "microprice_edge_bps"
    screen_path.write_text(json.dumps(screen), encoding="utf-8")

    try:
        build_strategy_conditioning_freeze_v1_1(
            screen_path,
            protocol_path,
            research_family="liquidity_microstructure",
            feature="microprice_edge_bps",
            target="future_spread_5s",
        )
    except StrategyConditioningFreezeV11Error:
        pass
    else:
        raise AssertionError("expected StrategyConditioningFreezeV11Error")

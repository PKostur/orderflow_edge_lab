import json

from orderflow_edge_lab.state_candidate_registry_v1 import build_state_candidate_registry_v1
from orderflow_edge_lab.strategy_conditioning_registry_binding_v1 import (
    build_registry_bound_conditioning_freeze_v1,
    verify_registry_bound_conditioning_freeze_v1,
)


def _screen() -> dict:
    return {
        "experiment": "regime_research_v1_2_market_state_screen",
        "protocol_name": "regime-research-v1.2",
        "status": "screen_ready",
        "v1_2_readiness": {"enough_forward_dependence_clusters": True},
        "claims": {"strategy_pnl_used": False},
        "dependence_audit": {"independent_cluster_count": 5, "collapsed_report_count": 0, "dependence_gap_seconds": 300},
        "association_summary": [{
            "research_family": "liquidity_microstructure",
            "feature": "spread_bps",
            "target": "future_spread_5s",
            "v1_2_eligible_state_association": True,
            "independent_batches": 5,
            "dominant_sign": 1,
            "dominant_sign_fraction": 1.0,
            "median_spearman": 0.3,
            "total_observations": 250,
        }],
        "feature_redundancy": {"clusters": [["spread_bps"]], "representatives": {"cluster_1": "spread_bps"}},
    }


def _conditioning_protocol() -> dict:
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
        "claims": {"verified_out_of_sample_evidence": False, "profitable_edge_established": False, "live_order_transmission_supported": False},
    }


def _registry_protocol() -> dict:
    return {
        "protocol_name": "state-candidate-registry-v1",
        "upstream_promotion_experiment": "state_promotion_report_v1_2",
        "upstream_state_protocol": "regime-research-v1.2",
        "downstream_conditioning_protocol": "strategy-conditioning-v1.1",
        "frozen_after_commit": "abc",
        "selection": {"maximum_locked_candidates": 1, "eligibility_field": "eligible_for_strategy_conditioning_v1_1_freeze"},
        "claims": {},
    }


def _binding_protocol() -> dict:
    return {
        "protocol_name": "strategy-conditioning-registry-binding-v1",
        "upstream_registry_protocol": "state-candidate-registry-v1",
        "upstream_state_protocol": "regime-research-v1.2",
        "downstream_conditioning_protocol": "strategy-conditioning-v1.1",
        "claims": {"profitable_edge_established": False},
    }


def test_freeze_uses_exact_registry_lock(tmp_path) -> None:
    promotion = {
        "experiment": "state_promotion_report_v1_2",
        "source_protocol": "regime-research-v1.2",
        "screen_ready": True,
        "independent_dependence_cluster_count": 5,
        "candidates": [{
            "research_family": "liquidity_microstructure",
            "feature": "spread_bps",
            "target": "future_spread_5s",
            "eligible_for_strategy_conditioning_v1_1_freeze": True,
        }],
    }
    registry = build_state_candidate_registry_v1(promotion, _registry_protocol())
    screen_path = tmp_path / "screen.json"
    registry_path = tmp_path / "registry.json"
    binding_path = tmp_path / "binding.json"
    conditioning_path = tmp_path / "conditioning.json"
    screen_path.write_text(json.dumps(_screen()), encoding="utf-8")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    binding_path.write_text(json.dumps(_binding_protocol()), encoding="utf-8")
    conditioning_path.write_text(json.dumps(_conditioning_protocol()), encoding="utf-8")

    result = build_registry_bound_conditioning_freeze_v1(screen_path, registry_path, binding_path, conditioning_path)
    assert result["status"] == "frozen"
    assert result["locked_candidate"]["feature"] == "spread_bps"
    assert result["conditioning_freeze"]["state_hypothesis"]["feature"] == "spread_bps"
    assert result["claims"]["registry_candidate_bound_before_conditioned_pnl"] is True
    assert verify_registry_bound_conditioning_freeze_v1(result) is True


def test_no_lock_does_not_freeze(tmp_path) -> None:
    promotion = {
        "experiment": "state_promotion_report_v1_2",
        "source_protocol": "regime-research-v1.2",
        "screen_ready": False,
        "independent_dependence_cluster_count": 2,
        "candidates": [],
    }
    registry = build_state_candidate_registry_v1(promotion, _registry_protocol())
    screen_path = tmp_path / "screen.json"
    registry_path = tmp_path / "registry.json"
    binding_path = tmp_path / "binding.json"
    conditioning_path = tmp_path / "conditioning.json"
    screen_path.write_text(json.dumps(_screen()), encoding="utf-8")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    binding_path.write_text(json.dumps(_binding_protocol()), encoding="utf-8")
    conditioning_path.write_text(json.dumps(_conditioning_protocol()), encoding="utf-8")

    result = build_registry_bound_conditioning_freeze_v1(screen_path, registry_path, binding_path, conditioning_path)
    assert result["status"] == "no_locked_candidate"
    assert result["conditioning_freeze"] is None

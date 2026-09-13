import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_v1_3_preserves_prior_protocol_boundaries():
    v1 = _load("regime_research_v1.json")
    v12 = _load("regime_research_v1_2.json")
    v13 = _load("regime_research_v1_3.json")

    assert v13["protocol_name"] == "regime-research-v1.3"
    assert v13["inherits"]["feature_and_target_definitions"] == v1["protocol_name"]
    assert v13["inherits"]["dependence_clustering"] == v12["protocol_name"]
    assert v13["claims"]["changes_regime_research_v1_scan_definitions"] is False
    assert v13["claims"]["changes_regime_research_v1_1_effect_thresholds"] is False
    assert v13["claims"]["changes_regime_research_v1_2_dependence_rules"] is False
    assert v13["claims"]["changes_discovery_v1_strategy_definitions"] is False
    assert v13["claims"]["uses_strategy_pnl_for_state_selection"] is False
    assert v13["claims"]["verified_out_of_sample_evidence"] is False
    assert v13["claims"]["profitable_edge_established"] is False
    assert v13["claims"]["live_order_transmission_supported"] is False


def test_v1_3_representatives_are_existing_v1_features():
    v1 = _load("regime_research_v1.json")
    v13 = _load("regime_research_v1_3.json")

    available = {
        indicator
        for family in v1["specialist_families"].values()
        for indicator in family.get("indicators", [])
    }
    for spec in v13["primary_family_representatives"].values():
        assert spec["feature"] in available

    for test in v13["predeclared_incremental_tests"]:
        assert test["base_feature"] in available
        assert test["candidate_feature"] in available


def test_v1_3_enforces_state_first_and_orthogonality_rules():
    v13 = _load("regime_research_v1_3.json")

    assert v13["sequencing"]["market_state_prediction_first"] is True
    assert v13["sequencing"]["strategy_conditioning_only_after_state_screen"] is True
    assert v13["sequencing"]["conditioning_requires_separate_frozen_protocol"] is True
    assert v13["redundancy_policy"]["no_pf_selection"] is True
    assert v13["redundancy_policy"]["no_strategy_pnl_selection"] is True
    assert (
        v13["redundancy_policy"]
        ["second_feature_requires_incremental_information_or_prespecified_interaction"]
        is True
    )
    assert v13["dependence_policy"]["independent_capture_batches_are_dependence_clusters"] is True
    assert v13["dependence_policy"]["representative_selection_uses_strategy_pnl"] is False


def test_v1_3_freeze_precedes_evidence_boundary():
    v13 = _load("regime_research_v1_3.json")
    assert v13["frozen_at_utc"] < v13["evidence_start_utc"]
    assert v13["evidence_start_batch_id"] == "20260913T130000Z"

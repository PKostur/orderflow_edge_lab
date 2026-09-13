from __future__ import annotations

import pytest

from orderflow_edge_lab.state_candidate_registry_v1 import (
    StateCandidateRegistryV1Error,
    build_state_candidate_registry_v1,
    verify_state_candidate_registry_v1,
)


def _protocol() -> dict:
    return {
        "protocol_name": "state-candidate-registry-v1",
        "upstream_promotion_experiment": "state_promotion_report_v1_2",
        "upstream_state_protocol": "regime-research-v1.2",
        "downstream_conditioning_protocol": "strategy-conditioning-v1.1",
        "frozen_after_commit": "abc123",
        "selection": {
            "maximum_locked_candidates": 1,
            "eligibility_field": "eligible_for_strategy_conditioning_v1_1_freeze",
        },
        "claims": {
            "uses_strategy_pnl_for_selection": False,
            "uses_state_association_magnitude_for_selection": False,
        },
    }


def _report(*rows: dict) -> dict:
    return {
        "experiment": "state_promotion_report_v1_2",
        "source_protocol": "regime-research-v1.2",
        "screen_ready": True,
        "independent_dependence_cluster_count": 5,
        "candidates": list(rows),
    }


def _candidate(family: str, feature: str, target: str, *, eligible: bool = True, spearman: float = 0.1) -> dict:
    return {
        "research_family": family,
        "feature": feature,
        "target": target,
        "median_spearman": spearman,
        "eligible_for_strategy_conditioning_v1_1_freeze": eligible,
    }


def test_locks_lexically_first_eligible_candidate_not_largest_association() -> None:
    report = _report(
        _candidate("volatility_regime", "zeta", "future_volatility", spearman=0.9),
        _candidate("liquidity_microstructure", "alpha", "future_liquidity", spearman=0.11),
        _candidate("aggressive_flow", "beta", "future_directionality", eligible=False, spearman=0.99),
    )
    registry = build_state_candidate_registry_v1(report, _protocol())
    assert registry["selection_newly_locked"] is True
    assert registry["locked_candidate"] == {
        "research_family": "liquidity_microstructure",
        "feature": "alpha",
        "target": "future_liquidity",
    }
    assert verify_state_candidate_registry_v1(registry)


def test_preserves_first_prior_lock_when_new_candidate_sorts_earlier() -> None:
    initial = build_state_candidate_registry_v1(
        _report(_candidate("volatility_regime", "zeta", "future_volatility")),
        _protocol(),
    )
    later = build_state_candidate_registry_v1(
        _report(
            _candidate("aggressive_flow", "alpha", "future_directionality"),
            _candidate("volatility_regime", "zeta", "future_volatility"),
        ),
        _protocol(),
        prior_registries=[initial],
    )
    assert later["selection_newly_locked"] is False
    assert later["locked_candidate"] == initial["locked_candidate"]
    assert later["locked_candidate_eligible_in_current_report"] is True


def test_prior_lock_remains_immutable_even_if_not_currently_eligible() -> None:
    initial = build_state_candidate_registry_v1(
        _report(_candidate("volatility_regime", "zeta", "future_volatility")),
        _protocol(),
    )
    later = build_state_candidate_registry_v1(
        _report(_candidate("aggressive_flow", "alpha", "future_directionality")),
        _protocol(),
        prior_registries=[initial],
    )
    assert later["locked_candidate"] == initial["locked_candidate"]
    assert later["locked_candidate_eligible_in_current_report"] is False


def test_rejects_conflicting_prior_locks() -> None:
    first = build_state_candidate_registry_v1(
        _report(_candidate("volatility_regime", "zeta", "future_volatility")),
        _protocol(),
    )
    second = build_state_candidate_registry_v1(
        _report(_candidate("aggressive_flow", "alpha", "future_directionality")),
        _protocol(),
    )
    with pytest.raises(StateCandidateRegistryV1Error, match="conflicting prior candidate locks"):
        build_state_candidate_registry_v1(
            _report(_candidate("liquidity_microstructure", "gamma", "future_liquidity")),
            _protocol(),
            prior_registries=[first, second],
        )


def test_registry_hash_detects_tampering() -> None:
    registry = build_state_candidate_registry_v1(
        _report(_candidate("volatility_regime", "zeta", "future_volatility")),
        _protocol(),
    )
    tampered = dict(registry)
    tampered["eligible_candidate_count"] = 99
    assert verify_state_candidate_registry_v1(registry)
    assert not verify_state_candidate_registry_v1(tampered)

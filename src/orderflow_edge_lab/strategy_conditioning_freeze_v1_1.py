from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class StrategyConditioningFreezeV11Error(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyConditioningFreezeV11Error(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise StrategyConditioningFreezeV11Error(f"JSON must be an object: {source}")
    return value


def _selected_association(
    screen: dict[str, Any], *, research_family: str, feature: str, target: str
) -> dict[str, Any]:
    matches = [
        row
        for row in screen.get("association_summary", [])
        if isinstance(row, dict)
        and row.get("research_family") == research_family
        and row.get("feature") == feature
        and row.get("target") == target
    ]
    if len(matches) != 1:
        raise StrategyConditioningFreezeV11Error("state association must resolve to exactly one v1.2 row")
    row = matches[0]
    if row.get("v1_2_eligible_state_association") is not True:
        raise StrategyConditioningFreezeV11Error("state association has not passed the frozen v1.2 screen")
    return row


def _assert_redundancy_representative(screen: dict[str, Any], feature: str) -> None:
    redundancy = screen.get("feature_redundancy")
    if not isinstance(redundancy, dict):
        raise StrategyConditioningFreezeV11Error("state screen lacks redundancy metadata")
    clusters = redundancy.get("clusters", [])
    representatives = redundancy.get("representatives", {})
    if not isinstance(clusters, list) or not isinstance(representatives, dict):
        raise StrategyConditioningFreezeV11Error("invalid redundancy metadata")
    for index, cluster in enumerate(clusters, start=1):
        if not isinstance(cluster, list) or feature not in cluster:
            continue
        representative = representatives.get(f"cluster_{index}")
        if representative != feature:
            raise StrategyConditioningFreezeV11Error(
                f"{feature} is redundant with another feature; primary conditioning must use PnL-independent representative {representative}"
            )


def build_strategy_conditioning_freeze_v1_1(
    state_screen_path: str | Path,
    protocol_path: str | Path,
    *,
    research_family: str,
    feature: str,
    target: str,
) -> dict[str, Any]:
    protocol = _load_object(protocol_path)
    if protocol.get("protocol_name") != "strategy-conditioning-v1.1":
        raise StrategyConditioningFreezeV11Error("not a strategy-conditioning-v1.1 protocol")
    screen = _load_object(state_screen_path)
    if screen.get("experiment") != "regime_research_v1_2_market_state_screen":
        raise StrategyConditioningFreezeV11Error("conditioning requires a regime-research-v1.2 state screen")
    if screen.get("protocol_name") != protocol.get("upstream_state_protocol"):
        raise StrategyConditioningFreezeV11Error("state-screen protocol mismatch")

    eligibility = protocol.get("eligibility")
    if not isinstance(eligibility, dict):
        raise StrategyConditioningFreezeV11Error("conditioning protocol lacks eligibility rules")
    if screen.get("status") != eligibility.get("required_state_screen_status"):
        raise StrategyConditioningFreezeV11Error("state screen is not ready for conditioning research")
    readiness = screen.get("v1_2_readiness")
    if not isinstance(readiness, dict) or readiness.get("enough_forward_dependence_clusters") is not True:
        raise StrategyConditioningFreezeV11Error("minimum forward dependence clusters have not matured")
    claims = screen.get("claims")
    if not isinstance(claims, dict):
        raise StrategyConditioningFreezeV11Error("state screen lacks claims metadata")
    pnl_independent = claims.get("strategy_pnl_used") is False or claims.get("uses_strategy_pnl_for_state_selection") is False
    if not pnl_independent:
        raise StrategyConditioningFreezeV11Error("state screen must be PnL-independent")

    dependence_audit = screen.get("dependence_audit")
    if not isinstance(dependence_audit, dict):
        raise StrategyConditioningFreezeV11Error("v1.2 state screen lacks dependence audit")
    if int(dependence_audit.get("independent_cluster_count") or 0) < int(
        eligibility["minimum_independent_dependence_clusters"]
    ):
        raise StrategyConditioningFreezeV11Error("insufficient independent dependence clusters")
    if int(dependence_audit.get("dependence_gap_seconds") or -1) != int(eligibility["dependence_gap_seconds"]):
        raise StrategyConditioningFreezeV11Error("dependence-gap mismatch")

    association = _selected_association(
        screen,
        research_family=research_family,
        feature=feature,
        target=target,
    )
    if int(association.get("independent_batches") or 0) < int(
        eligibility["minimum_independent_dependence_clusters"]
    ):
        raise StrategyConditioningFreezeV11Error("insufficient independent state clusters for association")
    if float(association.get("dominant_sign_fraction") or 0.0) < float(eligibility["minimum_dominant_sign_fraction"]):
        raise StrategyConditioningFreezeV11Error("state association sign stability is below the frozen floor")
    if abs(float(association.get("median_spearman") or 0.0)) < float(eligibility["minimum_median_abs_spearman"]):
        raise StrategyConditioningFreezeV11Error("state association effect magnitude is below the frozen floor")
    if eligibility.get("require_pnl_independent_redundancy_representative") is True:
        _assert_redundancy_representative(screen, feature)

    state_screen_sha256 = hashlib.sha256(Path(state_screen_path).read_bytes()).hexdigest()
    protocol_sha256 = hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest()
    frozen = {
        "schema_version": 1,
        "experiment": "strategy_conditioning_v1_1_freeze",
        "protocol_name": protocol["protocol_name"],
        "frozen_after_commit": protocol.get("frozen_after_commit"),
        "protocol_sha256": protocol_sha256,
        "state_screen_sha256": state_screen_sha256,
        "baseline_strategy_protocol": protocol["baseline_strategy_protocol"],
        "state_hypothesis": {
            "research_family": research_family,
            "feature": feature,
            "target": target,
            "dominant_sign": association.get("dominant_sign"),
            "dominant_sign_fraction": association.get("dominant_sign_fraction"),
            "median_spearman": association.get("median_spearman"),
            "independent_dependence_clusters": association.get("independent_batches"),
            "total_observations": association.get("total_observations"),
        },
        "dependence_audit": {
            "independent_cluster_count": dependence_audit.get("independent_cluster_count"),
            "collapsed_report_count": dependence_audit.get("collapsed_report_count"),
            "dependence_gap_seconds": dependence_audit.get("dependence_gap_seconds"),
        },
        "trial_design": protocol["trial_design"],
        "evaluation": protocol["evaluation"],
        "claims": {
            **dict(protocol["claims"]),
            "state_screen_passed_before_strategy_pnl_test": True,
            "single_feature_conditioning_only": True,
            "state_hypothesis_frozen": True,
            "dependence_clusters_bound_into_freeze": True,
        },
    }
    frozen["manifest_sha256"] = _canonical_sha256(frozen)
    return frozen


def verify_strategy_conditioning_freeze_v1_1(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or payload.get("experiment") != "strategy_conditioning_v1_1_freeze":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected

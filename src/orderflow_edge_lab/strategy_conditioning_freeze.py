from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class StrategyConditioningFreezeError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyConditioningFreezeError(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise StrategyConditioningFreezeError(f"JSON must be an object: {source}")
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
        raise StrategyConditioningFreezeError("state association must resolve to exactly one v1.1 row")
    row = matches[0]
    if row.get("v1_1_eligible_state_association") is not True:
        raise StrategyConditioningFreezeError("state association has not passed the frozen v1.1 screen")
    return row


def _assert_redundancy_representative(screen: dict[str, Any], feature: str) -> None:
    redundancy = screen.get("feature_redundancy")
    if not isinstance(redundancy, dict):
        raise StrategyConditioningFreezeError("state screen lacks redundancy metadata")
    clusters = redundancy.get("clusters", [])
    representatives = redundancy.get("representatives", {})
    if not isinstance(clusters, list) or not isinstance(representatives, dict):
        raise StrategyConditioningFreezeError("invalid redundancy metadata")
    for index, cluster in enumerate(clusters, start=1):
        if not isinstance(cluster, list) or feature not in cluster:
            continue
        representative = representatives.get(f"cluster_{index}")
        if representative != feature:
            raise StrategyConditioningFreezeError(
                f"{feature} is redundant with another feature; primary conditioning must use PnL-independent representative {representative}"
            )


def build_strategy_conditioning_freeze(
    state_screen_path: str | Path,
    protocol_path: str | Path,
    *,
    research_family: str,
    feature: str,
    target: str,
) -> dict[str, Any]:
    protocol = _load_object(protocol_path)
    if protocol.get("protocol_name") != "strategy-conditioning-v1":
        raise StrategyConditioningFreezeError("not a strategy-conditioning-v1 protocol")
    screen = _load_object(state_screen_path)
    if screen.get("experiment") != "regime_research_v1_1_market_state_screen":
        raise StrategyConditioningFreezeError("conditioning requires a regime-research-v1.1 state screen")
    if screen.get("protocol_name") != protocol.get("upstream_state_protocol"):
        raise StrategyConditioningFreezeError("state-screen protocol mismatch")

    eligibility = protocol.get("eligibility")
    if not isinstance(eligibility, dict):
        raise StrategyConditioningFreezeError("conditioning protocol lacks eligibility rules")
    if screen.get("status") != eligibility.get("required_state_screen_status"):
        raise StrategyConditioningFreezeError("state screen is not ready for conditioning research")
    readiness = screen.get("v1_1_readiness")
    if not isinstance(readiness, dict) or readiness.get("enough_forward_batches") is not True:
        raise StrategyConditioningFreezeError("minimum forward dependence clusters have not matured")
    claims = screen.get("claims")
    if not isinstance(claims, dict) or claims.get("strategy_pnl_used") is not False:
        raise StrategyConditioningFreezeError("state screen must be PnL-independent")

    association = _selected_association(
        screen,
        research_family=research_family,
        feature=feature,
        target=target,
    )
    if int(association.get("independent_batches") or 0) < int(eligibility["minimum_independent_batches"]):
        raise StrategyConditioningFreezeError("insufficient independent state batches")
    if float(association.get("dominant_sign_fraction") or 0.0) < float(eligibility["minimum_dominant_sign_fraction"]):
        raise StrategyConditioningFreezeError("state association sign stability is below the frozen floor")
    if abs(float(association.get("median_spearman") or 0.0)) < float(eligibility["minimum_median_abs_spearman"]):
        raise StrategyConditioningFreezeError("state association effect magnitude is below the frozen floor")
    if eligibility.get("require_pnl_independent_redundancy_representative") is True:
        _assert_redundancy_representative(screen, feature)

    state_screen_sha256 = hashlib.sha256(Path(state_screen_path).read_bytes()).hexdigest()
    protocol_sha256 = hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest()
    frozen = {
        "schema_version": 1,
        "experiment": "strategy_conditioning_v1_freeze",
        "protocol_name": protocol["protocol_name"],
        "protocol_frozen_at_utc": protocol["frozen_at_utc"],
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
            "independent_batches": association.get("independent_batches"),
            "total_observations": association.get("total_observations"),
        },
        "trial_design": protocol["trial_design"],
        "evaluation": protocol["evaluation"],
        "claims": {
            **dict(protocol["claims"]),
            "state_screen_passed_before_strategy_pnl_test": True,
            "single_feature_conditioning_only": True,
            "state_hypothesis_frozen": True,
        },
    }
    frozen["manifest_sha256"] = _canonical_sha256(frozen)
    return frozen


def verify_strategy_conditioning_freeze(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or payload.get("experiment") != "strategy_conditioning_v1_freeze":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected

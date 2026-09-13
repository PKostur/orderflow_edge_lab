from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from orderflow_edge_lab.state_threshold_freeze_v1 import verify_state_threshold_freeze_v1


class StrategyStateMappingV1Error(ValueError):
    pass


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyStateMappingV1Error(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise StrategyStateMappingV1Error(f"JSON must be an object: {source}")
    return value


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _waiting_payload(protocol: Mapping[str, Any], upstream_status: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "experiment": "strategy_state_mapping_v1",
        "protocol_name": protocol["protocol_name"],
        "status": "waiting_for_frozen_state_threshold",
        "upstream_threshold_status": upstream_status,
        "strategy_state_mapping": None,
        "claims": dict(protocol.get("claims", {})),
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def build_strategy_state_mapping_v1(
    threshold_freeze_path: str | Path,
    protocol_path: str | Path,
) -> dict[str, Any]:
    protocol = _load_object(protocol_path)
    if protocol.get("protocol_name") != "strategy-state-mapping-v1":
        raise StrategyStateMappingV1Error("invalid strategy-state-mapping-v1 protocol")

    threshold = _load_object(threshold_freeze_path)
    if threshold.get("protocol_name") != protocol.get("upstream_threshold_protocol"):
        raise StrategyStateMappingV1Error("state-threshold protocol mismatch")
    if not verify_state_threshold_freeze_v1(threshold):
        raise StrategyStateMappingV1Error("state-threshold freeze verification failed")
    if threshold.get("status") != "frozen":
        return _waiting_payload(protocol, threshold.get("status"))

    hypothesis = threshold.get("state_hypothesis")
    thresholds = threshold.get("thresholds")
    if not isinstance(hypothesis, Mapping) or not isinstance(thresholds, Mapping):
        raise StrategyStateMappingV1Error("frozen threshold artifact is incomplete")

    research_family = str(hypothesis.get("research_family") or "")
    feature = str(hypothesis.get("feature") or "")
    target = str(hypothesis.get("target") or "")
    dominant_sign = str(hypothesis.get("dominant_sign") or "")
    if not all((research_family, feature, target, dominant_sign)):
        raise StrategyStateMappingV1Error("state hypothesis identity is incomplete")

    mapping_rules = protocol.get("mapping_rules")
    if not isinstance(mapping_rules, Mapping):
        raise StrategyStateMappingV1Error("mapping protocol lacks mapping_rules")
    family_rule = mapping_rules.get(research_family)
    if not isinstance(family_rule, Mapping):
        raise StrategyStateMappingV1Error(f"no predeclared mapping rule for research family: {research_family}")

    selected_state = family_rule.get("selected_market_state_label")
    if selected_state is None:
        payload = {
            "schema_version": 1,
            "experiment": "strategy_state_mapping_v1",
            "protocol_name": protocol["protocol_name"],
            "status": "unsupported_for_v1_mapping",
            "frozen_after_commit": protocol.get("frozen_after_commit"),
            "state_hypothesis": dict(hypothesis),
            "unsupported_reason": str(family_rule.get("rationale") or "predeclared unsupported family"),
            "strategy_state_mapping": None,
            "claims": {
                **dict(protocol.get("claims", {})),
                "conditioned_pnl_may_run": False,
            },
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    selected_state = str(selected_state)
    market_state_mapping = thresholds.get("market_state_mapping")
    if not isinstance(market_state_mapping, Mapping):
        raise StrategyStateMappingV1Error("threshold artifact lacks market_state_mapping")
    raw_bucket = market_state_mapping.get(selected_state)
    if raw_bucket not in {"lower", "middle", "upper"}:
        raise StrategyStateMappingV1Error("selected state does not resolve to a valid raw feature bucket")

    lower = thresholds.get("lower")
    upper = thresholds.get("upper")
    if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
        raise StrategyStateMappingV1Error("threshold artifact lacks numeric lower/upper thresholds")

    predicate_by_bucket = {
        "lower": f"{feature} <= {float(lower)!r}",
        "middle": f"{float(lower)!r} < {feature} < {float(upper)!r}",
        "upper": f"{feature} >= {float(upper)!r}",
    }
    payload = {
        "schema_version": 1,
        "experiment": "strategy_state_mapping_v1",
        "protocol_name": protocol["protocol_name"],
        "status": "frozen",
        "frozen_after_commit": protocol.get("frozen_after_commit"),
        "protocol_sha256": hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest(),
        "state_threshold_file_sha256": hashlib.sha256(Path(threshold_freeze_path).read_bytes()).hexdigest(),
        "state_hypothesis": {
            "research_family": research_family,
            "feature": feature,
            "target": target,
            "dominant_sign": dominant_sign,
        },
        "strategy_state_mapping": {
            "selected_market_state_label": selected_state,
            "selected_raw_feature_bucket": raw_bucket,
            "feature_thresholds": {"lower": float(lower), "upper": float(upper)},
            "bucket_predicate": predicate_by_bucket[raw_bucket],
            "selection_rationale": str(family_rule.get("rationale") or ""),
            "conditioned_arm_rule": protocol.get("trial_rules", {}).get("conditioned_arm_rule"),
            "baseline_arm_rule": protocol.get("trial_rules", {}).get("baseline_arm_rule"),
        },
        "claims": {
            **dict(protocol.get("claims", {})),
            "bucket_frozen_before_conditioned_strategy_pnl": True,
            "conditioned_pnl_may_run": True,
            "bucket_selected_from_strategy_pnl": False,
        },
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def verify_strategy_state_mapping_v1(payload: Mapping[str, Any]) -> bool:
    if payload.get("experiment") != "strategy_state_mapping_v1":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected

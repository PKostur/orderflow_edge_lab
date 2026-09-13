from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from orderflow_edge_lab.strategy_conditioning_registry_binding_v1 import verify_registry_bound_conditioning_freeze_v1


class StateThresholdFreezeV1Error(ValueError):
    pass


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateThresholdFreezeV1Error(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise StateThresholdFreezeV1Error(f"JSON must be an object: {source}")
    return value


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise StateThresholdFreezeV1Error("cannot compute quantile of empty values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _representative_batch_ids(screen: Mapping[str, Any]) -> list[str]:
    audit = screen.get("dependence_audit")
    if not isinstance(audit, Mapping):
        raise StateThresholdFreezeV1Error("state screen lacks dependence audit")
    clusters = audit.get("clusters")
    if not isinstance(clusters, list):
        raise StateThresholdFreezeV1Error("state screen dependence audit lacks clusters")
    result: list[str] = []
    for row in clusters:
        if not isinstance(row, Mapping):
            continue
        batch_id = row.get("representative_batch_id")
        if isinstance(batch_id, str) and batch_id:
            result.append(batch_id)
    return result


def _report_map(report_paths: Iterable[str | Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in report_paths:
        payload = _load_object(path)
        if payload.get("experiment") != "regime_research_v1_market_state_scan":
            raise StateThresholdFreezeV1Error(f"not a regime-research-v1 market-state report: {path}")
        batch_id = str(payload.get("batch_id") or "")
        if not batch_id:
            raise StateThresholdFreezeV1Error(f"market-state report lacks batch_id: {path}")
        if batch_id in result:
            raise StateThresholdFreezeV1Error(f"duplicate market-state batch_id: {batch_id}")
        result[batch_id] = payload
    return result


def build_state_threshold_freeze_v1(
    state_screen_path: str | Path,
    registry_binding_path: str | Path,
    protocol_path: str | Path,
    report_paths: Iterable[str | Path],
) -> dict[str, Any]:
    protocol = _load_object(protocol_path)
    if protocol.get("protocol_name") != "state-threshold-freeze-v1":
        raise StateThresholdFreezeV1Error("invalid state-threshold-freeze-v1 protocol")
    screen = _load_object(state_screen_path)
    if screen.get("experiment") != "regime_research_v1_2_market_state_screen":
        raise StateThresholdFreezeV1Error("threshold freeze requires regime-research-v1.2 state screen")
    if screen.get("protocol_name") != protocol.get("upstream_state_protocol"):
        raise StateThresholdFreezeV1Error("state protocol mismatch")

    binding = _load_object(registry_binding_path)
    if binding.get("protocol_name") != protocol.get("upstream_binding_protocol"):
        raise StateThresholdFreezeV1Error("registry-binding protocol mismatch")
    if not verify_registry_bound_conditioning_freeze_v1(binding):
        raise StateThresholdFreezeV1Error("registry-bound conditioning manifest verification failed")
    if binding.get("status") != "frozen":
        payload = {
            "schema_version": 1,
            "experiment": "state_threshold_freeze_v1",
            "protocol_name": protocol["protocol_name"],
            "status": "waiting_for_frozen_conditioning_candidate",
            "upstream_binding_status": binding.get("status"),
            "thresholds": None,
            "claims": dict(protocol.get("claims", {})),
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    conditioning_freeze = binding.get("conditioning_freeze")
    if not isinstance(conditioning_freeze, Mapping):
        raise StateThresholdFreezeV1Error("frozen binding lacks conditioning freeze")
    if conditioning_freeze.get("protocol_name") != protocol.get("downstream_conditioning_protocol"):
        raise StateThresholdFreezeV1Error("downstream conditioning protocol mismatch")
    hypothesis = conditioning_freeze.get("state_hypothesis")
    if not isinstance(hypothesis, Mapping):
        raise StateThresholdFreezeV1Error("conditioning freeze lacks state hypothesis")
    feature = str(hypothesis.get("feature") or "")
    target = str(hypothesis.get("target") or "")
    research_family = str(hypothesis.get("research_family") or "")
    dominant_sign = str(hypothesis.get("dominant_sign") or "")
    if not feature or not target or not research_family:
        raise StateThresholdFreezeV1Error("state hypothesis identity is incomplete")
    if dominant_sign not in {"positive", "negative"}:
        raise StateThresholdFreezeV1Error("state hypothesis dominant sign must be positive or negative")

    rules = protocol.get("threshold_rules")
    if not isinstance(rules, Mapping):
        raise StateThresholdFreezeV1Error("threshold protocol lacks rules")
    lower_q = float(rules["lower_quantile"])
    upper_q = float(rules["upper_quantile"])
    if not 0.0 < lower_q < upper_q < 1.0:
        raise StateThresholdFreezeV1Error("threshold quantiles must satisfy 0 < lower < upper < 1")
    minimum_clusters = int(rules["minimum_independent_dependence_clusters"])
    minimum_observations = int(rules["minimum_valid_observations_per_cluster"])

    representatives = _representative_batch_ids(screen)
    reports = _report_map(report_paths)
    cluster_rows: list[dict[str, Any]] = []
    for batch_id in representatives:
        report = reports.get(batch_id)
        if report is None:
            raise StateThresholdFreezeV1Error(f"missing representative market-state report: {batch_id}")
        values: list[float] = []
        for row in report.get("observations", []):
            if not isinstance(row, Mapping):
                continue
            features = row.get("features")
            targets = row.get("targets")
            if not isinstance(features, Mapping) or not isinstance(targets, Mapping):
                continue
            feature_value = _finite(features.get(feature))
            target_value = _finite(targets.get(target))
            if feature_value is not None and target_value is not None:
                values.append(feature_value)
        if len(values) < minimum_observations:
            continue
        cluster_rows.append(
            {
                "representative_batch_id": batch_id,
                "valid_observations": len(values),
                "lower_quantile_value": _quantile(values, lower_q),
                "upper_quantile_value": _quantile(values, upper_q),
            }
        )

    if len(cluster_rows) < minimum_clusters:
        payload = {
            "schema_version": 1,
            "experiment": "state_threshold_freeze_v1",
            "protocol_name": protocol["protocol_name"],
            "status": "waiting_for_threshold_dependence_clusters",
            "state_hypothesis": dict(hypothesis),
            "eligible_threshold_cluster_count": len(cluster_rows),
            "minimum_required_clusters": minimum_clusters,
            "thresholds": None,
            "claims": dict(protocol.get("claims", {})),
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    lower_threshold = median([float(row["lower_quantile_value"]) for row in cluster_rows])
    upper_threshold = median([float(row["upper_quantile_value"]) for row in cluster_rows])
    if not math.isfinite(lower_threshold) or not math.isfinite(upper_threshold) or lower_threshold >= upper_threshold:
        payload = {
            "schema_version": 1,
            "experiment": "state_threshold_freeze_v1",
            "protocol_name": protocol["protocol_name"],
            "status": "degenerate_feature_distribution",
            "state_hypothesis": dict(hypothesis),
            "threshold_cluster_summary": cluster_rows,
            "thresholds": None,
            "claims": dict(protocol.get("claims", {})),
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    sign_mapping = rules.get("association_sign_mapping", {}).get(dominant_sign)
    if not isinstance(sign_mapping, Mapping):
        raise StateThresholdFreezeV1Error("threshold protocol lacks association-sign mapping")
    payload = {
        "schema_version": 1,
        "experiment": "state_threshold_freeze_v1",
        "protocol_name": protocol["protocol_name"],
        "status": "frozen",
        "frozen_after_commit": protocol.get("frozen_after_commit"),
        "protocol_sha256": hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest(),
        "state_screen_file_sha256": hashlib.sha256(Path(state_screen_path).read_bytes()).hexdigest(),
        "registry_binding_file_sha256": hashlib.sha256(Path(registry_binding_path).read_bytes()).hexdigest(),
        "state_hypothesis": {
            "research_family": research_family,
            "feature": feature,
            "target": target,
            "dominant_sign": dominant_sign,
        },
        "threshold_method": {
            "lower_quantile": lower_q,
            "upper_quantile": upper_q,
            "within_cluster_rule": rules["within_cluster_rule"],
            "across_cluster_rule": rules["across_cluster_rule"],
            "independent_dependence_clusters": len(cluster_rows),
            "minimum_valid_observations_per_cluster": minimum_observations,
        },
        "thresholds": {
            "lower": lower_threshold,
            "upper": upper_threshold,
            "raw_feature_bucket_definition": {
                "lower": f"{feature} <= lower",
                "middle": f"lower < {feature} < upper",
                "upper": f"{feature} >= upper",
            },
            "market_state_mapping": dict(sign_mapping),
        },
        "threshold_cluster_summary": cluster_rows,
        "claims": {
            **dict(protocol.get("claims", {})),
            "thresholds_frozen_before_conditioned_strategy_pnl": True,
            "dependence_cluster_weighting_equalized": True,
            "strategy_favorable_bucket_selected": False,
        },
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def verify_state_threshold_freeze_v1(payload: Mapping[str, Any]) -> bool:
    if payload.get("experiment") != "state_threshold_freeze_v1":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected

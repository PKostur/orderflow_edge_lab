from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


class MarketStateAggregateError(ValueError):
    pass


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        value = (cursor + end - 1) / 2.0 + 1.0
        for position in range(cursor, end):
            ranks[order[position]] = value
        cursor = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    centered_left = [value - mean_left for value in left]
    centered_right = [value - mean_right for value in right]
    var_left = sum(value * value for value in centered_left)
    var_right = sum(value * value for value in centered_right)
    if var_left <= 0 or var_right <= 0:
        return None
    covariance = sum(a * b for a, b in zip(centered_left, centered_right))
    value = covariance / math.sqrt(var_left * var_right)
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_rank(left), _rank(right))


def _load_report(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("experiment") != "regime_research_v1_market_state_scan":
        raise MarketStateAggregateError(f"not a regime-research-v1 market-state scan: {path}")
    if not payload.get("batch_id"):
        raise MarketStateAggregateError(f"market-state scan has no batch_id: {path}")
    return payload


def _sign_consistency(values: Sequence[float]) -> dict[str, float | str | None]:
    if not values:
        return {"dominant_sign": None, "dominant_sign_fraction": None}
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    if positive == negative:
        return {"dominant_sign": "mixed", "dominant_sign_fraction": max(positive, negative) / len(values)}
    sign = "positive" if positive > negative else "negative"
    return {"dominant_sign": sign, "dominant_sign_fraction": max(positive, negative) / len(values)}


def _feature_coverage(reports: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    batches: dict[str, set[str]] = defaultdict(set)
    for report in reports:
        batch_id = str(report["batch_id"])
        for row in report.get("observations", []):
            for feature, value in row.get("features", {}).items():
                if _finite(value) is not None:
                    batches[str(feature)].add(batch_id)
    return {feature: len(batch_ids) for feature, batch_ids in batches.items()}


def _stable_redundancy(
    reports: Sequence[Mapping[str, Any]],
    *,
    minimum_batches: int,
    minimum_fraction: float,
    abs_spearman_threshold: float,
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for report in reports:
        seen: set[tuple[str, str]] = set()
        for pair in report.get("feature_redundancy", {}).get("pairs", []):
            left = str(pair.get("left_feature"))
            right = str(pair.get("right_feature"))
            key = tuple(sorted((left, right)))
            if key in seen:
                continue
            seen.add(key)
            spearman = _finite(pair.get("spearman"))
            if spearman is not None:
                grouped[key].append(spearman)

    rows: list[dict[str, Any]] = []
    adjacency: dict[str, set[str]] = defaultdict(set)
    for (left, right), values in sorted(grouped.items()):
        fraction = sum(abs(value) >= abs_spearman_threshold for value in values) / len(values)
        stable = len(values) >= minimum_batches and fraction >= minimum_fraction
        row = {
            "left_feature": left,
            "right_feature": right,
            "independent_batches": len(values),
            "median_spearman": median(values),
            "median_abs_spearman": median([abs(value) for value in values]),
            "fraction_above_redundancy_threshold": fraction,
            "stable_redundancy": stable,
        }
        rows.append(row)
        if stable:
            adjacency[left].add(right)
            adjacency[right].add(left)

    clusters: list[list[str]] = []
    seen_features: set[str] = set()
    for feature in sorted(adjacency):
        if feature in seen_features or not adjacency[feature]:
            continue
        stack = [feature]
        cluster: list[str] = []
        while stack:
            current = stack.pop()
            if current in seen_features:
                continue
            seen_features.add(current)
            cluster.append(current)
            stack.extend(sorted(adjacency[current] - seen_features))
        if len(cluster) > 1:
            clusters.append(sorted(cluster))
    return rows, clusters


def _partial_spearman(rows: Sequence[Mapping[str, Any]], feature: str, target: str, control: str, minimum: int) -> float | None:
    x: list[float] = []
    y: list[float] = []
    z: list[float] = []
    for row in rows:
        features = row.get("features", {})
        targets = row.get("targets", {})
        xv = _finite(features.get(feature))
        yv = _finite(targets.get(target))
        zv = _finite(features.get(control))
        if xv is None or yv is None or zv is None:
            continue
        x.append(xv)
        y.append(yv)
        z.append(zv)
    if len(x) < minimum:
        return None
    rx = _rank(x)
    ry = _rank(y)
    rz = _rank(z)
    rxy = _pearson(rx, ry)
    rxz = _pearson(rx, rz)
    ryz = _pearson(ry, rz)
    if rxy is None or rxz is None or ryz is None:
        return None
    denominator = math.sqrt(max(0.0, (1.0 - rxz * rxz) * (1.0 - ryz * ryz)))
    if denominator <= 1e-12:
        return None
    value = (rxy - rxz * ryz) / denominator
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def aggregate_market_state_reports(
    report_paths: Iterable[str | Path],
    *,
    minimum_independent_batches: int = 3,
    minimum_positive_batch_fraction: float = 2.0 / 3.0,
    minimum_association_observations: int = 20,
    redundancy_abs_spearman_threshold: float = 0.80,
) -> dict[str, Any]:
    if minimum_independent_batches < 2:
        raise MarketStateAggregateError("minimum_independent_batches must be at least 2")
    if not 0.5 < minimum_positive_batch_fraction <= 1.0:
        raise MarketStateAggregateError("minimum_positive_batch_fraction must be in (0.5, 1]")
    if minimum_association_observations < 2:
        raise MarketStateAggregateError("minimum_association_observations must be at least 2")
    if not 0 < redundancy_abs_spearman_threshold <= 1:
        raise MarketStateAggregateError("redundancy_abs_spearman_threshold must be in (0, 1]")

    reports = [_load_report(path) for path in report_paths]
    if not reports:
        raise MarketStateAggregateError("no market-state reports supplied")
    batch_ids = [str(report["batch_id"]) for report in reports]
    if len(set(batch_ids)) != len(batch_ids):
        raise MarketStateAggregateError("batch_id values must be unique dependence clusters")

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        batch_id = str(report["batch_id"])
        for association in report.get("associations", []):
            spearman = _finite(association.get("spearman"))
            observations = int(association.get("observations") or 0)
            if spearman is None or observations < minimum_association_observations:
                continue
            key = (
                str(association.get("research_family")),
                str(association.get("feature")),
                str(association.get("target")),
            )
            grouped[key].append({"batch_id": batch_id, "spearman": spearman, "observations": observations})

    association_summary: list[dict[str, Any]] = []
    for (family, feature, target), items in sorted(grouped.items()):
        values = [float(item["spearman"]) for item in items]
        consistency = _sign_consistency(values)
        stable_sign = (
            len(items) >= minimum_independent_batches
            and consistency["dominant_sign"] in {"positive", "negative"}
            and float(consistency["dominant_sign_fraction"] or 0.0) >= minimum_positive_batch_fraction
        )
        association_summary.append(
            {
                "research_family": family,
                "feature": feature,
                "target": target,
                "independent_batches": len(items),
                "total_observations": sum(int(item["observations"]) for item in items),
                "median_spearman": median(values),
                **consistency,
                "stable_sign_across_batches": stable_sign,
                "batch_results": items,
            }
        )

    redundancy_pairs, redundancy_clusters = _stable_redundancy(
        reports,
        minimum_batches=minimum_independent_batches,
        minimum_fraction=minimum_positive_batch_fraction,
        abs_spearman_threshold=redundancy_abs_spearman_threshold,
    )
    coverage = _feature_coverage(reports)
    representatives: dict[str, str] = {}
    representative_for_feature: dict[str, str] = {}
    for index, cluster in enumerate(redundancy_clusters, start=1):
        representative = sorted(cluster, key=lambda feature: (-coverage.get(feature, 0), feature))[0]
        cluster_id = f"cluster_{index}"
        representatives[cluster_id] = representative
        for feature in cluster:
            representative_for_feature[feature] = representative

    incremental: list[dict[str, Any]] = []
    by_key = {(row["research_family"], row["feature"], row["target"]): row for row in association_summary}
    for (family, feature, target), summary in sorted(by_key.items()):
        control = representative_for_feature.get(feature)
        if control is None or control == feature:
            continue
        batch_values: list[dict[str, Any]] = []
        for report in reports:
            value = _partial_spearman(
                report.get("observations", []),
                feature,
                target,
                control,
                minimum_association_observations,
            )
            if value is not None:
                batch_values.append({"batch_id": str(report["batch_id"]), "partial_spearman": value})
        values = [float(item["partial_spearman"]) for item in batch_values]
        consistency = _sign_consistency(values)
        stable = (
            len(values) >= minimum_independent_batches
            and consistency["dominant_sign"] in {"positive", "negative"}
            and float(consistency["dominant_sign_fraction"] or 0.0) >= minimum_positive_batch_fraction
        )
        incremental.append(
            {
                "research_family": family,
                "feature": feature,
                "target": target,
                "control_feature": control,
                "independent_batches": len(values),
                "median_partial_spearman": median(values) if values else None,
                **consistency,
                "stable_incremental_sign_across_batches": stable,
                "batch_results": batch_values,
            }
        )

    return {
        "schema_version": 1,
        "experiment": "regime_research_v1_market_state_aggregate",
        "independent_batch_count": len(reports),
        "batch_ids": batch_ids,
        "dependence_cluster": "capture batch",
        "association_summary": association_summary,
        "feature_redundancy": {
            "threshold_abs_spearman": redundancy_abs_spearman_threshold,
            "minimum_batch_fraction": minimum_positive_batch_fraction,
            "pairs": redundancy_pairs,
            "clusters": redundancy_clusters,
            "representatives": representatives,
            "representative_rule": "highest independent-batch feature availability; lexical tie-break, never strategy PnL",
        },
        "incremental_information": incremental,
        "readiness": {
            "minimum_independent_batches": minimum_independent_batches,
            "minimum_positive_batch_fraction": minimum_positive_batch_fraction,
            "state_evidence_only": True,
            "strategy_conditioning_not_evaluated_here": True,
        },
        "claims": {
            "market_state_first": True,
            "strategy_pnl_used": False,
            "redundancy_control_applied": True,
            "incremental_information_checked": True,
            "transfer_is_not_untouched_oos": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

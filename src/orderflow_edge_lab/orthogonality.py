"""Indicator orthogonality, incremental information and stability.

The repository's contract says: prefer one stable representative from a highly
redundant indicator cluster, and combine indicators only when there is
incremental predictive information or a pre-specified interaction rationale.
Until now both sentences were prose. This module makes them executable.

Three questions, three answers, all descriptive:

* **Is the new indicator already in the set?** Rank correlation matrix plus
  redundancy clusters at a threshold the *caller* declares.
* **Does it add information the frozen regime variables do not already carry?**
  ``Delta R^2`` on rank-transformed data between the baseline model and the
  baseline-plus-feature model, with a cluster bootstrap interval. Rank
  transforms are used because regime features are ordinal and heavy-tailed, and
  the cluster bootstrap is used because rows inside one capture batch or one bar
  are not independent.
* **Is the finding stable when a group is removed?** Leave-one-out stability over
  symbols, batches or clusters -- applicable to a label metric (a state finding)
  as well as to PnL.

Nothing here selects an indicator, ranks candidates by PnL, or computes a
verdict.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

DEFAULT_CONFIDENCE = 0.95
DEFAULT_RESAMPLES = 4000
DEFAULT_SEED = 29


class OrthogonalityError(ValueError):
    """Raised when orthogonality inputs cannot be read or are malformed."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_rows(path: Path | str) -> list[dict[str, Any]]:
    """Read observation rows from JSON-lines or a JSON array of objects."""

    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise OrthogonalityError(f"cannot read rows: {target}") from exc
    rows: list[dict[str, Any]] = []
    if text.lstrip().startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OrthogonalityError(f"rows are not valid JSON: {target}") from exc
        if not isinstance(payload, list):
            raise OrthogonalityError("JSON rows must be an array")
        rows = [dict(row) for row in payload if isinstance(row, Mapping)]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OrthogonalityError(f"row is not valid JSON: {exc}") from exc
            if isinstance(payload, Mapping):
                rows.append(dict(payload))
    if not rows:
        raise OrthogonalityError(f"no rows in {target}")
    return rows


def _numeric(rows: Sequence[Mapping[str, Any]], key: str) -> np.ndarray:
    values = []
    for index, row in enumerate(rows, start=1):
        value = row.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise OrthogonalityError(f"row {index} has no numeric {key!r}")
        number = float(value)
        if not math.isfinite(number):
            raise OrthogonalityError(f"row {index} has a non-finite {key!r}")
        values.append(number)
    return np.asarray(values, dtype=float)


def ranks(values: Sequence[float]) -> np.ndarray:
    """Average ranks, so ties do not depend on input order."""

    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="mergesort")
    sorted_values = arr[order]
    out = np.empty(arr.size, dtype=float)
    index = 0
    while index < arr.size:
        end = index
        while end + 1 < arr.size and sorted_values[end + 1] == sorted_values[index]:
            end += 1
        average = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            out[order[position]] = average
        index = end + 1
    return out


def pearson(left: Sequence[float], right: Sequence[float]) -> float:
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if a.size != b.size:
        raise OrthogonalityError("pearson inputs must have equal length")
    if a.size < 3:
        return float("nan")
    a_centered = a - a.mean()
    b_centered = b - b.mean()
    denominator = math.sqrt(float(a_centered @ a_centered) * float(b_centered @ b_centered))
    if denominator == 0.0:
        return float("nan")
    return float(a_centered @ b_centered) / denominator


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    """Rank correlation with tie correction by average ranks."""

    return pearson(ranks(left), ranks(right))


def spearman_matrix(columns: Mapping[str, Sequence[float]]) -> dict[str, dict[str, float | None]]:
    """Full rank-correlation matrix over the supplied columns."""

    names = list(columns)
    matrix: dict[str, dict[str, float | None]] = {}
    for name in names:
        row: dict[str, float | None] = {}
        for other in names:
            value = spearman(columns[name], columns[other])
            row[other] = None if not math.isfinite(value) else value
        matrix[name] = row
    return matrix


def redundancy_clusters(
    columns: Mapping[str, Sequence[float]],
    *,
    threshold: float,
) -> dict[str, Any]:
    """Group columns whose absolute rank correlation reaches the caller's threshold.

    Single-linkage clustering: two indicators that are redundant with a shared
    representative belong to the same cluster. The threshold is required; this
    module declares no default because "redundant" is a research decision, not a
    library constant.
    """

    if not 0.0 < float(threshold) <= 1.0:
        raise OrthogonalityError("threshold must be in (0, 1] and supplied by the caller")
    names = list(columns)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    pairs: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        for other in names[i + 1 :]:
            value = spearman(columns[name], columns[other])
            if not math.isfinite(value):
                continue
            pairs.append({"left": name, "right": other, "rank_correlation": value})
            if abs(value) >= float(threshold):
                union(name, other)

    grouped: dict[str, list[str]] = {}
    for name in names:
        grouped.setdefault(find(name), []).append(name)
    clusters = sorted((sorted(members) for members in grouped.values()), key=lambda members: (-len(members), members))

    return {
        "threshold": float(threshold),
        "threshold_supplied_by_caller": True,
        "clusters": clusters,
        "redundant_cluster_count": sum(1 for members in clusters if len(members) > 1),
        "pairs": pairs,
        "note": (
            "Single-linkage grouping on |rank correlation|. One stable representative per cluster is the "
            "contract; which member to keep is a judgement for the reviewer, not for this tool."
        ),
    }


def _rank_design(rows: Sequence[Mapping[str, Any]], names: Sequence[str]) -> np.ndarray:
    columns = [ranks(_numeric(rows, name)) for name in names]
    matrix = np.column_stack(columns) if columns else np.zeros((len(rows), 0))
    return np.column_stack([np.ones(len(rows)), matrix])


def _adjusted_rank_r2(target: np.ndarray, design: np.ndarray) -> float:
    """Parameter-penalised rank R^2.

    Ordinary in-sample R^2 is *always* non-decreasing when a column is added, so
    a raw ``Delta R^2`` would report positive incremental information for pure
    noise. The adjusted form removes that bias, which is what makes the interval
    around it meaningful.
    """

    if design.shape[1] == 0 or target.size == 0:
        return float("nan")
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ coefficients
    total = float(((target - target.mean()) ** 2).sum())
    if total == 0.0:
        return float("nan")
    r2 = 1.0 - float(residual @ residual) / total
    n = int(target.size)
    predictors = int(design.shape[1]) - 1  # the first column is the intercept
    if n - predictors - 1 <= 0:
        return float("nan")
    return 1.0 - (1.0 - r2) * (n - 1) / (n - predictors - 1)


def delta_r2_rank(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    baseline: Sequence[str],
    feature: str,
) -> float:
    """Adjusted incremental rank R^2 of feature over an existing baseline set."""

    target_rank = ranks(_numeric(rows, target))
    base_design = _rank_design(rows, list(baseline))
    full_design = _rank_design(rows, [*baseline, feature])
    base_r2 = _adjusted_rank_r2(target_rank, base_design)
    full_r2 = _adjusted_rank_r2(target_rank, full_design)
    if not math.isfinite(base_r2) or not math.isfinite(full_r2):
        return float("nan")
    return full_r2 - base_r2


def partial_rank_ic(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    baseline: Sequence[str],
    feature: str,
) -> float:
    """Rank correlation of feature and target after removing the baseline ranks."""

    target_rank = ranks(_numeric(rows, target))
    feature_rank = ranks(_numeric(rows, feature))
    base_design = _rank_design(rows, list(baseline))
    if base_design.shape[1] == 0:
        return pearson(feature_rank, target_rank)
    coefficients, *_ = np.linalg.lstsq(base_design, feature_rank, rcond=None)
    feature_residual = feature_rank - base_design @ coefficients
    coefficients, *_ = np.linalg.lstsq(base_design, target_rank, rcond=None)
    target_residual = target_rank - base_design @ coefficients
    return pearson(feature_residual, target_residual)


def _cluster_keys(rows: Sequence[Mapping[str, Any]], cluster: str | None) -> list[str]:
    if cluster is None:
        return [str(index) for index in range(len(rows))]
    keys = []
    for index, row in enumerate(rows, start=1):
        value = row.get(cluster)
        if value is None:
            raise OrthogonalityError(f"row {index} has no cluster value for {cluster!r}")
        keys.append(str(value))
    return keys


def _bootstrap_clusters(
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    statistic,
    *,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, Any]:
    buckets: dict[str, list[int]] = {}
    for position, key in enumerate(keys):
        buckets.setdefault(key, []).append(position)
    cluster_ids = sorted(buckets)
    if len(cluster_ids) < 2:
        return {"status": "insufficient_clusters", "cluster_count": len(cluster_ids)}
    if int(resamples) < 100:
        raise OrthogonalityError("resamples must be at least 100")

    rng = np.random.default_rng(int(seed))
    draws = rng.integers(0, len(cluster_ids), size=(int(resamples), len(cluster_ids)))
    values = np.empty(int(resamples), dtype=float)
    for draw_index, draw in enumerate(draws):
        positions: list[int] = []
        for cluster_index in draw:
            positions.extend(buckets[cluster_ids[int(cluster_index)]])
        subset = [rows[position] for position in positions]
        values[draw_index] = statistic(subset)

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"status": "statistic_undefined", "cluster_count": len(cluster_ids)}
    alpha = 1.0 - float(confidence)
    lower = float(np.quantile(finite, alpha / 2.0))
    upper = float(np.quantile(finite, 1.0 - alpha / 2.0))
    return {
        "status": "ok",
        "cluster_count": len(cluster_ids),
        "resamples": int(resamples),
        "used_resamples": int(finite.size),
        "ci_lower": lower,
        "ci_upper": upper,
        "interval_excludes_zero": bool(lower > 0.0 or upper < 0.0),
    }


def incremental_information(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature: str,
    baseline: Sequence[str],
    target: str,
    cluster: str | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Does the feature add rank information beyond the existing baseline set?"""

    if not baseline:
        raise OrthogonalityError("baseline must list at least one existing variable")
    observed_delta = delta_r2_rank(rows, target=target, baseline=list(baseline), feature=feature)
    observed_partial = partial_rank_ic(rows, target=target, baseline=list(baseline), feature=feature)
    keys = _cluster_keys(rows, cluster)
    interval = _bootstrap_clusters(
        rows,
        keys,
        lambda subset: delta_r2_rank(subset, target=target, baseline=list(baseline), feature=feature),
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    return {
        "feature": feature,
        "baseline": list(baseline),
        "target": target,
        "dependence_cluster": cluster,
        "metric": "adjusted_delta_r2_on_ranks",
        "delta_r2_rank": None if not math.isfinite(observed_delta) else observed_delta,
        "partial_rank_ic": None if not math.isfinite(observed_partial) else observed_partial,
        "delta_r2_rank_interval": interval,
        "note": (
            "Descriptive only. Delta R^2 is the adjusted (parameter-penalised) rank form, so adding a "
            "noise feature does not produce a positive value. A positive value with an interval excluding "
            "zero is evidence that the feature is not already carried by the baseline; it is not a "
            "promotion or an interaction claim."
        ),
    }


def leave_one_out_stability(
    rows: Sequence[Mapping[str, Any]],
    *,
    value_key: str,
    group_key: str,
    cluster_key: str | None = None,
) -> dict[str, Any]:
    """Leave-one-group-out and leave-one-cluster-out stability of a metric.

    ``value_key`` may be a label metric (for a state finding) or a PnL series (for
    a strategy finding); this function only aggregates what it is given.
    """

    values = _numeric(rows, value_key)
    groups = [str(row.get(group_key)) for row in rows]
    if any(value == "None" for value in groups):
        raise OrthogonalityError(f"every row needs a {group_key!r} value")

    def loo(keys: Sequence[str]) -> dict[str, Any]:
        unique = sorted(set(keys))
        means: dict[str, float] = {}
        for key in unique:
            subset = values[[index for index, item in enumerate(keys) if item != key]]
            means[key] = float(subset.mean()) if subset.size else float("nan")
        finite = [value for value in means.values() if math.isfinite(value)]
        if not finite:
            return {"count": len(unique), "means": means, "status": "undefined"}
        return {
            "status": "ok",
            "count": len(unique),
            "means": means,
            "minimum": min(finite),
            "median": float(np.median(finite)),
            "maximum": max(finite),
            "positive_count": sum(1 for value in finite if value > 0.0),
            "sign_flips": min(finite) < 0.0 < max(finite),
            "note": "sign_flips is true when removing different units flips the sign of the metric.",
        }

    result: dict[str, Any] = {
        "value_key": value_key,
        "group_key": group_key,
        "overall_mean": float(values.mean()),
        "observations": int(values.size),
        "leave_one_group_out": loo(groups),
    }
    if cluster_key is not None:
        clusters = [str(row.get(cluster_key)) for row in rows]
        result["leave_one_cluster_out"] = loo(clusters)
        result["cluster_key"] = cluster_key
    return result


def build_orthogonality_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature: str,
    baseline: Sequence[str],
    target: str,
    redundancy_threshold: float,
    cluster: str | None = None,
    group_key: str | None = None,
    stability_value_key: str | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Build the combined orthogonality / incremental-information report."""

    feature_columns = [feature, *baseline]
    columns = {name: _numeric(rows, name) for name in [*feature_columns, target]}
    matrix = spearman_matrix(columns)
    clusters = redundancy_clusters({name: columns[name] for name in feature_columns}, threshold=redundancy_threshold)
    incremental = incremental_information(
        rows,
        feature=feature,
        baseline=list(baseline),
        target=target,
        cluster=cluster,
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    stability = None
    if group_key is not None:
        stability = leave_one_out_stability(
            rows,
            value_key=stability_value_key or target,
            group_key=group_key,
            cluster_key=cluster,
        )

    report = {
        "schema_version": 1,
        "analysis": "indicator_orthogonality_and_incremental_information",
        "feature": feature,
        "baseline": list(baseline),
        "target": target,
        "observations": len(rows),
        "dependence_cluster": cluster,
        "correlation_matrix": matrix,
        "redundancy": clusters,
        "incremental_information": incremental,
        "stability": stability,
        "verdict": None,
        "verdict_requires_human_review": True,
        "claims": {
            "selects_or_ranks_indicators": False,
            "invents_thresholds": False,
            "uses_strategy_pnl_to_screen_features": False,
            "computes_strategy_verdicts": False,
            "promotes_strategy": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def orthogonality_markdown(report: Mapping[str, Any]) -> str:
    """Render the orthogonality report."""

    incremental = report["incremental_information"]
    interval = incremental["delta_r2_rank_interval"]
    lines = [
        "# Indicator orthogonality and incremental information",
        "",
        f"- Feature `{report['feature']}` against baseline {report['baseline']} for target `{report['target']}`",
        f"- Observations: {report['observations']}; dependence cluster: `{report['dependence_cluster']}`",
        f"- Redundancy threshold (caller-declared): {report['redundancy']['threshold']}; "
        f"redundant clusters: {report['redundancy']['redundant_cluster_count']}",
        "",
        "## Redundancy clusters",
        "",
    ]
    for members in report["redundancy"]["clusters"]:
        lines.append(f"- {', '.join(f'`{name}`' for name in members)}")
    lines += [
        "",
        "## Incremental information",
        "",
        f"- Metric: `{incremental['metric']}`; value `{incremental['delta_r2_rank']}`; "
        f"partial rank IC `{incremental['partial_rank_ic']}`",
    ]
    if interval.get("status") == "ok":
        lines.append(
            f"- Cluster bootstrap interval: [{interval['ci_lower']:.6f}, {interval['ci_upper']:.6f}] over "
            f"{interval['cluster_count']} clusters; excludes zero: `{interval['interval_excludes_zero']}` "
            "(descriptive fact only)"
        )
    else:
        lines.append(f"- Cluster bootstrap interval: not computed (`{interval.get('status')}`)")
    lines += ["", "## Rank correlation matrix", "", "| | " + " | ".join(report["correlation_matrix"]) + " |"]
    lines.append("|---" * (len(report["correlation_matrix"]) + 1) + "|")
    for name, row in report["correlation_matrix"].items():
        rendered = [
            "n/a" if value is None else f"{value:.4f}" for value in (row[column] for column in report["correlation_matrix"])
        ]
        lines.append(f"| `{name}` | " + " | ".join(rendered) + " |")
    if report.get("stability"):
        stability = report["stability"]
        lines += [
            "",
            "## Stability",
            "",
            f"- Overall mean of `{stability['value_key']}`: {stability['overall_mean']:.4f}",
            f"- Leave-one-`{stability['group_key']}`-out: min {stability['leave_one_group_out'].get('minimum')}, "
            f"median {stability['leave_one_group_out'].get('median')}, "
            f"max {stability['leave_one_group_out'].get('maximum')}, "
            f"sign flips: `{stability['leave_one_group_out'].get('sign_flips')}`",
        ]
        if "leave_one_cluster_out" in stability:
            lines.append(
                f"- Leave-one-cluster-out: min {stability['leave_one_cluster_out'].get('minimum')}, "
                f"max {stability['leave_one_cluster_out'].get('maximum')}, "
                f"sign flips: `{stability['leave_one_cluster_out'].get('sign_flips')}`"
            )
    lines.append("")
    return "\n".join(lines)

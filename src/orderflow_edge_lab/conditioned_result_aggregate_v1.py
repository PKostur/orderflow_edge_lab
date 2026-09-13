from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from .conditioned_experiment_v1 import verify_conditioned_experiment_v1
from .market_state_aggregate_v1_2 import (
    _cluster_intervals,
    _eligible_intervals,
    _representative,
    _utc_ns,
)


class ConditionedResultAggregateV1Error(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConditionedResultAggregateV1Error(f"cannot read JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise ConditionedResultAggregateV1Error(f"JSON must be an object: {source}")
    return payload


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _load_protocol(path: str | Path) -> dict[str, Any]:
    payload = _load(path)
    if payload.get("protocol_name") != "conditioned-result-aggregate-v1":
        raise ConditionedResultAggregateV1Error("unexpected conditioned-result aggregate protocol")
    return payload


def _load_regime_protocol(path: str | Path) -> dict[str, Any]:
    payload = _load(path)
    if payload.get("protocol_name") != "regime-research-v1.2":
        raise ConditionedResultAggregateV1Error("dependence protocol must be regime-research-v1.2")
    return payload


def _key(row: Mapping[str, Any]) -> tuple[str, int, float]:
    return (str(row["family"]), int(row["horizon_ms"]), float(row["fee_bps_round_trip"]))


def _risk_key(row: Mapping[str, Any]) -> tuple[str, str, float, float, float]:
    return (
        str(row["stream"]),
        str(row["family"]),
        float(row["rr_target"]),
        float(row["requested_risk_fraction"]),
        float(row["fee_bps_round_trip"]),
    )


def _pf(value: Any) -> float | None:
    if value == "INF":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _median(values: Iterable[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(median(finite)) if finite else None


def _sign_fraction(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    positive = sum(value > 0 for value in values) / len(values)
    nonzero = [value for value in values if value != 0]
    dominant = None
    if nonzero:
        positive_nonzero = sum(value > 0 for value in nonzero)
        negative_nonzero = len(nonzero) - positive_nonzero
        dominant = max(positive_nonzero, negative_nonzero) / len(nonzero)
    return float(positive), float(dominant) if dominant is not None else None


def _summary_map(report: Mapping[str, Any], arm: str) -> dict[tuple[str, int, float], Mapping[str, Any]]:
    block = report.get(arm)
    rows = block.get("summary") if isinstance(block, Mapping) else None
    if not isinstance(rows, list):
        return {}
    return {_key(row): row for row in rows if isinstance(row, Mapping)}


def _direction_map(report: Mapping[str, Any], arm: str) -> dict[tuple[str, int, float], float]:
    control = report.get("original_vs_reversed_control")
    if not isinstance(control, Mapping):
        return {}
    original = control.get(f"{arm}_original")
    reversed_ = control.get(f"{arm}_reversed")
    if not isinstance(original, list) or not isinstance(reversed_, list):
        return {}
    original_by_key = {_key(row): row for row in original if isinstance(row, Mapping)}
    reversed_by_key = {_key(row): row for row in reversed_ if isinstance(row, Mapping)}
    out: dict[tuple[str, int, float], float] = {}
    for cell in sorted(original_by_key.keys() & reversed_by_key.keys()):
        out[cell] = float(original_by_key[cell]["net_mean_bps"]) - float(reversed_by_key[cell]["net_mean_bps"])
    return out


def _risk_map(report: Mapping[str, Any], arm: str) -> dict[tuple[str, str, float, float, float], Mapping[str, Any]]:
    comparison = report.get("mae_mfe_stop_risk_comparison")
    block = comparison.get(arm) if isinstance(comparison, Mapping) else None
    rows = block.get("summary") if isinstance(block, Mapping) else None
    if not isinstance(rows, list):
        return {}
    return {_risk_key(row): row for row in rows if isinstance(row, Mapping)}


def _verified_conditioned_reports(paths: Iterable[str | Path]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_batch: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for path in paths:
        source = Path(path)
        payload = _load(source)
        if not verify_conditioned_experiment_v1(payload):
            raise ConditionedResultAggregateV1Error(f"conditioned report manifest verification failed: {source}")
        batch_id = str(payload.get("batch_id") or "")
        status = str(payload.get("status") or "")
        audit.append({"path": str(source), "batch_id": batch_id or None, "status": status})
        if status != "evaluated_research_only":
            continue
        if not batch_id:
            raise ConditionedResultAggregateV1Error(f"evaluated conditioned report has no batch_id: {source}")
        if batch_id in by_batch:
            raise ConditionedResultAggregateV1Error(f"duplicate evaluated conditioned batch_id: {batch_id}")
        by_batch[batch_id] = payload
    return by_batch, audit


def _assert_consistency(reports: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    rows = list(reports)
    if not rows:
        return None
    mapping_hashes = {str(row.get("strategy_state_mapping_manifest_sha256") or "") for row in rows}
    gates = {_canonical_sha256(row.get("state_gate")) for row in rows}
    economics = {_canonical_sha256(row.get("economics")) for row in rows}
    if len(mapping_hashes) != 1 or "" in mapping_hashes:
        raise ConditionedResultAggregateV1Error("evaluated reports do not share one frozen strategy-state mapping")
    if len(gates) != 1:
        raise ConditionedResultAggregateV1Error("evaluated reports do not share one frozen state gate")
    if len(economics) != 1:
        raise ConditionedResultAggregateV1Error("evaluated reports do not share identical economics")
    return {
        "strategy_state_mapping_manifest_sha256": next(iter(mapping_hashes)),
        "state_gate_sha256": next(iter(gates)),
        "economics_sha256": next(iter(economics)),
    }


def build_conditioned_result_aggregate_v1(
    conditioned_report_paths: Iterable[str | Path],
    state_report_paths: Iterable[str | Path],
    *,
    protocol_path: str | Path,
    regime_protocol_path: str | Path,
) -> dict[str, Any]:
    protocol = _load_protocol(protocol_path)
    regime = _load_regime_protocol(regime_protocol_path)
    reports_by_batch, report_audit = _verified_conditioned_reports(conditioned_report_paths)

    evidence_start_utc = str(regime["evidence_start_utc"])
    minimum_batch_id = str(regime["evidence_start_batch_id"])
    gap_seconds = int(regime["dependence_clustering"]["dependence_gap_seconds"])
    intervals = _eligible_intervals(
        state_report_paths,
        minimum_batch_id=minimum_batch_id,
        minimum_start_ns=_utc_ns(evidence_start_utc),
    )
    clusters = _cluster_intervals(intervals, gap_seconds * 1_000_000_000)

    representative_rows: list[dict[str, Any]] = []
    selected_reports: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters, start=1):
        rep = _representative(cluster)
        batch_id = str(rep["batch_id"])
        conditioned = reports_by_batch.get(batch_id)
        representative_rows.append({
            "cluster_id": f"dependence_cluster_{index}",
            "member_batch_ids": [str(row["batch_id"]) for row in cluster],
            "representative_batch_id": batch_id,
            "conditioned_report_available_and_evaluated": conditioned is not None,
        })
        if conditioned is not None:
            selected_reports.append(conditioned)

    consistency = _assert_consistency(selected_reports)
    minimum_clusters = int(protocol["aggregation"]["minimum_independent_clusters_for_review"])

    strategy_cells: list[dict[str, Any]] = []
    strategy_keys = sorted({cell for report in selected_reports for cell in (_summary_map(report, "baseline").keys() & _summary_map(report, "conditioned").keys())})
    for cell in strategy_keys:
        rows = []
        for report in selected_reports:
            baseline = _summary_map(report, "baseline").get(cell)
            conditioned = _summary_map(report, "conditioned").get(cell)
            if baseline is None or conditioned is None:
                continue
            baseline_exp = float(baseline["net_expectancy_bps"])
            conditioned_exp = float(conditioned["net_expectancy_bps"])
            rows.append({
                "batch_id": str(report["batch_id"]),
                "baseline_net_expectancy_bps": baseline_exp,
                "conditioned_net_expectancy_bps": conditioned_exp,
                "delta_expectancy_bps": conditioned_exp - baseline_exp,
                "baseline_profit_factor": _pf(baseline.get("net_profit_factor")),
                "conditioned_profit_factor": _pf(conditioned.get("net_profit_factor")),
                "baseline_observations": int(baseline["observations"]),
                "conditioned_observations": int(conditioned["observations"]),
            })
        deltas = [float(row["delta_expectancy_bps"]) for row in rows]
        positive, dominant = _sign_fraction(deltas)
        strategy_cells.append({
            "family": cell[0], "horizon_ms": cell[1], "fee_bps_round_trip": cell[2],
            "cluster_count": len(rows),
            "median_baseline_net_expectancy_bps": _median([row["baseline_net_expectancy_bps"] for row in rows]),
            "median_conditioned_net_expectancy_bps": _median([row["conditioned_net_expectancy_bps"] for row in rows]),
            "median_conditioned_minus_baseline_expectancy_bps": _median(deltas),
            "positive_delta_cluster_fraction": positive,
            "dominant_delta_sign_fraction": dominant,
            "median_baseline_profit_factor": _median([row["baseline_profit_factor"] for row in rows]),
            "median_conditioned_profit_factor": _median([row["conditioned_profit_factor"] for row in rows]),
            "clusters": rows,
        })

    direction_cells: list[dict[str, Any]] = []
    direction_keys = sorted({cell for report in selected_reports for cell in (_direction_map(report, "baseline").keys() & _direction_map(report, "conditioned").keys())})
    for cell in direction_keys:
        rows = []
        for report in selected_reports:
            baseline = _direction_map(report, "baseline").get(cell)
            conditioned = _direction_map(report, "conditioned").get(cell)
            if baseline is None or conditioned is None:
                continue
            rows.append((float(baseline), float(conditioned)))
        direction_cells.append({
            "family": cell[0], "horizon_ms": cell[1], "fee_bps_round_trip": cell[2],
            "cluster_count": len(rows),
            "median_baseline_original_minus_reversed_net_bps": _median([row[0] for row in rows]),
            "median_conditioned_original_minus_reversed_net_bps": _median([row[1] for row in rows]),
            "median_conditioned_minus_baseline_direction_discrimination_bps": _median([row[1] - row[0] for row in rows]),
        })

    risk_cells: list[dict[str, Any]] = []
    risk_keys = sorted({cell for report in selected_reports for cell in (_risk_map(report, "baseline").keys() & _risk_map(report, "conditioned").keys())})
    for cell in risk_keys:
        rows = []
        for report in selected_reports:
            baseline = _risk_map(report, "baseline").get(cell)
            conditioned = _risk_map(report, "conditioned").get(cell)
            if baseline is None or conditioned is None:
                continue
            rows.append({"baseline": baseline, "conditioned": conditioned})
        risk_cells.append({
            "stream": cell[0], "family": cell[1], "rr_target": cell[2],
            "requested_risk_fraction": cell[3], "fee_bps_round_trip": cell[4],
            "cluster_count": len(rows),
            "median_change_max_realized_drawdown_pct": _median([float(r["conditioned"]["max_realized_drawdown_pct"]) - float(r["baseline"]["max_realized_drawdown_pct"]) for r in rows]),
            "median_change_mean_mae_bps": _median([(float(r["conditioned"]["mean_mae_bps"]) - float(r["baseline"]["mean_mae_bps"])) if r["conditioned"].get("mean_mae_bps") is not None and r["baseline"].get("mean_mae_bps") is not None else None for r in rows]),
            "median_change_mean_mfe_bps": _median([(float(r["conditioned"]["mean_mfe_bps"]) - float(r["baseline"]["mean_mfe_bps"])) if r["conditioned"].get("mean_mfe_bps") is not None and r["baseline"].get("mean_mfe_bps") is not None else None for r in rows]),
            "baseline_ruined_cluster_fraction": (sum(bool(r["baseline"]["ruined_on_realized_path"]) for r in rows) / len(rows)) if rows else None,
            "conditioned_ruined_cluster_fraction": (sum(bool(r["conditioned"]["ruined_on_realized_path"]) for r in rows) / len(rows)) if rows else None,
        })

    independent_evaluated = len(selected_reports)
    payload = {
        "schema_version": 1,
        "experiment": "conditioned_result_aggregate_v1",
        "protocol_name": protocol["protocol_name"],
        "protocol_frozen_at_utc": protocol["frozen_at_utc"],
        "status": "reviewable_cluster_count_reached" if independent_evaluated >= minimum_clusters else "collecting_independent_conditioned_clusters",
        "dependence": {
            "upstream_protocol": regime["protocol_name"],
            "evidence_start_utc": evidence_start_utc,
            "dependence_gap_seconds": gap_seconds,
            "eligible_state_cluster_count": len(clusters),
            "evaluated_representative_cluster_count": independent_evaluated,
            "minimum_independent_clusters_for_review": minimum_clusters,
            "representatives": representative_rows,
            "representative_selection_uses_strategy_pnl": False,
        },
        "consistency": consistency,
        "conditioned_report_audit": report_audit,
        "strategy_cells": strategy_cells,
        "direction_control_cells": direction_cells,
        "risk_path_cells": risk_cells,
        "claims": {
            **dict(protocol["claims"]),
            "raw_overlapping_captures_counted_as_independent": False,
            "cluster_weighting": "equal",
            "best_cell_selection_performed": False,
            "automatic_candidate_promotion_performed": False,
            "cross_pair_transfer_is_untouched_oos": False,
        },
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def verify_conditioned_result_aggregate_v1(payload: Mapping[str, Any]) -> bool:
    if payload.get("experiment") != "conditioned_result_aggregate_v1":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected

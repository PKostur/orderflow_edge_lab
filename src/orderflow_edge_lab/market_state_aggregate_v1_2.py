from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from .market_state_aggregate import aggregate_market_state_reports


class MarketStateAggregateV12Error(ValueError):
    pass


def _load_protocol(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_name") != "regime-research-v1.2":
        raise MarketStateAggregateV12Error("not a regime-research-v1.2 protocol")
    return payload


def _utc_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise MarketStateAggregateV12Error("evidence_start_utc must include a timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1_000_000_000)


def _report_interval(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("experiment") != "regime_research_v1_market_state_scan":
        raise MarketStateAggregateV12Error(f"not a regime-research-v1 market-state scan: {source}")
    batch_id = str(payload.get("batch_id") or "")
    if not batch_id:
        raise MarketStateAggregateV12Error(f"market-state scan has no batch_id: {source}")
    observed: list[int] = []
    for row in payload.get("observations", []):
        value = row.get("observed_at_ns") if isinstance(row, dict) else None
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp >= 0:
            observed.append(timestamp)
    if not observed:
        raise MarketStateAggregateV12Error(f"market-state scan has no timestamped observations: {source}")
    return {
        "path": source,
        "batch_id": batch_id,
        "start_ns": min(observed),
        "end_ns": max(observed),
        "timestamped_observations": len(observed),
    }


def _eligible_intervals(
    report_paths: Iterable[str | Path],
    *,
    minimum_batch_id: str,
    minimum_start_ns: int,
) -> list[dict[str, Any]]:
    intervals = [_report_interval(path) for path in report_paths]
    batch_ids = [row["batch_id"] for row in intervals]
    if len(set(batch_ids)) != len(batch_ids):
        raise MarketStateAggregateV12Error("batch_id values must be unique before dependence clustering")
    return [
        row
        for row in intervals
        if row["batch_id"] >= minimum_batch_id and int(row["start_ns"]) >= minimum_start_ns
    ]


def _cluster_intervals(intervals: list[dict[str, Any]], gap_ns: int) -> list[list[dict[str, Any]]]:
    ordered = sorted(intervals, key=lambda row: (int(row["start_ns"]), int(row["end_ns"]), str(row["batch_id"])))
    clusters: list[list[dict[str, Any]]] = []
    cluster_end: int | None = None
    for row in ordered:
        start = int(row["start_ns"])
        end = int(row["end_ns"])
        if not clusters or cluster_end is None or start > cluster_end + gap_ns:
            clusters.append([row])
            cluster_end = end
            continue
        clusters[-1].append(row)
        cluster_end = max(cluster_end, end)
    return clusters


def _representative(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        cluster,
        key=lambda row: (
            -int(row["timestamped_observations"]),
            int(row["start_ns"]),
            str(row["batch_id"]),
        ),
    )[0]


def _audit_payload(
    clusters: list[list[dict[str, Any]]],
    *,
    gap_seconds: int,
    evidence_start_utc: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters, start=1):
        representative = _representative(cluster)
        rows.append(
            {
                "cluster_id": f"dependence_cluster_{index}",
                "start_ns": min(int(row["start_ns"]) for row in cluster),
                "end_ns": max(int(row["end_ns"]) for row in cluster),
                "member_batch_ids": [str(row["batch_id"]) for row in cluster],
                "member_count": len(cluster),
                "representative_batch_id": str(representative["batch_id"]),
                "representative_rule_inputs": {
                    "timestamped_observations": int(representative["timestamped_observations"]),
                    "start_ns": int(representative["start_ns"]),
                },
            }
        )
    return {
        "evidence_start_utc": evidence_start_utc,
        "dependence_gap_seconds": gap_seconds,
        "eligible_report_count": sum(len(cluster) for cluster in clusters),
        "independent_cluster_count": len(clusters),
        "collapsed_report_count": sum(max(0, len(cluster) - 1) for cluster in clusters),
        "clusters": rows,
        "representative_selection_uses_strategy_pnl": False,
    }


def build_v1_2_state_screen(
    report_paths: Iterable[str | Path],
    protocol_path: str | Path,
) -> dict[str, Any]:
    protocol = _load_protocol(protocol_path)
    rules = protocol["state_screen"]
    clustering = protocol["dependence_clustering"]
    minimum_batch_id = str(protocol["evidence_start_batch_id"])
    evidence_start_utc = str(protocol["evidence_start_utc"])
    minimum_start_ns = _utc_ns(evidence_start_utc)
    gap_seconds = int(clustering["dependence_gap_seconds"])
    if gap_seconds < 0:
        raise MarketStateAggregateV12Error("dependence_gap_seconds must be non-negative")

    eligible = _eligible_intervals(
        report_paths,
        minimum_batch_id=minimum_batch_id,
        minimum_start_ns=minimum_start_ns,
    )
    clusters = _cluster_intervals(eligible, gap_seconds * 1_000_000_000)
    audit = _audit_payload(clusters, gap_seconds=gap_seconds, evidence_start_utc=evidence_start_utc)

    if not clusters:
        return {
            "schema_version": 1,
            "experiment": "regime_research_v1_2_market_state_screen",
            "protocol_name": protocol["protocol_name"],
            "protocol_frozen_at_utc": protocol["frozen_at_utc"],
            "evidence_start_utc": evidence_start_utc,
            "evidence_start_batch_id": minimum_batch_id,
            "status": "waiting_for_forward_dependence_clusters",
            "independent_batch_count": 0,
            "eligible_state_association_count": 0,
            "eligible_incremental_feature_count": 0,
            "association_summary": [],
            "incremental_information": [],
            "dependence_audit": audit,
            "claims": dict(protocol["claims"]),
        }

    representatives = [_representative(cluster) for cluster in clusters]
    base = aggregate_market_state_reports(
        [row["path"] for row in representatives],
        minimum_independent_batches=int(rules["minimum_independent_batches"]),
        minimum_positive_batch_fraction=float(rules["minimum_dominant_sign_fraction"]),
        minimum_association_observations=int(rules["minimum_association_observations_per_batch"]),
        redundancy_abs_spearman_threshold=float(rules["redundancy_abs_spearman_threshold"]),
    )

    min_abs = float(rules["minimum_median_abs_spearman"])
    eligible_associations = 0
    for row in base.get("association_summary", []):
        effect = abs(float(row.get("median_spearman") or 0.0)) >= min_abs
        row["v1_2_effect_size_floor_passed"] = effect
        row["v1_2_eligible_state_association"] = bool(row.get("stable_sign_across_batches") and effect)
        eligible_associations += int(row["v1_2_eligible_state_association"])

    min_partial = float(rules["minimum_median_abs_partial_spearman"])
    eligible_incremental = 0
    for row in base.get("incremental_information", []):
        value = row.get("median_partial_spearman")
        effect = value is not None and abs(float(value)) >= min_partial
        row["v1_2_effect_size_floor_passed"] = effect
        row["v1_2_eligible_incremental_feature"] = bool(
            row.get("stable_incremental_sign_across_batches") and effect
        )
        eligible_incremental += int(row["v1_2_eligible_incremental_feature"])

    enough_batches = int(base.get("independent_batch_count") or 0) >= int(rules["minimum_independent_batches"])
    base.update(
        {
            "experiment": "regime_research_v1_2_market_state_screen",
            "protocol_name": protocol["protocol_name"],
            "protocol_frozen_at_utc": protocol["frozen_at_utc"],
            "evidence_start_utc": evidence_start_utc,
            "evidence_start_batch_id": minimum_batch_id,
            "status": "screen_ready" if enough_batches else "collecting_forward_dependence_clusters",
            "eligible_state_association_count": eligible_associations,
            "eligible_incremental_feature_count": eligible_incremental,
            "dependence_cluster": "timestamp-overlap-aware capture cluster",
            "dependence_audit": audit,
            "v1_2_readiness": {
                "minimum_independent_batches": int(rules["minimum_independent_batches"]),
                "minimum_median_abs_spearman": min_abs,
                "minimum_median_abs_partial_spearman": min_partial,
                "dependence_gap_seconds": gap_seconds,
                "enough_forward_dependence_clusters": enough_batches,
                "state_hypothesis_available_for_separate_conditioning_test": bool(
                    enough_batches and eligible_associations > 0
                ),
                "automatic_strategy_conditioning_permitted": False,
            },
            "claims": {
                **dict(protocol["claims"]),
                "market_state_first": True,
                "strategy_pnl_used": False,
                "effect_size_floor_applied": True,
                "incremental_information_checked": True,
                "dependence_clusters_counted_instead_of_raw_report_ids": True,
                "state_screen_is_not_strategy_promotion": True,
            },
        }
    )
    return base

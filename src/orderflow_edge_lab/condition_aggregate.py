from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
from typing import Any, Iterable

from orderflow_edge_lab.market_conditions import (
    CONDITION_PROTOCOL,
    MIN_POSITIVE_BATCH_FRACTION,
    MIN_SCREEN_BATCHES,
    MIN_SCREEN_OBSERVATIONS,
    _numeric_pf,
    _summarize_group,
)


class ConditionAggregateError(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConditionAggregateError(f"{path}: expected JSON object")
    if payload.get("experiment") != "pre_registered_market_condition_stratification":
        raise ConditionAggregateError(f"{path}: incompatible condition report")
    return payload


def aggregate_condition_reports(report_paths: Iterable[str | Path]) -> dict[str, Any]:
    paths = [Path(path) for path in report_paths]
    if not paths:
        raise ConditionAggregateError("at least one report is required")
    reports = [_load(path) for path in paths]
    symbol = reports[0].get("symbol")
    context_symbol = reports[0].get("context_symbol")
    horizons = reports[0].get("horizons_ms")
    fees = reports[0].get("fees_bps_round_trip")
    enriched: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    for report in reports:
        if report.get("symbol") != symbol or report.get("context_symbol") != context_symbol:
            raise ConditionAggregateError("symbol or context mismatch across reports")
        if report.get("condition_protocol") != CONDITION_PROTOCOL:
            raise ConditionAggregateError("condition protocol mismatch across reports")
        if report.get("horizons_ms") != horizons or report.get("fees_bps_round_trip") != fees:
            raise ConditionAggregateError("horizon or fee protocol mismatch across reports")
        for source in report.get("sources", []):
            if not isinstance(source, dict) or not source.get("source_sha256"):
                continue
            sources[str(source["source_sha256"])] = source
        for row in report.get("enriched_observations", []):
            if isinstance(row, dict):
                enriched.append(row)
    # Deduplicate in case the same batch report was downloaded twice.
    unique: dict[tuple[str, str, int, float, int], dict[str, Any]] = {}
    for row in enriched:
        key = (
            str(row.get("batch_id")),
            str(row.get("family")),
            int(row.get("horizon_ms")),
            float(row.get("fee_bps_round_trip")),
            int(row.get("signal_observed_at_ns")),
        )
        unique[key] = row
    enriched = list(unique.values())

    baselines: dict[tuple[str, int, float], list[dict[str, Any]]] = defaultdict(list)
    groups: dict[tuple[str, str, str, int, float], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        family = str(row["family"])
        horizon = int(row["horizon_ms"])
        fee = float(row["fee_bps_round_trip"])
        baselines[(family, horizon, fee)].append(row)
        for dimension, bucket in row.get("conditions", {}).items():
            if bucket is not None:
                groups[(str(dimension), str(bucket), family, horizon, fee)].append(row)

    baseline_summary = []
    for (family, horizon, fee), rows in sorted(baselines.items()):
        baseline_summary.append({
            "family": family,
            "horizon_ms": horizon,
            "fee_bps_round_trip": fee,
            **_summarize_group(rows),
        })

    condition_summary = []
    for (dimension, bucket, family, horizon, fee), rows in sorted(groups.items()):
        base = _summarize_group(baselines[(family, horizon, fee)])
        summary = _summarize_group(rows)
        base_pf = _numeric_pf(base["net_profit_factor"])
        cond_pf = _numeric_pf(summary["net_profit_factor"])
        lift = None
        if base_pf is not None and base_pf > 0 and cond_pf is not None and math.isfinite(cond_pf):
            lift = cond_pf / base_pf
        condition_summary.append({
            "dimension": dimension,
            "bucket": bucket,
            "family": family,
            "horizon_ms": horizon,
            "fee_bps_round_trip": fee,
            **summary,
            "baseline_net_profit_factor": base["net_profit_factor"],
            "baseline_net_mean_bps": base["net_mean_bps"],
            "profit_factor_lift_vs_family_baseline": lift,
        })

    ready = [row for row in condition_summary if row.get("screening_condition_ready") is True]
    exploratory = [row for row in condition_summary if row["observations"] >= 5 and row["independent_batches"] >= 2]
    exploratory.sort(
        key=lambda row: (
            _numeric_pf(row["net_profit_factor"]) or -math.inf,
            float(row["net_mean_bps"] or -math.inf),
            int(row["observations"]),
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "experiment": "multi_batch_market_condition_aggregate",
        "symbol": symbol,
        "context_symbol": context_symbol,
        "condition_protocol": CONDITION_PROTOCOL,
        "screening_readiness_rule": {
            "minimum_observations": MIN_SCREEN_OBSERVATIONS,
            "minimum_independent_batches": MIN_SCREEN_BATCHES,
            "minimum_positive_batch_fraction": MIN_POSITIVE_BATCH_FRACTION,
            "requires_net_profit_factor_above": 1.0,
            "requires_positive_net_expectancy": True,
        },
        "horizons_ms": horizons,
        "fees_bps_round_trip": fees,
        "unique_sources": list(sources.values()),
        "baseline_summary": baseline_summary,
        "condition_summary": condition_summary,
        "screening_conditions_ready": ready,
        "exploratory_top_conditions": exploratory[:25],
        "enriched_observations": enriched,
        "claims": {
            "exploratory_only": True,
            "independent_capture_batches_are_dependence_clusters": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

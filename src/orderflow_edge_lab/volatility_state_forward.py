from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence
import json


class VolatilityStateForwardError(ValueError):
    pass


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2.0 + 1.0
        for pos in range(cursor, end):
            ranks[order[pos]] = rank
        cursor = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    ml = statistics.fmean(left)
    mr = statistics.fmean(right)
    dl = [x - ml for x in left]
    dr = [x - mr for x in right]
    vl = sum(x * x for x in dl)
    vr = sum(x * x for x in dr)
    if vl <= 0 or vr <= 0:
        return None
    value = sum(a * b for a, b in zip(dl, dr)) / math.sqrt(vl * vr)
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    return _pearson(_rank(left), _rank(right))


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("experiment") != "regime_research_v1_market_state_scan":
        raise VolatilityStateForwardError(f"not a market-state scan: {path}")
    return payload


def _rows(
    report: Mapping[str, Any],
    feature: str,
    target: str,
) -> list[tuple[int, float, float]]:
    out: list[tuple[int, float, float]] = []
    for row in report.get("observations") or []:
        observed = row.get("observed_at_ns")
        x = _finite((row.get("features") or {}).get(feature))
        y = _finite((row.get("targets") or {}).get(target))
        if observed is None or x is None or y is None:
            continue
        out.append((int(observed), x, y))
    out.sort(key=lambda item: item[0])
    return out


def _quartile_calibration(rows: Sequence[tuple[int, float, float]]) -> list[dict[str, Any]]:
    if len(rows) < 8:
        return []
    ordered = sorted(rows, key=lambda item: item[1])
    bins: list[list[tuple[int, float, float]]] = [[], [], [], []]
    for index, row in enumerate(ordered):
        bucket = min(3, int(index * 4 / len(ordered)))
        bins[bucket].append(row)
    result: list[dict[str, Any]] = []
    for i, bucket in enumerate(bins, start=1):
        if not bucket:
            continue
        result.append(
            {
                "feature_rank_quartile": i,
                "observations": len(bucket),
                "median_feature": statistics.median([row[1] for row in bucket]),
                "median_target": statistics.median([row[2] for row in bucket]),
                "mean_target": statistics.fmean([row[2] for row in bucket]),
            }
        )
    return result


def evaluate_forward_cluster(
    report_paths: Iterable[str | Path],
    config: Mapping[str, Any],
    *,
    cluster_id: str,
) -> dict[str, Any]:
    reports = [_load(path) for path in report_paths]
    if not reports:
        raise VolatilityStateForwardError("no state reports supplied")

    feature = str(config["frozen_relationship"]["feature"])
    primary_target = str(config["frozen_relationship"]["primary_target"])
    secondary_targets = [str(v) for v in config["frozen_relationship"].get("secondary_targets", [])]
    expected_symbols = [str(v) for v in config["source"]["transfer_symbols"]]
    start_ns = int(
        datetime.fromisoformat(str(config["prospective_start_utc"]).replace("Z", "+00:00"))
        .timestamp()
        * 1_000_000_000
    )

    by_symbol: dict[str, Mapping[str, Any]] = {}
    for report in reports:
        symbol = str(report.get("symbol"))
        if symbol in by_symbol:
            raise VolatilityStateForwardError(f"duplicate symbol report: {symbol}")
        by_symbol[symbol] = report
    missing = [s for s in expected_symbols if s not in by_symbol]
    extra = sorted(set(by_symbol) - set(expected_symbols))
    if missing or extra:
        raise VolatilityStateForwardError(f"symbol mismatch missing={missing} extra={extra}")

    symbol_results: list[dict[str, Any]] = []
    all_primary: list[tuple[str, int, float, float]] = []
    all_times: list[int] = []
    for symbol in expected_symbols:
        report = by_symbol[symbol]
        primary_rows = _rows(report, feature, primary_target)
        if primary_rows and primary_rows[0][0] < start_ns:
            raise VolatilityStateForwardError(
                f"{symbol}: contains observation before prospective boundary"
            )
        all_times.extend(row[0] for row in primary_rows)
        all_primary.extend((symbol, *row) for row in primary_rows)
        primary_rho = _spearman(
            [row[1] for row in primary_rows],
            [row[2] for row in primary_rows],
        )
        secondary: dict[str, Any] = {}
        for target in secondary_targets:
            rows = _rows(report, feature, target)
            secondary[target] = {
                "observations": len(rows),
                "spearman": _spearman([r[1] for r in rows], [r[2] for r in rows]),
            }
        symbol_results.append(
            {
                "symbol": symbol,
                "observations": len(primary_rows),
                "primary_spearman": primary_rho,
                "positive_primary_spearman": primary_rho is not None and primary_rho > 0,
                "quartile_calibration": _quartile_calibration(primary_rows),
                "secondary_horizon_results": secondary,
            }
        )

    valid = [row for row in symbol_results if row["primary_spearman"] is not None]
    minimum_obs = int(config["review_rule"]["minimum_observations_per_symbol_per_cluster"])
    eligible = [row for row in valid if int(row["observations"]) >= minimum_obs]

    pooled_x_rank: list[float] = []
    pooled_y_rank: list[float] = []
    grouped: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for symbol, ts, x, y in all_primary:
        grouped[symbol].append((ts, x, y))
    for symbol in expected_symbols:
        rows = grouped[symbol]
        if len(rows) < 2:
            continue
        xr = _rank([r[1] for r in rows])
        yr = _rank([r[2] for r in rows])
        scale = max(1.0, float(len(rows)))
        pooled_x_rank.extend([value / scale for value in xr])
        pooled_y_rank.extend([value / scale for value in yr])

    rhos = [float(row["primary_spearman"]) for row in eligible]
    cluster_median = statistics.median(rhos) if rhos else None
    positive_fraction = (
        sum(value > 0 for value in rhos) / len(rhos) if rhos else None
    )
    pooled_within_symbol = _pearson(pooled_x_rank, pooled_y_rank)

    return {
        "schema_version": 1,
        "analysis": "volatility_state_forward_cluster_v1",
        "watch_id": str(config["watch_id"]),
        "cluster_id": str(cluster_id),
        "prospective_start_utc": str(config["prospective_start_utc"]),
        "feature": feature,
        "primary_target": primary_target,
        "secondary_targets": secondary_targets,
        "capture_first_observation_utc": (
            datetime.fromtimestamp(min(all_times) / 1e9, tz=timezone.utc).isoformat()
            if all_times
            else None
        ),
        "capture_last_observation_utc": (
            datetime.fromtimestamp(max(all_times) / 1e9, tz=timezone.utc).isoformat()
            if all_times
            else None
        ),
        "expected_symbol_count": len(expected_symbols),
        "valid_symbol_count": len(valid),
        "eligible_symbol_count": len(eligible),
        "cluster_median_primary_spearman": cluster_median,
        "cluster_positive_symbol_fraction": positive_fraction,
        "pooled_within_symbol_rank_correlation": pooled_within_symbol,
        "symbol_results": symbol_results,
        "formal_verdict": "WITHHELD",
        "claims": {
            "d4_prospective_cluster": True,
            "simultaneous_symbols_count_as_one_dependence_cluster": True,
            "strategy_pnl_used": False,
            "model_retrained": False,
            "thresholds_retuned": False,
            "rank_relationship_replication_only": True,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }


def restore_forward_cluster_history(
    cluster_paths: Iterable[str | Path],
    config: Mapping[str, Any],
    history_dir: str | Path,
) -> dict[str, Any]:
    start = str(config["prospective_start_utc"])
    watch_id = str(config["watch_id"])
    restored: dict[str, tuple[str, dict[str, Any]]] = {}

    for path in cluster_paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("analysis") != "volatility_state_forward_cluster_v1":
            continue
        if str(payload.get("watch_id")) != watch_id:
            raise VolatilityStateForwardError(f"watch_id mismatch in restored cluster: {path}")
        if str(payload.get("prospective_start_utc")) != start:
            raise VolatilityStateForwardError(
                f"prospective boundary mismatch in restored cluster: {path}"
            )
        cluster_id = str(payload.get("cluster_id") or "")
        if not cluster_id:
            raise VolatilityStateForwardError(f"missing cluster_id in restored cluster: {path}")
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        previous = restored.get(cluster_id)
        if previous is not None and previous[0] != canonical:
            raise VolatilityStateForwardError(
                f"conflicting payloads for restored cluster_id {cluster_id}"
            )
        restored[cluster_id] = (canonical, payload)

    destination = Path(history_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for cluster_id in sorted(restored):
        payload = restored[cluster_id][1]
        target = destination / cluster_id / "cluster.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    return {
        "schema_version": 1,
        "analysis": "volatility_state_forward_restore_v1",
        "watch_id": watch_id,
        "prospective_start_utc": start,
        "restored_cluster_count": len(restored),
        "cluster_ids": sorted(restored),
        "claims": {
            "new_evidence_collected": False,
            "historical_cluster_values_changed": False,
            "review_thresholds_changed": False,
            "strategy_pnl_used": False,
        },
    }


def aggregate_forward_clusters(
    cluster_paths: Iterable[str | Path],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    clusters = [json.loads(Path(path).read_text(encoding="utf-8")) for path in cluster_paths]
    if not clusters:
        raise VolatilityStateForwardError("no forward clusters supplied")
    ids = [str(row["cluster_id"]) for row in clusters]
    if len(set(ids)) != len(ids):
        raise VolatilityStateForwardError("cluster_id values must be unique")
    start = str(config["prospective_start_utc"])
    for row in clusters:
        if row.get("analysis") != "volatility_state_forward_cluster_v1":
            raise VolatilityStateForwardError("unexpected cluster report")
        if str(row.get("watch_id")) != str(config["watch_id"]):
            raise VolatilityStateForwardError("watch_id mismatch")
        if str(row.get("prospective_start_utc")) != start:
            raise VolatilityStateForwardError("prospective boundary mismatch")

    eligible = [
        row for row in clusters
        if int(row.get("eligible_symbol_count") or 0)
        >= int(config["review_rule"]["minimum_eligible_symbols_per_cluster"])
        and _finite(row.get("cluster_median_primary_spearman")) is not None
    ]
    medians = [float(row["cluster_median_primary_spearman"]) for row in eligible]
    pooled = [
        float(row["pooled_within_symbol_rank_correlation"])
        for row in eligible
        if _finite(row.get("pooled_within_symbol_rank_correlation")) is not None
    ]
    dates = {
        str(row.get("capture_first_observation_utc", ""))[:10]
        for row in eligible
        if row.get("capture_first_observation_utc")
    }
    min_clusters = int(config["review_rule"]["minimum_independent_clusters"])
    min_dates = int(config["review_rule"]["minimum_distinct_utc_dates"])
    ready = len(eligible) >= min_clusters and len(dates) >= min_dates

    return {
        "schema_version": 1,
        "analysis": "volatility_state_forward_aggregate_v1",
        "watch_id": str(config["watch_id"]),
        "prospective_start_utc": start,
        "total_cluster_count": len(clusters),
        "eligible_cluster_count": len(eligible),
        "distinct_utc_dates": sorted(dates),
        "cluster_median_spearman_median": statistics.median(medians) if medians else None,
        "positive_cluster_fraction": (
            sum(value > 0 for value in medians) / len(medians) if medians else None
        ),
        "median_pooled_within_symbol_rank_correlation": (
            statistics.median(pooled) if pooled else None
        ),
        "clusters": sorted(clusters, key=lambda row: str(row["cluster_id"])),
        "review_progress": {
            "minimum_independent_clusters": min_clusters,
            "minimum_distinct_utc_dates": min_dates,
            "cluster_progress_fraction": min(1.0, len(eligible) / min_clusters),
            "date_progress_fraction": min(1.0, len(dates) / min_dates),
            "ready_for_review": ready,
        },
        "formal_verdict": "WITHHELD",
        "claims": {
            "state_prediction_only": True,
            "strategy_pnl_used": False,
            "no_early_pass_fail": True,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }

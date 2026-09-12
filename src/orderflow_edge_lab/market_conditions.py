from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable

from orderflow_edge_lab.direction_pair import evaluate_pair
from orderflow_edge_lab.orderflow_backtest import BacktestConfig, _load


class MarketConditionError(ValueError):
    pass


CONDITION_PROTOCOL = {
    "spread_bps": ["narrow<=1", "medium>1<=3", "wide>3"],
    "range_to_spread_15s": ["low<=2", "medium>2<=6", "high>6"],
    "abs_return_to_spread_15s": ["flat<=1", "moving>1<=4", "strong>4"],
    "rolling_trade_count_10s": ["sparse<=2", "active3-8", "intense>=9"],
    "btc_flow_alignment": ["aligned", "neutral", "against"],
    "signal_strength_multiple": ["weak1-1.5", "medium1.5-2.5", "strong>=2.5"],
    "utc_session": ["00-08", "08-16", "16-24"],
}


MIN_SCREEN_OBSERVATIONS = 20
MIN_SCREEN_BATCHES = 3
MIN_POSITIVE_BATCH_FRACTION = 2.0 / 3.0


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _spread_bps(observation: dict[str, Any]) -> float | None:
    bid = _finite(observation.get("signal_bid"))
    ask = _finite(observation.get("signal_ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 10_000.0


def _quote_index(rows: list[dict[str, Any]], symbol: str) -> tuple[list[int], list[float]]:
    times: list[int] = []
    mids: list[float] = []
    for row in rows:
        if row.get("symbol") != symbol:
            continue
        bid = _finite(row.get("best_bid"))
        ask = _finite(row.get("best_ask"))
        if bid is None or ask is None or bid <= 0 or ask <= bid:
            continue
        observed = row.get("observed_at_ns")
        if observed is None:
            continue
        times.append(int(observed))
        mids.append((bid + ask) / 2.0)
    return times, mids


def _window_metrics(times: list[int], mids: list[float], end_ns: int, seconds: float) -> dict[str, float | None]:
    start_ns = end_ns - int(seconds * 1_000_000_000)
    left = bisect_left(times, start_ns)
    right = bisect_right(times, end_ns)
    window = mids[left:right]
    if not window:
        return {"return_bps": None, "range_bps": None, "updates_per_second": 0.0}
    first = window[0]
    last = window[-1]
    if first <= 0:
        return {"return_bps": None, "range_bps": None, "updates_per_second": len(window) / seconds}
    ret = (last / first - 1.0) * 10_000.0
    low = min(window)
    high = max(window)
    rng = (high / low - 1.0) * 10_000.0 if low > 0 else None
    return {"return_bps": ret, "range_bps": rng, "updates_per_second": len(window) / seconds}


def _signal_rows(rows: list[dict[str, Any]], symbol: str) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.get("symbol") == symbol and row.get("event_type") == "trade" and row.get("observed_at_ns") is not None:
            output[int(row["observed_at_ns"])] = row
    return output


def _strength_multiple(observation: dict[str, Any], cfg: BacktestConfig) -> float | None:
    family = str(observation.get("family"))
    flow = _finite(observation.get("flow_ratio"))
    book = _finite(observation.get("book_imbalance"))
    micro = _finite(observation.get("microprice_edge"))
    values: list[float] = []
    if family == "cvd" and flow is not None:
        values = [abs(flow) / cfg.min_trade_flow_ratio]
    elif family == "book" and book is not None:
        values = [abs(book) / cfg.min_book_imbalance]
    elif family == "microprice" and micro is not None:
        values = [abs(micro) / cfg.min_microprice_edge]
    elif family in {"aligned", "aligned_btc"}:
        if flow is not None:
            values.append(abs(flow) / cfg.min_trade_flow_ratio)
        if book is not None:
            values.append(abs(book) / cfg.min_book_imbalance)
        if micro is not None:
            values.append(abs(micro) / cfg.min_microprice_edge)
    return min(values) if values else None


def _bucket_spread(value: float | None) -> str | None:
    if value is None:
        return None
    if value <= 1.0:
        return "narrow<=1"
    if value <= 3.0:
        return "medium>1<=3"
    return "wide>3"


def _bucket_ratio(value: float | None, *, kind: str) -> str | None:
    if value is None:
        return None
    if kind == "range":
        if value <= 2.0:
            return "low<=2"
        if value <= 6.0:
            return "medium>2<=6"
        return "high>6"
    if value <= 1.0:
        return "flat<=1"
    if value <= 4.0:
        return "moving>1<=4"
    return "strong>4"


def _bucket_trade_count(value: int | None) -> str | None:
    if value is None:
        return None
    if value <= 2:
        return "sparse<=2"
    if value <= 8:
        return "active3-8"
    return "intense>=9"


def _bucket_strength(value: float | None) -> str | None:
    if value is None:
        return None
    if value < 1.5:
        return "weak1-1.5"
    if value < 2.5:
        return "medium1.5-2.5"
    return "strong>=2.5"


def _btc_alignment(observation: dict[str, Any]) -> str:
    btc = int(observation.get("btc_flow_side") or 0)
    side = int(observation.get("signal_side", observation.get("side", 0)) or 0)
    if btc == 0 or side == 0:
        return "neutral"
    return "aligned" if btc == side else "against"


def _utc_session(observed_ns: int) -> str:
    hour = datetime.fromtimestamp(observed_ns / 1_000_000_000, tz=timezone.utc).hour
    if hour < 8:
        return "00-08"
    if hour < 16:
        return "08-16"
    return "16-24"


def _enrich_observation(
    observation: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    quote_times: list[int],
    quote_mids: list[float],
    signal_rows: dict[int, dict[str, Any]],
    cfg: BacktestConfig,
    batch_id: str,
) -> dict[str, Any]:
    observed_ns = int(observation["signal_observed_at_ns"])
    spread_bps = _spread_bps(observation)
    local = _window_metrics(quote_times, quote_mids, observed_ns, 15.0)
    signal_row = signal_rows.get(observed_ns)
    trade_count = None
    if signal_row is not None:
        try:
            trade_count = int(signal_row.get("rolling_trade_count") or 0)
        except (TypeError, ValueError):
            trade_count = None
    range_ratio = None
    return_ratio = None
    if spread_bps is not None and spread_bps > 0:
        if local["range_bps"] is not None:
            range_ratio = float(local["range_bps"]) / spread_bps
        if local["return_bps"] is not None:
            return_ratio = abs(float(local["return_bps"])) / spread_bps
    strength = _strength_multiple(observation, cfg)
    buckets = {
        "spread_bps": _bucket_spread(spread_bps),
        "range_to_spread_15s": _bucket_ratio(range_ratio, kind="range"),
        "abs_return_to_spread_15s": _bucket_ratio(return_ratio, kind="return"),
        "rolling_trade_count_10s": _bucket_trade_count(trade_count),
        "btc_flow_alignment": _btc_alignment(observation),
        "signal_strength_multiple": _bucket_strength(strength),
        "utc_session": _utc_session(observed_ns),
    }
    return {
        **observation,
        "batch_id": batch_id,
        "spread_bps": spread_bps,
        "local_return_15s_bps": local["return_bps"],
        "local_range_15s_bps": local["range_bps"],
        "local_quote_updates_per_second_15s": local["updates_per_second"],
        "range_to_spread_15s": range_ratio,
        "abs_return_to_spread_15s": return_ratio,
        "rolling_trade_count_10s": trade_count,
        "signal_strength_multiple": strength,
        "conditions": buckets,
    }


def _profit_factor(values: list[float]) -> float | str | None:
    profit = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss > 0:
        return profit / loss
    return "INF" if profit > 0 else None


def _numeric_pf(value: float | str | None) -> float | None:
    if value == "INF":
        return math.inf
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def _summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nets = [float(row["net_bps"]) for row in rows]
    by_batch: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_batch[str(row["batch_id"])].append(float(row["net_bps"]))
    batch_means = {batch: sum(values) / len(values) for batch, values in by_batch.items()}
    positive_batch_fraction = (
        sum(value > 0 for value in batch_means.values()) / len(batch_means)
        if batch_means
        else 0.0
    )
    pf = _profit_factor(nets)
    pf_numeric = _numeric_pf(pf)
    net_mean = sum(nets) / len(nets) if nets else None
    ready = bool(
        len(nets) >= MIN_SCREEN_OBSERVATIONS
        and len(by_batch) >= MIN_SCREEN_BATCHES
        and net_mean is not None
        and net_mean > 0
        and pf_numeric is not None
        and pf_numeric > 1.0
        and positive_batch_fraction >= MIN_POSITIVE_BATCH_FRACTION
    )
    return {
        "observations": len(nets),
        "independent_batches": len(by_batch),
        "net_profit_factor": pf,
        "net_mean_bps": net_mean,
        "net_total_bps": sum(nets),
        "net_win_rate": sum(value > 0 for value in nets) / len(nets) if nets else None,
        "positive_batch_fraction": positive_batch_fraction,
        "batch_net_mean_bps": batch_means,
        "screening_condition_ready": ready,
    }


def analyze_market_conditions(
    feature_paths: Iterable[str | Path],
    cfg: BacktestConfig = BacktestConfig(),
    *,
    horizons_ms: tuple[int, ...] = (5_000, 15_000, 30_000),
    fees_bps: tuple[float, ...] = (4.0, 8.0),
) -> dict[str, Any]:
    paths = [Path(path) for path in feature_paths]
    if not paths:
        raise MarketConditionError("at least one feature path is required")
    enriched: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for index, path in enumerate(paths, 1):
        pair = evaluate_pair(path, cfg)
        rows = _load(path)
        quote_times, quote_mids = _quote_index(rows, cfg.symbol)
        signal_rows = _signal_rows(rows, cfg.symbol)
        batch_id = f"batch_{index}:{pair['source_sha256'][:12]}"
        sources.append({
            "batch_id": batch_id,
            "path_name": path.name,
            "source_sha256": pair["source_sha256"],
            "signals": pair["signals"],
        })
        for observation in pair["streams"]["original"]["observations"]:
            if int(observation["horizon_ms"]) not in horizons_ms:
                continue
            if float(observation["fee_bps_round_trip"]) not in fees_bps:
                continue
            enriched.append(
                _enrich_observation(
                    observation,
                    rows=rows,
                    quote_times=quote_times,
                    quote_mids=quote_mids,
                    signal_rows=signal_rows,
                    cfg=cfg,
                    batch_id=batch_id,
                )
            )

    groups: dict[tuple[str, str, str, int, float], list[dict[str, Any]]] = defaultdict(list)
    baselines: dict[tuple[str, int, float], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        family = str(row["family"])
        horizon = int(row["horizon_ms"])
        fee = float(row["fee_bps_round_trip"])
        baselines[(family, horizon, fee)].append(row)
        for dimension, bucket in row["conditions"].items():
            if bucket is None:
                continue
            groups[(dimension, str(bucket), family, horizon, fee)].append(row)

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
        baseline = _summarize_group(baselines[(family, horizon, fee)])
        summary = _summarize_group(rows)
        baseline_pf = _numeric_pf(baseline["net_profit_factor"])
        condition_pf = _numeric_pf(summary["net_profit_factor"])
        pf_lift = None
        if baseline_pf is not None and baseline_pf > 0 and condition_pf is not None and math.isfinite(condition_pf):
            pf_lift = condition_pf / baseline_pf
        condition_summary.append({
            "dimension": dimension,
            "bucket": bucket,
            "family": family,
            "horizon_ms": horizon,
            "fee_bps_round_trip": fee,
            **summary,
            "baseline_net_profit_factor": baseline["net_profit_factor"],
            "baseline_net_mean_bps": baseline["net_mean_bps"],
            "profit_factor_lift_vs_family_baseline": pf_lift,
        })

    ready = [row for row in condition_summary if row["screening_condition_ready"]]
    exploratory = [
        row for row in condition_summary
        if row["observations"] >= 5 and row["independent_batches"] >= 2
    ]
    exploratory.sort(
        key=lambda row: (
            _numeric_pf(row["net_profit_factor"]) or -math.inf,
            float(row["net_mean_bps"] or -math.inf),
            int(row["observations"]),
        ),
        reverse=True,
    )

    combined_digest = hashlib.sha256(
        "".join(source["source_sha256"] for source in sources).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "experiment": "pre_registered_market_condition_stratification",
        "combined_source_sha256": combined_digest,
        "sources": sources,
        "symbol": cfg.symbol,
        "context_symbol": cfg.context_symbol,
        "condition_protocol": CONDITION_PROTOCOL,
        "screening_readiness_rule": {
            "minimum_observations": MIN_SCREEN_OBSERVATIONS,
            "minimum_independent_batches": MIN_SCREEN_BATCHES,
            "minimum_positive_batch_fraction": MIN_POSITIVE_BATCH_FRACTION,
            "requires_net_profit_factor_above": 1.0,
            "requires_positive_net_expectancy": True,
        },
        "horizons_ms": list(horizons_ms),
        "fees_bps_round_trip": list(fees_bps),
        "baseline_summary": baseline_summary,
        "condition_summary": condition_summary,
        "screening_conditions_ready": ready,
        "exploratory_top_conditions": exploratory[:25],
        "enriched_observations": enriched,
        "claims": {
            "exploratory_only": True,
            "conditions_pre_registered_before_cross_pair_results": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

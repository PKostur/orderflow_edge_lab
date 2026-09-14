from __future__ import annotations

from collections import defaultdict, deque
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from orderflow_edge_lab.direction_pair import evaluate_pair
from orderflow_edge_lab.market_conditions import (
    _btc_alignment,
    _quote_index,
    _signal_rows,
    _spread_bps,
    _strength_multiple,
    _window_metrics,
)
from orderflow_edge_lab.orderflow_backtest import BacktestConfig, _load


class LskRegimeRouterError(ValueError):
    pass


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise LskRegimeRouterError("quantile requires non-empty values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _profit_factor(values: list[float]) -> float | str | None:
    gains = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    if losses > 0:
        return gains / losses
    if gains > 0:
        return "INF"
    return None


def _pf_numeric(value: float | str | None) -> float | None:
    if value == "INF":
        return math.inf
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _pair_key(row: dict[str, Any]) -> tuple[int, str, int, float]:
    return (
        int(row["signal_observed_at_ns"]),
        str(row["family"]),
        int(row["horizon_ms"]),
        float(row["fee_bps_round_trip"]),
    )


def _summarize(values: list[float]) -> dict[str, Any]:
    return {
        "trades": len(values),
        "net_mean_bps": sum(values) / len(values) if values else None,
        "net_total_bps": sum(values),
        "net_win_rate": sum(x > 0 for x in values) / len(values) if values else None,
        "net_profit_factor": _profit_factor(values),
    }


def _state_for_observation(
    observation: dict[str, Any],
    *,
    quote_times: list[int],
    quote_mids: list[float],
    signal_rows: dict[int, dict[str, Any]],
    cfg: BacktestConfig,
) -> dict[str, Any]:
    observed_ns = int(observation["signal_observed_at_ns"])
    spread = _spread_bps(observation)
    local = _window_metrics(quote_times, quote_mids, observed_ns, 15.0)
    signal_row = signal_rows.get(observed_ns)
    trade_count = None
    if signal_row is not None:
        try:
            trade_count = int(signal_row.get("rolling_trade_count") or 0)
        except (TypeError, ValueError):
            trade_count = None
    strength = _strength_multiple(observation, cfg)
    abs_return_to_spread = None
    range_to_spread = None
    if spread is not None and spread > 0:
        if local["return_bps"] is not None:
            abs_return_to_spread = abs(float(local["return_bps"])) / spread
        if local["range_bps"] is not None:
            range_to_spread = float(local["range_bps"]) / spread
    response_efficiency = None
    if local["return_bps"] is not None and strength is not None and strength > 0:
        response_efficiency = abs(float(local["return_bps"])) / max(float(strength), 1e-9)
    return {
        "signal_observed_at_ns": observed_ns,
        "spread_bps": spread,
        "local_return_15s_bps": local["return_bps"],
        "local_range_15s_bps": local["range_bps"],
        "local_quote_updates_per_second_15s": local["updates_per_second"],
        "rolling_trade_count_10s": trade_count,
        "signal_strength_multiple": strength,
        "abs_return_to_spread_15s": abs_return_to_spread,
        "range_to_spread_15s": range_to_spread,
        "price_response_efficiency": response_efficiency,
        "btc_flow_alignment": _btc_alignment(observation),
    }


def _history_values(history: deque[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in history:
        value = _finite(row.get(key))
        if value is not None:
            out.append(value)
    return out


def _classify(
    state: dict[str, Any],
    history: deque[dict[str, Any]],
    *,
    min_prior: int,
) -> tuple[str, dict[str, Any]]:
    required = {
        "spread_bps",
        "local_range_15s_bps",
        "local_quote_updates_per_second_15s",
        "rolling_trade_count_10s",
        "signal_strength_multiple",
        "abs_return_to_spread_15s",
        "price_response_efficiency",
    }
    if len(history) < min_prior or any(_finite(state.get(key)) is None for key in required):
        return "no_trade", {"reason": "insufficient_causal_baseline"}

    baselines: dict[str, float] = {}
    for key in required:
        vals = _history_values(history, key)
        if len(vals) < min_prior:
            return "no_trade", {"reason": f"insufficient_prior_{key}"}
        baselines[f"{key}_median"] = median(vals)
        baselines[f"{key}_q25"] = _quantile(vals, 0.25)
        baselines[f"{key}_q75"] = _quantile(vals, 0.75)

    spread = float(state["spread_bps"])
    spread_med = baselines["spread_bps_median"]
    spread_vs_med = spread / spread_med if spread_med > 0 else math.inf
    strength = float(state["signal_strength_multiple"])
    common = state["btc_flow_alignment"] == "aligned" and strength >= 1.0

    exhausted = bool(
        common
        and float(state["abs_return_to_spread_15s"]) >= baselines["abs_return_to_spread_15s_q75"]
        and float(state["price_response_efficiency"]) <= baselines["price_response_efficiency_q25"]
        and (
            float(state["rolling_trade_count_10s"]) < baselines["rolling_trade_count_10s_median"]
            or float(state["local_quote_updates_per_second_15s"]) < baselines["local_quote_updates_per_second_15s_median"]
            or spread_vs_med > 1.0
        )
    )

    continuation = bool(
        common
        and float(state["rolling_trade_count_10s"]) >= baselines["rolling_trade_count_10s_median"]
        and float(state["local_quote_updates_per_second_15s"]) >= baselines["local_quote_updates_per_second_15s_median"]
        and float(state["local_range_15s_bps"]) >= baselines["local_range_15s_bps_median"]
        and float(state["price_response_efficiency"]) >= baselines["price_response_efficiency_median"]
        and float(state["abs_return_to_spread_15s"]) < baselines["abs_return_to_spread_15s_q75"]
        and spread_vs_med <= 1.25
    )

    route = "reversed" if exhausted else "original" if continuation else "no_trade"
    return route, {
        "reason": "exhaustion" if exhausted else "continuation" if continuation else "ambiguous",
        "spread_vs_prior_median": spread_vs_med,
        "baselines": baselines,
    }


def evaluate_lsk_regime_router(
    feature_paths: Iterable[str | Path],
    *,
    config_path: str | Path = "config/lsk_regime_router_v1.json",
) -> dict[str, Any]:
    protocol = json.loads(Path(config_path).read_text(encoding="utf-8"))
    symbol = str(protocol["symbol"])
    context_symbol = str(protocol["context_symbol"])
    family = str(protocol["family"])
    horizon = int(protocol["horizon_ms"])
    fees = {float(x) for x in protocol["fee_bps_round_trip"]}
    stresses = [float(x) for x in protocol["additional_execution_stress_bps_round_trip"]]
    min_prior = int(protocol["causal_baseline"]["minimum_prior_signals"])
    max_prior = int(protocol["causal_baseline"]["maximum_prior_signals"])
    cfg = BacktestConfig(symbol=symbol, context_symbol=context_symbol)

    routed_rows: list[dict[str, Any]] = []
    source_meta: list[dict[str, Any]] = []

    for batch_index, raw_path in enumerate(feature_paths, 1):
        path = Path(raw_path)
        pair = evaluate_pair(path, cfg)
        rows = _load(path)
        quote_times, quote_mids = _quote_index(rows, symbol)
        signal_rows = _signal_rows(rows, symbol)
        batch_id = f"batch_{batch_index}:{pair['source_sha256'][:12]}"
        source_meta.append({"batch_id": batch_id, "source_sha256": pair["source_sha256"], "path_name": path.name})

        original = {
            _pair_key(row): row
            for row in pair["streams"]["original"]["observations"]
            if str(row["family"]) == family and int(row["horizon_ms"]) == horizon and float(row["fee_bps_round_trip"]) in fees
        }
        reversed_rows = {
            _pair_key(row): row
            for row in pair["streams"]["reversed"]["observations"]
            if str(row["family"]) == family and int(row["horizon_ms"]) == horizon and float(row["fee_bps_round_trip"]) in fees
        }
        if original.keys() != reversed_rows.keys():
            raise LskRegimeRouterError(f"paired observation mismatch in {path}")

        histories: dict[float, deque[dict[str, Any]]] = {fee: deque(maxlen=max_prior) for fee in fees}
        for key in sorted(original):
            orig = original[key]
            rev = reversed_rows[key]
            fee = float(orig["fee_bps_round_trip"])
            state = _state_for_observation(
                orig,
                quote_times=quote_times,
                quote_mids=quote_mids,
                signal_rows=signal_rows,
                cfg=cfg,
            )
            route, diagnostic = _classify(state, histories[fee], min_prior=min_prior)
            routed_rows.append({
                "batch_id": batch_id,
                "fee_bps_round_trip": fee,
                "route": route,
                "state": state,
                "diagnostic": diagnostic,
                "original_net_bps": float(orig["net_bps"]),
                "reversed_net_bps": float(rev["net_bps"]),
            })
            histories[fee].append(state)

    results: list[dict[str, Any]] = []
    for fee in sorted(fees):
        fee_rows = [row for row in routed_rows if float(row["fee_bps_round_trip"]) == fee]
        for stress in stresses:
            router_values: list[float] = []
            always_original: list[float] = []
            always_reversed: list[float] = []
            by_batch: dict[str, list[float]] = defaultdict(list)
            route_counts = defaultdict(int)
            for row in fee_rows:
                route = str(row["route"])
                route_counts[route] += 1
                always_original.append(float(row["original_net_bps"]) - stress)
                always_reversed.append(float(row["reversed_net_bps"]) - stress)
                if route == "no_trade":
                    continue
                value = float(row["original_net_bps"] if route == "original" else row["reversed_net_bps"]) - stress
                router_values.append(value)
                by_batch[str(row["batch_id"])].append(value)

            batch_means = {batch: sum(vals) / len(vals) for batch, vals in by_batch.items() if vals}
            positive_cluster_fraction = (
                sum(v > 0 for v in batch_means.values()) / len(batch_means) if batch_means else 0.0
            )
            positive_profit_by_batch = {
                batch: max(sum(vals), 0.0) for batch, vals in by_batch.items() if vals
            }
            total_positive = sum(positive_profit_by_batch.values())
            max_profit_share = (
                max(positive_profit_by_batch.values()) / total_positive
                if total_positive > 0 and positive_profit_by_batch
                else None
            )
            summary = _summarize(router_values)
            pf = _pf_numeric(summary["net_profit_factor"])
            numeric_screen = bool(
                len(batch_means) >= int(protocol["numeric_forward_screen"]["minimum_independent_clusters"])
                and summary["net_mean_bps"] is not None
                and float(summary["net_mean_bps"]) > float(protocol["numeric_forward_screen"]["minimum_net_mean_bps"])
                and pf is not None
                and pf > float(protocol["numeric_forward_screen"]["minimum_profit_factor_after_cost"])
                and positive_cluster_fraction >= float(protocol["numeric_forward_screen"]["minimum_positive_cluster_fraction"])
                and max_profit_share is not None
                and max_profit_share <= float(protocol["numeric_forward_screen"]["maximum_single_cluster_profit_share"])
            )
            results.append({
                "fee_bps_round_trip": fee,
                "additional_execution_stress_bps_round_trip": stress,
                "router": summary,
                "route_counts": dict(route_counts),
                "independent_clusters_with_trades": len(batch_means),
                "positive_cluster_fraction": positive_cluster_fraction,
                "batch_net_mean_bps": batch_means,
                "maximum_single_cluster_positive_profit_share": max_profit_share,
                "always_original": _summarize(always_original),
                "always_reversed": _summarize(always_reversed),
                "numeric_forward_screen_would_pass": numeric_screen,
            })

    return {
        "schema_version": 1,
        "experiment": protocol["protocol_name"],
        "protocol_status": protocol["status"],
        "sources": source_meta,
        "results": results,
        "routed_observations": routed_rows,
        "claims": {
            "known_capture_evaluation_is_exploratory_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "standalone_router_promotable": False,
            "live_order_transmission_supported": False,
        },
    }

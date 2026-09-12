from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from orderflow_edge_lab.orderflow_backtest import _load


class MarketStateScanError(ValueError):
    pass


@dataclass(frozen=True)
class MarketStateScanConfig:
    symbol: str = "ENA_USDT"
    context_symbol: str = "BTC_USDT"
    sample_seconds: int = 5
    directionality_horizons_seconds: tuple[int, ...] = (15, 30, 60, 300)
    volatility_horizons_seconds: tuple[int, ...] = (30, 60, 300)
    liquidity_horizons_seconds: tuple[int, ...] = (5, 15, 30, 60)
    continuation_horizons_seconds: tuple[int, ...] = (15, 30, 60, 300)
    displacement_lookback_seconds: int = 15
    minimum_association_observations: int = 20
    redundancy_abs_spearman_threshold: float = 0.80


SIGNED_FEATURES = (
    "book_imbalance_10",
    "microprice_edge_spread_units",
    "depth_flow_imbalance",
    "flow_ratio_10s",
    "local_return_15s_bps",
    "btc_return_15s_bps",
)
MAGNITUDE_FEATURES = (
    "abs_book_imbalance_10",
    "abs_microprice_edge_spread_units",
    "abs_depth_flow_imbalance",
    "abs_flow_ratio_10s",
    "rolling_trade_count_10s",
    "trade_velocity_per_second",
    "local_range_to_spread_15s",
)
LIQUIDITY_FEATURES = (
    "spread_bps",
    "top_depth_notional",
)


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _mid(row: Mapping[str, Any]) -> float | None:
    bid = _finite(row.get("best_bid"))
    ask = _finite(row.get("best_ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return None
    return (bid + ask) / 2.0


def _spread_bps(row: Mapping[str, Any]) -> float | None:
    bid = _finite(row.get("best_bid"))
    ask = _finite(row.get("best_ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid * 10_000.0


def _micro_edge(row: Mapping[str, Any]) -> float | None:
    bid = _finite(row.get("best_bid"))
    ask = _finite(row.get("best_ask"))
    micro = _finite(row.get("microprice"))
    if bid is None or ask is None or micro is None or bid <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / 2.0
    half_spread = (ask - bid) / 2.0
    return (micro - mid) / half_spread if half_spread > 0 else None


def _flow_ratio(row: Mapping[str, Any]) -> float | None:
    buy = _finite(row.get("rolling_buy_volume"))
    sell = _finite(row.get("rolling_sell_volume"))
    if buy is None or sell is None or buy + sell <= 0:
        return None
    return (buy - sell) / (buy + sell)


def _top_depth_notional(row: Mapping[str, Any]) -> float | None:
    bid = _finite(row.get("best_bid"))
    ask = _finite(row.get("best_ask"))
    bid_qty = _finite(row.get("best_bid_contract_volume", row.get("best_bid_qty")))
    ask_qty = _finite(row.get("best_ask_contract_volume", row.get("best_ask_qty")))
    if None in (bid, ask, bid_qty, ask_qty) or bid <= 0 or ask <= 0 or bid_qty < 0 or ask_qty < 0:
        return None
    return bid * bid_qty + ask * ask_qty


def _series(rows: Sequence[Mapping[str, Any]], symbol: str) -> tuple[list[int], list[float], list[float], list[float]]:
    times: list[int] = []
    mids: list[float] = []
    spreads: list[float] = []
    depths: list[float] = []
    for row in rows:
        if row.get("symbol") != symbol:
            continue
        observed = row.get("observed_at_ns")
        mid = _mid(row)
        spread = _spread_bps(row)
        depth = _top_depth_notional(row)
        if observed is None or mid is None or spread is None:
            continue
        times.append(int(observed))
        mids.append(mid)
        spreads.append(spread)
        depths.append(depth if depth is not None else math.nan)
    return times, mids, spreads, depths


def _last_index_at_or_before(times: Sequence[int], observed_ns: int) -> int | None:
    index = bisect_right(times, observed_ns) - 1
    return index if index >= 0 else None


def _first_index_at_or_after(times: Sequence[int], observed_ns: int) -> int | None:
    index = bisect_left(times, observed_ns)
    return index if index < len(times) else None


def _window_indices(times: Sequence[int], start_ns: int, end_ns: int) -> tuple[int, int]:
    return bisect_left(times, start_ns), bisect_right(times, end_ns)


def _return_bps(start: float, end: float) -> float | None:
    if start <= 0 or end <= 0:
        return None
    value = (end / start - 1.0) * 10_000.0
    return value if math.isfinite(value) else None


def _range_bps(values: Sequence[float]) -> float | None:
    if not values:
        return None
    low = min(values)
    high = max(values)
    if low <= 0:
        return None
    return (high / low - 1.0) * 10_000.0


def _directional_efficiency(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    span = max(values) - min(values)
    if span <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / span


def _realized_volatility_bps(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    sum_sq = 0.0
    used = 0
    for previous, current in zip(values, values[1:]):
        if previous <= 0 or current <= 0:
            continue
        ret = math.log(current / previous)
        if math.isfinite(ret):
            sum_sq += ret * ret
            used += 1
    return math.sqrt(sum_sq) * 10_000.0 if used else None


def _mean_finite(values: Iterable[float]) -> float | None:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return fmean(finite) if finite else None


def _past_window_metric(times: Sequence[int], values: Sequence[float], anchor_ns: int, seconds: int) -> list[float]:
    left, right = _window_indices(times, anchor_ns - seconds * 1_000_000_000, anchor_ns)
    return list(values[left:right])


def _future_window_metric(times: Sequence[int], values: Sequence[float], anchor_ns: int, seconds: int) -> list[float]:
    left, right = _window_indices(times, anchor_ns, anchor_ns + seconds * 1_000_000_000)
    return list(values[left:right])


def _future_endpoint(times: Sequence[int], values: Sequence[float], anchor_ns: int, seconds: int) -> float | None:
    index = _first_index_at_or_after(times, anchor_ns + seconds * 1_000_000_000)
    return float(values[index]) if index is not None else None


def _past_endpoint(times: Sequence[int], values: Sequence[float], anchor_ns: int, seconds: int) -> float | None:
    index = _last_index_at_or_before(times, anchor_ns - seconds * 1_000_000_000)
    return float(values[index]) if index is not None else None


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        average_rank = (cursor + end - 1) / 2.0 + 1.0
        for pos in range(cursor, end):
            ranks[order[pos]] = average_rank
        cursor = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = fmean(left)
    mean_right = fmean(right)
    centered_left = [value - mean_left for value in left]
    centered_right = [value - mean_right for value in right]
    variance_left = sum(value * value for value in centered_left)
    variance_right = sum(value * value for value in centered_right)
    if variance_left <= 0 or variance_right <= 0:
        return None
    covariance = sum(a * b for a, b in zip(centered_left, centered_right))
    value = covariance / math.sqrt(variance_left * variance_right)
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _association(rows: Sequence[Mapping[str, Any]], feature: str, target: str, minimum: int) -> dict[str, Any] | None:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        x = _finite(row.get("features", {}).get(feature))
        y = _finite(row.get("targets", {}).get(target))
        if x is not None and y is not None:
            pairs.append((x, y))
    if len(pairs) < minimum:
        return None
    left = [item[0] for item in pairs]
    right = [item[1] for item in pairs]
    return {
        "feature": feature,
        "target": target,
        "observations": len(pairs),
        "pearson": _pearson(left, right),
        "spearman": _pearson(_rank(left), _rank(right)),
    }


def _feature_association(rows: Sequence[Mapping[str, Any]], left_feature: str, right_feature: str, minimum: int) -> dict[str, Any] | None:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        left = _finite(row.get("features", {}).get(left_feature))
        right = _finite(row.get("features", {}).get(right_feature))
        if left is not None and right is not None:
            pairs.append((left, right))
    if len(pairs) < minimum:
        return None
    left_values = [item[0] for item in pairs]
    right_values = [item[1] for item in pairs]
    return {
        "left_feature": left_feature,
        "right_feature": right_feature,
        "observations": len(pairs),
        "pearson": _pearson(left_values, right_values),
        "spearman": _pearson(_rank(left_values), _rank(right_values)),
    }


def _redundancy_clusters(rows: Sequence[Mapping[str, Any]], features: Sequence[str], minimum: int, threshold: float) -> tuple[list[dict[str, Any]], list[list[str]]]:
    associations: list[dict[str, Any]] = []
    adjacency: dict[str, set[str]] = {feature: set() for feature in features}
    for index, left in enumerate(features):
        for right in features[index + 1 :]:
            association = _feature_association(rows, left, right, minimum)
            if association is None:
                continue
            associations.append(association)
            spearman = association.get("spearman")
            if spearman is not None and abs(float(spearman)) >= threshold:
                adjacency[left].add(right)
                adjacency[right].add(left)
    clusters: list[list[str]] = []
    seen: set[str] = set()
    for feature in features:
        if feature in seen or not adjacency[feature]:
            continue
        stack = [feature]
        cluster: list[str] = []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            cluster.append(current)
            stack.extend(sorted(adjacency[current] - seen))
        if len(cluster) > 1:
            clusters.append(sorted(cluster))
    return associations, clusters


def _session(observed_ns: int) -> str:
    seconds = observed_ns // 1_000_000_000
    hour = (seconds // 3600) % 24
    if hour < 8:
        return "00-08"
    if hour < 16:
        return "08-16"
    return "16-24"


def _candidate_anchors(rows: Sequence[Mapping[str, Any]], symbol: str, sample_seconds: int) -> list[int]:
    times = [int(row["observed_at_ns"]) for row in rows if row.get("symbol") == symbol and _mid(row) is not None]
    if not times:
        return []
    step = sample_seconds * 1_000_000_000
    first = ((times[0] + step - 1) // step) * step
    last = times[-1]
    return list(range(first, last + 1, step))


def _latest_rows_by_type(rows: Sequence[Mapping[str, Any]], symbol: str) -> tuple[list[int], list[Mapping[str, Any]], list[int], list[Mapping[str, Any]]]:
    depth_times: list[int] = []
    depth_rows: list[Mapping[str, Any]] = []
    trade_times: list[int] = []
    trade_rows: list[Mapping[str, Any]] = []
    for row in rows:
        if row.get("symbol") != symbol:
            continue
        observed = int(row["observed_at_ns"])
        if row.get("event_type") == "depth":
            depth_times.append(observed)
            depth_rows.append(row)
        elif row.get("event_type") == "trade":
            trade_times.append(observed)
            trade_rows.append(row)
    return depth_times, depth_rows, trade_times, trade_rows


def _latest(times: Sequence[int], rows: Sequence[Mapping[str, Any]], anchor_ns: int) -> Mapping[str, Any] | None:
    index = _last_index_at_or_before(times, anchor_ns)
    return rows[index] if index is not None else None


def scan_market_state(
    features_path: str | Path,
    config: MarketStateScanConfig = MarketStateScanConfig(),
    *,
    batch_id: str | None = None,
) -> dict[str, Any]:
    if config.sample_seconds <= 0 or config.minimum_association_observations < 2:
        raise MarketStateScanError("sampling and association limits must be positive")
    if not 0 < config.redundancy_abs_spearman_threshold <= 1:
        raise MarketStateScanError("redundancy threshold must be in (0, 1]")
    rows = _load(features_path)
    symbol_times, symbol_mids, symbol_spreads, symbol_depths = _series(rows, config.symbol)
    btc_times, btc_mids, _, _ = _series(rows, config.context_symbol)
    if not symbol_times:
        raise MarketStateScanError(f"no valid BBO series for {config.symbol}")
    if not btc_times:
        raise MarketStateScanError(f"no valid BBO series for {config.context_symbol}")

    depth_times, depth_rows, trade_times, trade_rows = _latest_rows_by_type(rows, config.symbol)
    all_times = [int(row["observed_at_ns"]) for row in rows if row.get("symbol") == config.symbol]
    all_rows = [row for row in rows if row.get("symbol") == config.symbol]
    anchors = _candidate_anchors(rows, config.symbol, config.sample_seconds)
    observations: list[dict[str, Any]] = []

    for anchor_ns in anchors:
        row = _latest(all_times, all_rows, anchor_ns)
        if row is None:
            continue
        anchor_index = _last_index_at_or_before(symbol_times, anchor_ns)
        if anchor_index is None:
            continue
        anchor_mid = symbol_mids[anchor_index]
        current_spread = symbol_spreads[anchor_index]
        depth_row = _latest(depth_times, depth_rows, anchor_ns)
        trade_row = _latest(trade_times, trade_rows, anchor_ns)

        past_local = _past_window_metric(symbol_times, symbol_mids, anchor_ns, config.displacement_lookback_seconds)
        past_btc = _past_window_metric(btc_times, btc_mids, anchor_ns, config.displacement_lookback_seconds)
        local_return = _return_bps(past_local[0], anchor_mid) if past_local else None
        local_range = _range_bps(past_local)
        btc_anchor_index = _last_index_at_or_before(btc_times, anchor_ns)
        btc_anchor_mid = btc_mids[btc_anchor_index] if btc_anchor_index is not None else None
        btc_return = _return_bps(past_btc[0], btc_anchor_mid) if past_btc and btc_anchor_mid is not None else None
        book = _finite(row.get("book_imbalance_10"))
        micro = _micro_edge(row)
        depth_flow = _finite(depth_row.get("depth_flow_imbalance")) if depth_row else None
        flow_ratio = _flow_ratio(trade_row) if trade_row else None
        trade_count = _finite(trade_row.get("rolling_trade_count")) if trade_row else None
        trade_velocity = _finite(trade_row.get("trade_velocity_per_second")) if trade_row else None
        top_depth = _top_depth_notional(row)
        features = {
            "spread_bps": current_spread,
            "top_depth_notional": top_depth,
            "book_imbalance_10": book,
            "abs_book_imbalance_10": abs(book) if book is not None else None,
            "microprice_edge_spread_units": micro,
            "abs_microprice_edge_spread_units": abs(micro) if micro is not None else None,
            "depth_flow_imbalance": depth_flow,
            "abs_depth_flow_imbalance": abs(depth_flow) if depth_flow is not None else None,
            "flow_ratio_10s": flow_ratio,
            "abs_flow_ratio_10s": abs(flow_ratio) if flow_ratio is not None else None,
            "rolling_trade_count_10s": trade_count,
            "trade_velocity_per_second": trade_velocity,
            "local_return_15s_bps": local_return,
            "local_range_to_spread_15s": (local_range / current_spread if local_range is not None and current_spread > 0 else None),
            "btc_return_15s_bps": btc_return,
        }
        targets: dict[str, float | None] = {}

        for horizon in config.directionality_horizons_seconds:
            future = _future_window_metric(symbol_times, symbol_mids, anchor_ns, horizon)
            endpoint = _future_endpoint(symbol_times, symbol_mids, anchor_ns, horizon)
            targets[f"directionality_efficiency_{horizon}s"] = _directional_efficiency([anchor_mid, *future]) if future else None
            targets[f"signed_return_bps_{horizon}s"] = _return_bps(anchor_mid, endpoint) if endpoint is not None else None

        for horizon in config.volatility_horizons_seconds:
            future = _future_window_metric(symbol_times, symbol_mids, anchor_ns, horizon)
            past = _past_window_metric(symbol_times, symbol_mids, anchor_ns, horizon)
            future_range = _range_bps([anchor_mid, *future]) if future else None
            trailing_range = _range_bps(past) if past else None
            targets[f"future_range_bps_{horizon}s"] = future_range
            targets[f"future_realized_volatility_bps_{horizon}s"] = _realized_volatility_bps([anchor_mid, *future]) if future else None
            targets[f"volatility_expansion_ratio_{horizon}s"] = (
                future_range / trailing_range
                if future_range is not None and trailing_range is not None and trailing_range > 0
                else None
            )

        for horizon in config.liquidity_horizons_seconds:
            future_spreads = _future_window_metric(symbol_times, symbol_spreads, anchor_ns, horizon)
            past_spreads = _past_window_metric(symbol_times, symbol_spreads, anchor_ns, horizon)
            future_depth = _future_window_metric(symbol_times, symbol_depths, anchor_ns, horizon)
            future_spread = _mean_finite(future_spreads)
            past_spread = _mean_finite(past_spreads)
            targets[f"future_spread_bps_{horizon}s"] = future_spread
            targets[f"future_top_depth_notional_{horizon}s"] = _mean_finite(future_depth)
            targets[f"spread_expansion_ratio_{horizon}s"] = (
                future_spread / past_spread
                if future_spread is not None and past_spread is not None and past_spread > 0
                else None
            )

        past_displacement = _past_endpoint(symbol_times, symbol_mids, anchor_ns, config.displacement_lookback_seconds)
        past_move = _return_bps(past_displacement, anchor_mid) if past_displacement is not None else None
        for horizon in config.continuation_horizons_seconds:
            future = _future_window_metric(symbol_times, symbol_mids, anchor_ns, horizon)
            endpoint = _future_endpoint(symbol_times, symbol_mids, anchor_ns, horizon)
            future_return = _return_bps(anchor_mid, endpoint) if endpoint is not None else None
            targets[f"future_return_from_signal_mid_bps_{horizon}s"] = future_return
            if past_move is None or abs(past_move) < 1e-12 or not future:
                targets[f"continuation_fraction_{horizon}s"] = None
                targets[f"reversion_fraction_{horizon}s"] = None
            else:
                sign = 1.0 if past_move > 0 else -1.0
                displacements = [_return_bps(anchor_mid, value) for value in future]
                usable = [value for value in displacements if value is not None and abs(value) > 1e-12]
                if not usable:
                    targets[f"continuation_fraction_{horizon}s"] = None
                    targets[f"reversion_fraction_{horizon}s"] = None
                else:
                    targets[f"continuation_fraction_{horizon}s"] = sum(value * sign > 0 for value in usable) / len(usable)
                    targets[f"reversion_fraction_{horizon}s"] = sum(value * sign < 0 for value in usable) / len(usable)

        observations.append(
            {
                "batch_id": batch_id or Path(features_path).stem,
                "symbol": config.symbol,
                "observed_at_ns": anchor_ns,
                "utc_session": _session(anchor_ns),
                "features": features,
                "targets": targets,
            }
        )

    if not observations:
        raise MarketStateScanError("no sampled market-state observations")

    associations: list[dict[str, Any]] = []
    for feature in SIGNED_FEATURES:
        for horizon in sorted(set(config.directionality_horizons_seconds + config.continuation_horizons_seconds)):
            for target in (f"signed_return_bps_{horizon}s", f"future_return_from_signal_mid_bps_{horizon}s"):
                result = _association(observations, feature, target, config.minimum_association_observations)
                if result:
                    result["research_family"] = "signed_direction_or_continuation"
                    associations.append(result)
    for feature in MAGNITUDE_FEATURES:
        for horizon in config.directionality_horizons_seconds:
            result = _association(observations, feature, f"directionality_efficiency_{horizon}s", config.minimum_association_observations)
            if result:
                result["research_family"] = "directionality_vs_chop"
                associations.append(result)
        for horizon in config.volatility_horizons_seconds:
            for target in (f"future_range_bps_{horizon}s", f"volatility_expansion_ratio_{horizon}s"):
                result = _association(observations, feature, target, config.minimum_association_observations)
                if result:
                    result["research_family"] = "volatility_expansion_contraction"
                    associations.append(result)
    for feature in LIQUIDITY_FEATURES:
        for horizon in config.liquidity_horizons_seconds:
            for target in (f"future_spread_bps_{horizon}s", f"spread_expansion_ratio_{horizon}s"):
                result = _association(observations, feature, target, config.minimum_association_observations)
                if result:
                    result["research_family"] = "liquidity_stability_deterioration"
                    associations.append(result)

    all_features = tuple(dict.fromkeys((*SIGNED_FEATURES, *MAGNITUDE_FEATURES, *LIQUIDITY_FEATURES)))
    redundancy_pairs, redundancy_clusters = _redundancy_clusters(
        observations,
        all_features,
        config.minimum_association_observations,
        config.redundancy_abs_spearman_threshold,
    )
    associations.sort(key=lambda row: (row["research_family"], row["feature"], row["target"]))

    return {
        "schema_version": 1,
        "experiment": "regime_research_v1_market_state_scan",
        "symbol": config.symbol,
        "context_symbol": config.context_symbol,
        "batch_id": batch_id or Path(features_path).stem,
        "sampling": {
            "sample_seconds": config.sample_seconds,
            "observations": len(observations),
            "independent_batches": 1,
            "minimum_association_observations": config.minimum_association_observations,
        },
        "target_definitions": {
            "directionality": "future absolute endpoint movement divided by future realized mid-price range, plus signed endpoint return",
            "volatility": "future mid-price range and realized log-return variation relative to a same-horizon trailing causal range baseline",
            "liquidity": "future average spread and top-of-book depth plus future/trailing spread ratio",
            "continuation_reversion": "future path displacement relative to the prior 15-second displacement direction",
        },
        "feature_families": {
            "signed_features": list(SIGNED_FEATURES),
            "magnitude_features": list(MAGNITUDE_FEATURES),
            "liquidity_features": list(LIQUIDITY_FEATURES),
            "availability_note": "Only causal fields present in the captured public MEXC feature stream are evaluated; unavailable 15m/1h candle indicators are not invented.",
        },
        "associations": associations,
        "feature_redundancy": {
            "threshold_abs_spearman": config.redundancy_abs_spearman_threshold,
            "pairs": redundancy_pairs,
            "clusters": redundancy_clusters,
        },
        "observations": observations,
        "claims": {
            "market_state_first": True,
            "strategy_pnl_used": False,
            "single_batch_is_exploratory_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

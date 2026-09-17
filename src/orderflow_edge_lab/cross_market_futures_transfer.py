from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

from .cross_market_futures import extra_round_trip_friction_bps, futures_spec


@dataclass(frozen=True)
class FuturesTransferConfig:
    horizons_ms: tuple[int, ...] = (1_000, 5_000, 15_000, 30_000)
    extra_round_trip_ticks: tuple[float, ...] = (0.0, 1.0, 2.0)
    min_trade_count: int = 5
    min_flow_ratio: float = 0.25
    min_book_imbalance_10: float = 0.25
    min_microprice_edge: float = 0.20
    cooldown_ms: int = 2_000


@dataclass(frozen=True)
class TransferSignal:
    family: str
    side: int
    observed_at_ns: int
    bid: float
    ask: float
    flow_ratio: float | None
    book_imbalance_10: float | None
    microprice_edge: float | None


def _finite(value: object | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _side(value: float, threshold: float) -> int:
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0


def _flow_ratio(row: Mapping[str, object]) -> float | None:
    buy = _finite(row.get("rolling_buy_volume"))
    sell = _finite(row.get("rolling_sell_volume"))
    if buy is None or sell is None or buy < 0 or sell < 0 or buy + sell <= 0:
        return None
    return (buy - sell) / (buy + sell)


def _validate_rows(rows: Sequence[Mapping[str, object]]) -> None:
    prior: int | None = None
    for row in rows:
        observed = row.get("observed_at_ns")
        if isinstance(observed, bool):
            raise ValueError("observed_at_ns must be an integer")
        try:
            ts = int(observed)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("each feature row requires observed_at_ns") from exc
        if ts <= 0:
            raise ValueError("observed_at_ns must be positive")
        if prior is not None and ts < prior:
            raise ValueError("feature-row observation-time regression")
        prior = ts


def candidate_signals(
    rows: Sequence[Mapping[str, object]],
    cfg: FuturesTransferConfig = FuturesTransferConfig(),
) -> list[TransferSignal]:
    _validate_rows(rows)
    cooldown_ns = int(cfg.cooldown_ms) * 1_000_000
    last: dict[tuple[str, int], int] = {}
    out: list[TransferSignal] = []
    for row in rows:
        if str(row.get("event_type", "")).lower() != "trade":
            continue
        bid = _finite(row.get("best_bid"))
        ask = _finite(row.get("best_ask"))
        if bid is None or ask is None or not 0 < bid < ask:
            continue
        observed = int(row["observed_at_ns"])
        flow = _flow_ratio(row)
        book = _finite(row.get("book_imbalance_10"))
        micro = _finite(row.get("microprice_edge"))
        count = int(row.get("rolling_trade_count") or 0)
        candidates: list[tuple[str, int]] = []
        if count >= cfg.min_trade_count and flow is not None:
            candidates.append(("aggressive_flow_ratio", _side(flow, cfg.min_flow_ratio)))
        if book is not None:
            candidates.append(("book_imbalance_10", _side(book, cfg.min_book_imbalance_10)))
        if micro is not None:
            candidates.append(("microprice_normalized_edge", _side(micro, cfg.min_microprice_edge)))
        for family, side in candidates:
            if side == 0:
                continue
            key = (family, side)
            if observed - last.get(key, -10**30) < cooldown_ns:
                continue
            out.append(
                TransferSignal(
                    family=family,
                    side=side,
                    observed_at_ns=observed,
                    bid=bid,
                    ask=ask,
                    flow_ratio=flow,
                    book_imbalance_10=book,
                    microprice_edge=micro,
                )
            )
            last[key] = observed
    return out


def _quotes(rows: Sequence[Mapping[str, object]]) -> list[tuple[int, float, float]]:
    out: list[tuple[int, float, float]] = []
    for row in rows:
        if str(row.get("event_type", "")).lower() != "quote":
            continue
        bid = _finite(row.get("best_bid"))
        ask = _finite(row.get("best_ask"))
        if bid is None or ask is None or not 0 < bid < ask:
            continue
        out.append((int(row["observed_at_ns"]), bid, ask))
    return out


def _first_quote_at_or_after(
    quotes: Sequence[tuple[int, float, float]], target_ns: int
) -> tuple[int, float, float] | None:
    lo, hi = 0, len(quotes)
    while lo < hi:
        mid = (lo + hi) // 2
        if quotes[mid][0] < target_ns:
            lo = mid + 1
        else:
            hi = mid
    return quotes[lo] if lo < len(quotes) else None


def _path_return_bps(*, side: int, entry_bid: float, entry_ask: float, exit_bid: float, exit_ask: float) -> tuple[float, float]:
    if side > 0:
        entry, exit_ = entry_ask, exit_bid
    else:
        entry, exit_ = entry_bid, exit_ask
    return side * (exit_ / entry - 1.0) * 10_000.0, entry


def evaluate_feature_rows(
    feature_rows: Iterable[Mapping[str, object]],
    *,
    root: str,
    cfg: FuturesTransferConfig = FuturesTransferConfig(),
) -> dict[str, object]:
    """Evaluate frozen v1 transfer signals with executable BBO and native-tick stress.

    `gross_bps` already pays the observed spread because long paths enter ask and
    exit bid while short paths enter bid and exit ask. The 0/1/2 tick surface is
    an additional total round-trip stress. Commission/exchange fees are not
    silently set to zero; the report keeps them explicitly unresolved.
    """
    spec = futures_spec(root)
    rows = [dict(row) for row in feature_rows]
    _validate_rows(rows)
    signals = candidate_signals(rows, cfg)
    quotes = _quotes(rows)
    observations: list[dict[str, object]] = []

    for signal in signals:
        for horizon_ms in cfg.horizons_ms:
            target_ns = signal.observed_at_ns + int(horizon_ms) * 1_000_000
            exit_quote = _first_quote_at_or_after(quotes, target_ns)
            if exit_quote is None:
                continue
            exit_ns, exit_bid, exit_ask = exit_quote
            for control, path_side in (("original", signal.side), ("reversed_same_decision", -signal.side)):
                gross_bps, entry_price = _path_return_bps(
                    side=path_side,
                    entry_bid=signal.bid,
                    entry_ask=signal.ask,
                    exit_bid=exit_bid,
                    exit_ask=exit_ask,
                )
                for ticks in cfg.extra_round_trip_ticks:
                    extra_bps = extra_round_trip_friction_bps(
                        root=spec.root,
                        price=entry_price,
                        total_ticks=float(ticks),
                    )
                    observations.append(
                        {
                            "root": spec.root,
                            "family": signal.family,
                            "control": control,
                            "signal_side": signal.side,
                            "path_side": path_side,
                            "signal_observed_at_ns": signal.observed_at_ns,
                            "horizon_ms": int(horizon_ms),
                            "exit_observed_at_ns": exit_ns,
                            "entry_bid": signal.bid,
                            "entry_ask": signal.ask,
                            "exit_bid": exit_bid,
                            "exit_ask": exit_ask,
                            "gross_bps_after_observed_spread": gross_bps,
                            "extra_round_trip_ticks": float(ticks),
                            "extra_friction_bps": extra_bps,
                            "net_bps_before_commission": gross_bps - extra_bps,
                            "commission_exchange_fees_resolved": False,
                        }
                    )

    groups: dict[tuple[str, str, int, float], list[dict[str, object]]] = {}
    for row in observations:
        key = (
            str(row["family"]),
            str(row["control"]),
            int(row["horizon_ms"]),
            float(row["extra_round_trip_ticks"]),
        )
        groups.setdefault(key, []).append(row)
    summary: list[dict[str, object]] = []
    for (family, control, horizon, ticks), group in sorted(groups.items()):
        values = [float(x["net_bps_before_commission"]) for x in group]
        summary.append(
            {
                "family": family,
                "control": control,
                "horizon_ms": horizon,
                "extra_round_trip_ticks": ticks,
                "observations": len(values),
                "mean_net_bps_before_commission": sum(values) / len(values),
                "total_net_bps_before_commission": sum(values),
                "win_rate_before_commission": sum(v > 0 for v in values) / len(values),
            }
        )

    family_counts: dict[str, int] = {}
    for signal in signals:
        family_counts[signal.family] = family_counts.get(signal.family, 0) + 1
    eligibility = {
        "CMF-H1_aggressive_flow_ratio_observed": family_counts.get("aggressive_flow_ratio", 0) > 0,
        "CMF-H2_book_imbalance_10_observed": family_counts.get("book_imbalance_10", 0) > 0,
        "CMF-H3_microprice_normalized_edge_observed": family_counts.get("microprice_normalized_edge", 0) > 0,
        "H2_requires_true_top10_depth": True,
    }
    return {
        "research_id": "cross_market_futures_v1",
        "root": spec.root,
        "venue": spec.venue,
        "tick_size": spec.tick_size,
        "tick_value_usd": spec.tick_value_usd,
        "config": {
            "horizons_ms": list(cfg.horizons_ms),
            "extra_round_trip_ticks": list(cfg.extra_round_trip_ticks),
            "min_trade_count": cfg.min_trade_count,
            "min_flow_ratio": cfg.min_flow_ratio,
            "min_book_imbalance_10": cfg.min_book_imbalance_10,
            "min_microprice_edge": cfg.min_microprice_edge,
            "cooldown_ms": cfg.cooldown_ms,
        },
        "feature_rows": len(rows),
        "signals": len(signals),
        "signal_counts_by_family": family_counts,
        "hypothesis_observation_eligibility": eligibility,
        "summary": summary,
        "observations": observations,
        "unresolved_economics": {
            "commission_and_exchange_fees": True,
            "market_impact": True,
        },
        "claims": {
            "transfer_discovery_only": True,
            "persistent_edge_established": False,
            "candidate_promoted": False,
            "live_execution_supported": False,
            "leverage_supported": False,
        },
    }

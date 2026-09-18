from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
import math
import random
from typing import Iterable, Mapping, Sequence

from .cross_market_futures import extra_round_trip_friction_bps


PRIMARY_HORIZONS_MS = (1_000, 5_000, 15_000, 30_000)
PRIMARY_EXTRA_ROUND_TRIP_TICKS = 1.0
PLACEBO_SHIFTS_SECONDS = (-300, -60, 60, 300)
PLACEBO_MIN_COVERAGE = 0.80
MAX_QUOTE_AGE_NS = 1_000_000_000
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_917


def _finite(value: object | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _report_identity(record: Mapping[str, object]) -> tuple[str, str, str, str]:
    session_id = str(record.get("session_id", "")).strip()
    root = str(record.get("root", "")).strip().upper()
    native_contract = str(record.get("native_contract", "")).strip()
    report = record.get("report")
    if not session_id or not root or not native_contract or not isinstance(report, Mapping):
        raise ValueError("each aggregate record requires session_id, root, native_contract, and report")

    if str(report.get("research_id")) != "cross_market_futures_v1":
        raise ValueError("report research_id mismatch")
    if str(report.get("root", "")).upper() != root:
        raise ValueError("manifest/report root mismatch")
    source_sha = str(report.get("source_sha256", "")).strip()
    if not source_sha:
        raise ValueError("report requires source_sha256")

    native = report.get("native_contract_audit")
    if not isinstance(native, Mapping) or native.get("passed") is not True:
        raise ValueError("native contract audit must pass")
    symbols = native.get("symbols")
    if not isinstance(symbols, list) or symbols != [native_contract]:
        raise ValueError("manifest/native-contract audit mismatch")
    return session_id, root, native_contract, source_sha


def _composite_signals(record: Mapping[str, object]) -> list[dict[str, object]]:
    session_id, root, native_contract, source_sha = _report_identity(record)
    report = record["report"]
    assert isinstance(report, Mapping)
    observations = report.get("observations")
    if not isinstance(observations, list):
        raise ValueError("report observations must be a list")

    grouped: dict[tuple[str, int, int], dict[tuple[str, int], float]] = defaultdict(dict)
    sides: dict[tuple[str, int, int], int] = {}
    for row in observations:
        if not isinstance(row, Mapping):
            continue
        if _finite(row.get("extra_round_trip_ticks")) != PRIMARY_EXTRA_ROUND_TRIP_TICKS:
            continue
        family = str(row.get("family", ""))
        control = str(row.get("control", ""))
        if control not in {"original", "reversed_same_decision"}:
            continue
        try:
            signal_ts = int(row["signal_observed_at_ns"])
            horizon = int(row["horizon_ms"])
            signal_side = int(row["signal_side"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if horizon not in PRIMARY_HORIZONS_MS or signal_side not in (-1, 1):
            continue
        value = _finite(row.get("net_bps_before_commission"))
        if value is None:
            continue
        key = (family, signal_ts, signal_side)
        cell = (control, horizon)
        if cell in grouped[key]:
            raise ValueError("duplicate primary observation cell")
        grouped[key][cell] = value
        sides[key] = signal_side

    required = {
        (control, horizon)
        for control in ("original", "reversed_same_decision")
        for horizon in PRIMARY_HORIZONS_MS
    }
    output: list[dict[str, object]] = []
    for (family, signal_ts, signal_side), cells in sorted(grouped.items()):
        if set(cells) != required:
            continue
        original = [cells[("original", h)] for h in PRIMARY_HORIZONS_MS]
        reversed_ = [cells[("reversed_same_decision", h)] for h in PRIMARY_HORIZONS_MS]
        capture_key = f"{root}|{native_contract}|{session_id}"
        output.append(
            {
                "capture_key": capture_key,
                "session_id": session_id,
                "root": root,
                "native_contract": native_contract,
                "source_sha256": source_sha,
                "family": family,
                "signal_observed_at_ns": signal_ts,
                "signal_side": signal_side,
                "original_composite_net_bps": sum(original) / len(original),
                "reversed_composite_net_bps": sum(reversed_) / len(reversed_),
            }
        )
    return output


def _bootstrap_by_session(signals: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_session: dict[str, list[float]] = defaultdict(list)
    for row in signals:
        value = _finite(row.get("original_composite_net_bps"))
        if value is not None:
            by_session[str(row["capture_key"])].append(value)
    sessions = sorted(by_session)
    if len(sessions) < 5:
        return {
            "eligible": False,
            "sessions": len(sessions),
            "resamples": 0,
            "seed": BOOTSTRAP_SEED,
            "p02_5": None,
            "p50": None,
            "p97_5": None,
        }

    rng = random.Random(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        values: list[float] = []
        for _ in sessions:
            chosen = sessions[rng.randrange(len(sessions))]
            values.extend(by_session[chosen])
        draws.append(sum(values) / len(values))
    return {
        "eligible": True,
        "sessions": len(sessions),
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "p02_5": _quantile(draws, 0.025),
        "p50": _quantile(draws, 0.50),
        "p97_5": _quantile(draws, 0.975),
    }


def _family_d0(signals: Sequence[Mapping[str, object]]) -> dict[str, object]:
    original = [float(row["original_composite_net_bps"]) for row in signals]
    reversed_ = [float(row["reversed_composite_net_bps"]) for row in signals]
    sessions = {str(row["session_id"]) for row in signals}
    markets = {str(row["root"]) for row in signals}

    market_values: dict[str, list[float]] = defaultdict(list)
    for row in signals:
        market_values[str(row["root"])].append(float(row["original_composite_net_bps"]))
    market_stats = {
        market: {
            "signals": len(values),
            "mean_original_composite_net_bps": sum(values) / len(values),
            "total_original_composite_net_bps": sum(values),
        }
        for market, values in sorted(market_values.items())
    }
    positive_markets = [
        market for market, stats in market_stats.items()
        if float(stats["mean_original_composite_net_bps"]) > 0
    ]
    positive_totals = [
        max(0.0, float(stats["total_original_composite_net_bps"]))
        for stats in market_stats.values()
    ]
    positive_sum = sum(positive_totals)
    concentration = max(positive_totals) / positive_sum if positive_sum > 0 else None

    pooled = _mean(original)
    pooled_reversed = _mean(reversed_)
    gates = {
        "minimum_total_signals": len(signals) >= 100,
        "minimum_independent_capture_sessions": len(sessions) >= 5,
        "minimum_markets_with_signals": len(markets) >= 3,
        "pooled_net_expectancy_positive_after_one_extra_round_trip_tick": pooled is not None and pooled > 0,
        "original_must_beat_reversed_after_one_extra_round_trip_tick": (
            pooled is not None and pooled_reversed is not None and pooled > pooled_reversed
        ),
        "at_least_three_markets_same_direction_net_expectancy": len(positive_markets) >= 3,
        "single_market_positive_pnl_share_must_not_exceed": (
            concentration is not None and concentration <= 0.60
        ),
    }
    return {
        "eligible_composite_signals": len(signals),
        "independent_capture_sessions": len(sessions),
        "markets_with_signals": len(markets),
        "pooled_original_composite_net_bps": pooled,
        "pooled_reversed_composite_net_bps": pooled_reversed,
        "positive_markets": positive_markets,
        "single_market_positive_pnl_share": concentration,
        "market_stats": market_stats,
        "gates": gates,
        "d0_survives": all(gates.values()),
        "session_block_bootstrap": _bootstrap_by_session(signals),
    }


def _quotes(feature_rows: Iterable[Mapping[str, object]]) -> list[tuple[int, float, float]]:
    output: list[tuple[int, float, float]] = []
    for row in feature_rows:
        if str(row.get("event_type", "")).lower() != "quote":
            continue
        try:
            ts = int(row["observed_at_ns"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        bid = _finite(row.get("best_bid"))
        ask = _finite(row.get("best_ask"))
        if bid is None or ask is None or not 0 < bid < ask:
            continue
        output.append((ts, bid, ask))
    output.sort(key=lambda item: item[0])
    return output


def _entry_quote(
    quotes: Sequence[tuple[int, float, float]],
    timestamps: Sequence[int],
    target_ns: int,
) -> tuple[int, float, float] | None:
    index = bisect_right(timestamps, target_ns) - 1
    if index < 0:
        return None
    quote = quotes[index]
    if target_ns - quote[0] > MAX_QUOTE_AGE_NS:
        return None
    return quote


def _exit_quote(
    quotes: Sequence[tuple[int, float, float]],
    timestamps: Sequence[int],
    target_ns: int,
) -> tuple[int, float, float] | None:
    index = bisect_left(timestamps, target_ns)
    return quotes[index] if index < len(quotes) else None


def _path_net_bps(
    *,
    root: str,
    side: int,
    entry_bid: float,
    entry_ask: float,
    exit_bid: float,
    exit_ask: float,
) -> float:
    if side > 0:
        entry, exit_ = entry_ask, exit_bid
    else:
        entry, exit_ = entry_bid, exit_ask
    gross = side * (exit_ / entry - 1.0) * 10_000.0
    friction = extra_round_trip_friction_bps(
        root=root,
        price=entry,
        total_ticks=PRIMARY_EXTRA_ROUND_TRIP_TICKS,
    )
    return gross - friction


def _placebo_for_family(
    family_signals: Sequence[Mapping[str, object]],
    feature_rows_by_capture: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    original_count = len(family_signals)
    original_mean = _mean([
        float(row["original_composite_net_bps"]) for row in family_signals
    ])
    by_session: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in family_signals:
        by_session[str(row["capture_key"])].append(row)

    shift_results: list[dict[str, object]] = []
    for shift_seconds in PLACEBO_SHIFTS_SECONDS:
        values: list[float] = []
        for session_id, signals in by_session.items():
            feature_rows = feature_rows_by_capture.get(session_id)
            if feature_rows is None:
                continue
            quotes = _quotes(feature_rows)
            timestamps = [row[0] for row in quotes]
            if not quotes:
                continue
            for signal in signals:
                shifted_ns = int(signal["signal_observed_at_ns"]) + shift_seconds * 1_000_000_000
                entry = _entry_quote(quotes, timestamps, shifted_ns)
                if entry is None:
                    continue
                _, entry_bid, entry_ask = entry
                horizon_values: list[float] = []
                for horizon_ms in PRIMARY_HORIZONS_MS:
                    exit_ = _exit_quote(
                        quotes,
                        timestamps,
                        shifted_ns + horizon_ms * 1_000_000,
                    )
                    if exit_ is None:
                        horizon_values = []
                        break
                    _, exit_bid, exit_ask = exit_
                    horizon_values.append(
                        _path_net_bps(
                            root=str(signal["root"]),
                            side=int(signal["signal_side"]),
                            entry_bid=entry_bid,
                            entry_ask=entry_ask,
                            exit_bid=exit_bid,
                            exit_ask=exit_ask,
                        )
                    )
                if len(horizon_values) == len(PRIMARY_HORIZONS_MS):
                    values.append(sum(horizon_values) / len(horizon_values))
        coverage = len(values) / original_count if original_count else 0.0
        shift_results.append(
            {
                "shift_seconds": shift_seconds,
                "eligible_signals": len(values),
                "coverage_fraction": coverage,
                "interpretable": coverage >= PLACEBO_MIN_COVERAGE,
                "pooled_composite_net_bps": _mean(values),
            }
        )

    all_interpretable = bool(shift_results) and all(
        bool(row["interpretable"]) for row in shift_results
    )
    placebo_means = [
        float(row["pooled_composite_net_bps"])
        for row in shift_results
        if row["pooled_composite_net_bps"] is not None
    ]
    maximum = max(placebo_means) if placebo_means else None
    passed = (
        all_interpretable
        and original_mean is not None
        and maximum is not None
        and original_mean > maximum
    )
    return {
        "required_for_candidate_freeze": True,
        "original_eligible_signals": original_count,
        "original_pooled_composite_net_bps": original_mean,
        "minimum_shift_coverage_fraction": PLACEBO_MIN_COVERAGE,
        "shifts": shift_results,
        "all_shifts_interpretable": all_interpretable,
        "maximum_placebo_pooled_composite_net_bps": maximum,
        "passes_candidate_freeze_placebo": passed,
    }


def aggregate_d0(
    records: Sequence[Mapping[str, object]],
    *,
    feature_rows_by_capture: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    """Aggregate frozen cross-market futures v1 replay reports into family D0 gates."""
    seen_sha: set[str] = set()
    all_signals: list[dict[str, object]] = []
    identities: list[dict[str, str]] = []
    seen_session_root: set[tuple[str, str]] = set()

    for record in records:
        session_id, root, native_contract, source_sha = _report_identity(record)
        if source_sha in seen_sha:
            raise ValueError("duplicate source_sha256")
        seen_sha.add(source_sha)
        key = (session_id, root)
        if key in seen_session_root:
            raise ValueError("duplicate session/root record")
        seen_session_root.add(key)
        capture_key = f"{root}|{native_contract}|{session_id}"
        identities.append(
            {
                "capture_key": capture_key,
                "session_id": session_id,
                "root": root,
                "native_contract": native_contract,
                "source_sha256": source_sha,
            }
        )
        all_signals.extend(_composite_signals(record))

    families = sorted({str(row["family"]) for row in all_signals})
    results: dict[str, object] = {}
    for family in families:
        rows = [row for row in all_signals if row["family"] == family]
        result = _family_d0(rows)
        if feature_rows_by_capture is not None:
            result["time_shift_placebo"] = _placebo_for_family(
                rows, feature_rows_by_capture
            )
        else:
            result["time_shift_placebo"] = {
                "required_for_candidate_freeze": True,
                "status": "NOT_RUN_NO_FEATURE_ROWS",
                "passes_candidate_freeze_placebo": False,
            }
        result["candidate_freeze_eligible"] = bool(result["d0_survives"]) and bool(
            result["time_shift_placebo"].get("passes_candidate_freeze_placebo")
        )
        results[family] = result

    return {
        "research_id": "cross_market_futures_v1",
        "stage": "D0_TRANSFER_AGGREGATION",
        "primary_statistic": {
            "horizons_ms": list(PRIMARY_HORIZONS_MS),
            "extra_round_trip_ticks": PRIMARY_EXTRA_ROUND_TRIP_TICKS,
            "signal_composite": "equal_weight_mean_across_all_four_horizons",
            "complete_horizons_required": True,
        },
        "records": identities,
        "families": results,
        "unresolved_economics": {
            "commission_and_exchange_fees": True,
            "market_impact": True,
        },
        "claims": {
            "persistent_edge_established": False,
            "candidate_promoted": False,
            "live_execution_supported": False,
            "leverage_supported": False,
        },
    }

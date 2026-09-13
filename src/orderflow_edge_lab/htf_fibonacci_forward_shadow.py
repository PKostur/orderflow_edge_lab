from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.fibonacci_overlay import (
    directional_fib_depth,
    eligible_near_levels,
    gate_target_on_entry_transitions,
)
from orderflow_edge_lab.htf_trend_forward_shadow import (
    EIGHT_HOURS,
    HtfTrendForwardError,
    _candidate_params,
    _funding_between,
    _portfolio_stats,
    _symbol_trades,
    _utc,
    _validate_frame,
    verify_candidate_spec,
)
from orderflow_edge_lab.strategy_tournament import generate_target_position


def _overlay(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    overlay = candidate.get("fibonacci_overlay")
    if not isinstance(overlay, Mapping):
        raise HtfTrendForwardError("fibonacci overlay is missing")
    if overlay.get("mode") != "entry_transition_gate_only":
        raise HtfTrendForwardError("unsupported fibonacci overlay mode")
    levels = overlay.get("levels")
    if not isinstance(levels, list) or not levels:
        raise HtfTrendForwardError("fibonacci levels are missing")
    return overlay


def build_execution_targets(
    frame: pd.DataFrame,
    candidate: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
) -> pd.Series:
    """Build prospective Fib-gated positions from completed 8h bars only.

    The full warm-up history may define the causal swing anchor, but the overlay
    state is reset to flat at forward_signal_start_utc. A failed gate therefore
    cannot be inherited from development history or entered later without a new
    baseline transition.
    """
    if not verify_candidate_spec(candidate):
        raise HtfTrendForwardError("candidate specification hash is invalid")
    overlay = _overlay(candidate)
    as_of = _utc(as_of_utc)
    current_bar_start = as_of.floor("8h")
    start = _utc(candidate["forward_signal_start_utc"])
    clean = _validate_frame(frame, "symbol")
    closed = clean[clean.index < current_bar_start]
    if closed.empty:
        return pd.Series(dtype=float)

    raw_full = generate_target_position(
        closed, "ema_tsmom", _candidate_params(candidate)
    ).clip(-1.0, 1.0)
    depth = directional_fib_depth(
        closed,
        raw_full,
        lookback_bars=int(overlay["anchor_lookback_bars"]),
        minimum_impulse_atr=float(overlay["minimum_impulse_atr"]),
        atr_period=int(candidate["specification"]["atr_period"]),
    )
    forward_raw = raw_full[raw_full.index >= start]
    if forward_raw.empty:
        return pd.Series(dtype=float)
    eligible = eligible_near_levels(
        depth,
        [float(value) for value in overlay["levels"]],
        float(overlay["level_tolerance"]),
    )
    gated = gate_target_on_entry_transitions(forward_raw, eligible)
    executable = gated.copy()
    executable.index = executable.index + EIGHT_HOURS
    executable = executable[executable.index <= current_bar_start]
    executable.name = "target"
    return executable.astype(float)


def build_forward_report(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    candidate: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
    candidate_file_sha256: str | None = None,
    source_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not verify_candidate_spec(candidate):
        raise HtfTrendForwardError("candidate specification hash is invalid")
    overlay = _overlay(candidate)
    as_of = _utc(as_of_utc)
    spec = candidate["specification"]
    symbols = [str(value) for value in spec["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise HtfTrendForwardError(f"missing frozen symbols: {missing}")

    clean = {symbol: _validate_frame(frames[symbol], symbol) for symbol in symbols}
    current_bar_start = as_of.floor("8h")
    targets = {
        symbol: build_execution_targets(clean[symbol], candidate, as_of_utc=as_of)
        for symbol in symbols
    }
    execution_times = sorted(
        {ts for series in targets.values() for ts in series.index if ts <= current_bar_start}
    )
    cost_bps = float(spec["round_trip_cost_bps"])
    side_cost = cost_bps / 2.0 / 10_000.0
    previous_weights = pd.Series(0.0, index=symbols, dtype=float)
    interval_rows: list[dict[str, Any]] = []

    for i, ts in enumerate(execution_times):
        requested = pd.Series(
            {
                symbol: float(
                    targets[symbol].get(
                        ts,
                        previous_weights[symbol]
                        and math.copysign(1.0, previous_weights[symbol])
                        or 0.0,
                    )
                )
                for symbol in symbols
            },
            dtype=float,
        )
        active = int((requested != 0.0).sum())
        weights = requested / active if active else requested * 0.0
        turnover = float((weights - previous_weights).abs().sum())
        trading_cost = turnover * side_cost
        is_current = ts == current_bar_start
        end = (
            as_of
            if is_current
            else (
                execution_times[i + 1]
                if i + 1 < len(execution_times)
                else min(ts + EIGHT_HOURS, current_bar_start)
            )
        )
        if end <= ts:
            previous_weights = weights
            continue

        gross = 0.0
        funding_return = 0.0
        for symbol in symbols:
            weight = float(weights[symbol])
            if abs(weight) < 1e-15:
                continue
            frame = clean[symbol]
            if ts not in frame.index:
                raise HtfTrendForwardError(f"{symbol}: missing execution bar {ts}")
            entry_open = float(frame.loc[ts, "open"])
            if is_current:
                mark = float(frame.loc[ts, "close"])
            else:
                if end not in frame.index:
                    raise HtfTrendForwardError(f"{symbol}: missing next execution bar {end}")
                mark = float(frame.loc[end, "open"])
            gross += weight * (mark / entry_open - 1.0)
            funding_return += -weight * _funding_between(
                funding.get(symbol, pd.DataFrame()), ts, end
            )
        net = gross + funding_return - trading_cost
        interval_rows.append(
            {
                "start": ts.isoformat(),
                "end": end.isoformat(),
                "is_current_mark_to_market_interval": bool(is_current),
                "active_symbols": active,
                "gross_return": float(gross),
                "funding_return": float(funding_return),
                "turnover": turnover,
                "trading_cost_return": float(-trading_cost),
                "net_return": float(net),
            }
        )
        previous_weights = weights

    completed_trades: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    for symbol in symbols:
        trades, open_position = _symbol_trades(
            symbol,
            clean[symbol],
            targets[symbol],
            funding.get(symbol, pd.DataFrame()),
            cost_bps=cost_bps,
            as_of=as_of,
        )
        completed_trades.extend(trades)
        if open_position is not None:
            open_position["portfolio_weight"] = float(previous_weights.get(symbol, 0.0))
            open_positions.append(open_position)

    stats = _portfolio_stats(interval_rows)
    minimum = int(candidate["forward_protocol"]["minimum_completed_forward_trades_for_edge_review"])
    count = len(completed_trades)
    start = _utc(candidate["forward_signal_start_utc"])
    if as_of < start + EIGHT_HOURS:
        status = "waiting_for_first_executable_forward_signal"
    elif count >= minimum:
        status = "reviewable_trade_count_reached"
    else:
        status = "collecting"

    return {
        "schema_version": 1,
        "experiment": "htf-fibonacci-forward-shadow-v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_spec_sha256": candidate["spec_sha256"],
        "candidate_file_sha256": candidate_file_sha256,
        "source_sha256": dict(source_sha256 or {}),
        "as_of_utc": as_of.isoformat(),
        "forward_signal_start_utc": candidate["forward_signal_start_utc"],
        "status": status,
        "fibonacci_overlay": dict(overlay),
        "economics": {
            "round_trip_cost_bps": cost_bps,
            "funding": "actual public MEXC funding events",
            "gross_exposure_cap": float(spec["gross_portfolio_exposure_cap"]),
            "leverage": float(spec["leverage"]),
        },
        "metrics": {
            **stats,
            "completed_symbol_trades": count,
            "open_symbol_positions": len(open_positions),
            "minimum_completed_trades_for_edge_review": minimum,
        },
        "current_weights": {
            symbol: float(previous_weights[symbol]) for symbol in symbols
        },
        "completed_trades": sorted(
            completed_trades, key=lambda row: (row["exit_time"], row["symbol"])
        ),
        "open_positions": sorted(open_positions, key=lambda row: row["symbol"]),
        "portfolio_intervals": interval_rows,
        "claims": {
            "candidate_specification_frozen": True,
            "fibonacci_overlay_frozen": True,
            "paper_shadow_only": True,
            "forward_sample_minimum_reached": count >= minimum,
            "visible_forward_pnl_is_statistical_proof": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

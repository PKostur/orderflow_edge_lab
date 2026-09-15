from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_sectional_forward_shadow import (
    ONE_DAY,
    _funding_between as _xs_funding_between,
    _validate_frames as _validate_xs_frames,
    build_rebalance_weights,
)
from orderflow_edge_lab.ena_forward_shadow import build_forward_target
from orderflow_edge_lab.ena_mean_reversion_risk import _atr, _trade_stats, _validate_frame as _validate_ena_frame
from orderflow_edge_lab.htf_trend_forward_shadow import (
    EIGHT_HOURS,
    _funding_between as _trend_funding_between,
    _portfolio_stats,
    _symbol_trades,
    _validate_frame as _validate_trend_frame,
    build_execution_targets,
)
from orderflow_edge_lab.markov_price_diagnostics import (
    STATE_ORDER,
    MarkovStateSpec,
    build_price_states,
    fit_transition_matrix,
)


class MarkovEVShadowError(ValueError):
    pass


@dataclass(frozen=True)
class MarkovRewardFit:
    states: pd.DataFrame
    training_states: pd.DataFrame
    counts: pd.DataFrame
    transition: pd.DataFrame
    reward_bps: np.ndarray
    reward_se_bps: np.ndarray
    reward_observations: dict[str, int]


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _state_spec_from_config(config: Mapping[str, Any]) -> MarkovStateSpec:
    state = config["state_definition"]
    return MarkovStateSpec(
        direction_scale_lookback_bars=int(state["direction_scale_lookback_bars"]),
        direction_z_down_lt=float(state["direction_z_down_lt"]),
        direction_z_up_gt=float(state["direction_z_up_gt"]),
        volatility_short_lookback_bars=int(state["volatility_short_lookback_bars"]),
        volatility_long_lookback_bars=int(state["volatility_long_lookback_bars"]),
        volatility_ratio_low_lt=float(state["volatility_ratio_low_lt"]),
        volatility_ratio_high_gt=float(state["volatility_ratio_high_gt"]),
        transition_smoothing_alpha=float(state["transition_smoothing_alpha"]),
        minimum_state_transition_count_for_reliable_label=int(
            state["minimum_state_transition_count_for_reliable_label"]
        ),
    )


def fit_markov_reward(
    frame: pd.DataFrame,
    *,
    training_end_exclusive_utc: str,
    state_spec: MarkovStateSpec,
) -> MarkovRewardFit:
    states = build_price_states(frame, state_spec)
    cutoff = _utc(training_end_exclusive_utc)
    training = states.loc[states.index < cutoff].copy()
    if len(training) < state_spec.volatility_long_lookback_bars + 20:
        raise MarkovEVShadowError(f"insufficient pre-freeze states: {len(training)}")

    counts, transition = fit_transition_matrix(
        training["state"],
        alpha=state_spec.transition_smoothing_alpha,
    )
    work = training[["state", "log_return"]].copy()
    work["next_log_return"] = work["log_return"].shift(-1)
    global_sample = work["next_log_return"].dropna().to_numpy(dtype=float) * 10_000.0
    global_sd = float(np.std(global_sample, ddof=1)) if global_sample.size >= 2 else 100.0
    if not math.isfinite(global_sd) or global_sd <= 0:
        global_sd = 100.0

    rewards: list[float] = []
    ses: list[float] = []
    observations: dict[str, int] = {}
    for label in STATE_ORDER:
        sample = work.loc[work["state"] == label, "next_log_return"].dropna().to_numpy(dtype=float) * 10_000.0
        n = int(sample.size)
        observations[label] = n
        if n == 0:
            rewards.append(0.0)
            ses.append(global_sd)
            continue
        rewards.append(float(np.mean(sample)))
        if n >= 2:
            sd = float(np.std(sample, ddof=1))
            ses.append(sd / math.sqrt(n) if math.isfinite(sd) else global_sd)
        else:
            ses.append(global_sd)

    return MarkovRewardFit(
        states=states,
        training_states=training,
        counts=counts,
        transition=transition,
        reward_bps=np.asarray(rewards, dtype=float),
        reward_se_bps=np.asarray(ses, dtype=float),
        reward_observations=observations,
    )


def assess_entry(
    fit: MarkovRewardFit,
    *,
    state_timestamp_utc: str | pd.Timestamp,
    side: float,
    horizon_bars: int,
    round_trip_cost_bps: float,
    minimum_state_transitions: int,
    conservative_score_z: float,
) -> dict[str, Any]:
    if side not in (-1.0, 1.0):
        raise MarkovEVShadowError("side must be -1 or +1")
    if horizon_bars < 1:
        raise MarkovEVShadowError("horizon_bars must be positive")

    timestamp = _utc(state_timestamp_utc)
    eligible = fit.states.loc[fit.states.index <= timestamp]
    if eligible.empty:
        raise MarkovEVShadowError(f"no causal state available at {timestamp.isoformat()}")
    row = eligible.iloc[-1]
    state = str(row["state"])
    state_index = STATE_ORDER.index(state)
    transition_count = int(fit.counts.loc[state].sum())

    distribution = np.zeros(len(STATE_ORDER), dtype=float)
    distribution[state_index] = 1.0
    expected_bps = 0.0
    variance = 0.0
    for _ in range(int(horizon_bars)):
        expected_bps += float(distribution @ fit.reward_bps)
        variance += float(np.sum(np.square(distribution * fit.reward_se_bps)))
        distribution = distribution @ fit.transition.to_numpy(dtype=float)

    se_bps = math.sqrt(max(variance, 0.0))
    same_side_gross_bps = float(side * expected_bps)
    net_bps = same_side_gross_bps - float(round_trip_cost_bps)
    conservative_bps = net_bps - float(conservative_score_z) * se_bps
    adequate = transition_count >= int(minimum_state_transitions)
    passed = bool(adequate and conservative_bps > 0.0)
    return {
        "state_timestamp_utc": eligible.index[-1].isoformat(),
        "state": state,
        "state_transition_count": transition_count,
        "state_reliability": "adequate" if adequate else "sparse",
        "side": "long" if side > 0 else "short",
        "horizon_bars": int(horizon_bars),
        "expected_underlying_bps": float(expected_bps),
        "same_side_expected_gross_bps": same_side_gross_bps,
        "round_trip_cost_bps": float(round_trip_cost_bps),
        "expected_net_bps": float(net_bps),
        "approx_se_bps": float(se_bps),
        "conservative_score_bps": float(conservative_bps),
        "decision": "PASS" if passed else "VETO",
    }


def _filter_side_series(
    base: pd.Series,
    fit: MarkovRewardFit,
    *,
    execution_start: pd.Timestamp,
    signal_lag: pd.Timedelta,
    horizon_bars: int,
    round_trip_cost_bps: float,
    minimum_state_transitions: int,
    conservative_score_z: float,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    index = base.index[base.index >= execution_start]
    filtered = pd.Series(0.0, index=index, dtype=float)
    decisions: list[dict[str, Any]] = []
    current = 0.0
    vetoed_side = 0.0

    for ts in index:
        requested = float(base.loc[ts])
        requested = 1.0 if requested > 0 else (-1.0 if requested < 0 else 0.0)
        if vetoed_side and requested != vetoed_side:
            vetoed_side = 0.0
        if current != 0.0 and requested != current:
            current = 0.0
        if current == 0.0:
            if requested == 0.0:
                vetoed_side = 0.0
            elif requested == vetoed_side:
                pass
            else:
                decision = assess_entry(
                    fit,
                    state_timestamp_utc=ts - signal_lag,
                    side=requested,
                    horizon_bars=horizon_bars,
                    round_trip_cost_bps=round_trip_cost_bps,
                    minimum_state_transitions=minimum_state_transitions,
                    conservative_score_z=conservative_score_z,
                )
                decision.update({"execution_time": ts.isoformat(), "base_requested_side": requested})
                decisions.append(decision)
                if decision["decision"] == "PASS":
                    current = requested
                else:
                    vetoed_side = requested
        filtered.loc[ts] = current

    return filtered, decisions


def build_trend_shadow_report(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    base_candidate: Mapping[str, Any],
    clone: Mapping[str, Any],
    markov_config: Mapping[str, Any],
    ev_config: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    as_of = _utc(as_of_utc)
    start = _utc(clone["shadow_execution_start_utc"])
    spec = base_candidate["specification"]
    symbols = [str(x) for x in spec["symbols"]]
    clean = {s: _validate_trend_frame(frames[s], s) for s in symbols}
    state_spec = _state_spec_from_config(markov_config)
    policy = ev_config["reward_model"]
    horizon = int(clone["primary_horizon_bars"])
    cost_bps = float(policy["fresh_entry_round_trip_cost_bps"])
    minimum = int(policy["minimum_state_transition_count_for_actionable_label"])
    z = float(policy["conservative_score_z"])

    base_targets = {s: build_execution_targets(clean[s], base_candidate, as_of_utc=as_of) for s in symbols}
    execution_times = sorted({ts for series in base_targets.values() for ts in series.index if start <= ts <= as_of.floor("8h")})
    aligned_base = {
        s: base_targets[s].reindex(execution_times).ffill().fillna(0.0) if execution_times else pd.Series(dtype=float)
        for s in symbols
    }
    filtered_targets: dict[str, pd.Series] = {}
    decisions: list[dict[str, Any]] = []
    for symbol in symbols:
        fit = fit_markov_reward(
            clean[symbol],
            training_end_exclusive_utc=str(clone["training_end_exclusive_utc"]),
            state_spec=state_spec,
        )
        filtered, symbol_decisions = _filter_side_series(
            aligned_base[symbol],
            fit,
            execution_start=start,
            signal_lag=EIGHT_HOURS,
            horizon_bars=horizon,
            round_trip_cost_bps=cost_bps,
            minimum_state_transitions=minimum,
            conservative_score_z=z,
        )
        for item in symbol_decisions:
            item["symbol"] = symbol
        filtered_targets[symbol] = filtered
        decisions.extend(symbol_decisions)

    side_cost = float(spec["round_trip_cost_bps"]) / 2.0 / 10_000.0
    previous_weights = pd.Series(0.0, index=symbols, dtype=float)
    intervals: list[dict[str, Any]] = []
    for i, ts in enumerate(execution_times):
        base_requested = pd.Series({s: float(aligned_base[s].loc[ts]) for s in symbols})
        base_active = int((base_requested != 0.0).sum())
        sides = pd.Series({s: float(filtered_targets[s].loc[ts]) for s in symbols})
        weights = sides / base_active if base_active else sides * 0.0
        turnover = float((weights - previous_weights).abs().sum())
        trading_cost = turnover * side_cost
        current_bar_start = as_of.floor("8h")
        is_current = ts == current_bar_start
        end = as_of if is_current else (execution_times[i + 1] if i + 1 < len(execution_times) else min(ts + EIGHT_HOURS, current_bar_start))
        if end <= ts:
            previous_weights = weights
            continue
        gross = 0.0
        funding_return = 0.0
        for symbol in symbols:
            weight = float(weights[symbol])
            if abs(weight) < 1e-15:
                continue
            entry = float(clean[symbol].loc[ts, "open"])
            mark = float(clean[symbol].loc[ts, "close"]) if is_current else float(clean[symbol].loc[end, "open"])
            gross += weight * (mark / entry - 1.0)
            funding_return += -weight * _trend_funding_between(funding.get(symbol, pd.DataFrame()), ts, end)
        intervals.append({
            "start": ts.isoformat(), "end": end.isoformat(), "is_current_mark_to_market_interval": bool(is_current),
            "gross_return": float(gross), "funding_return": float(funding_return), "turnover": turnover,
            "trading_cost_return": float(-trading_cost), "net_return": float(gross + funding_return - trading_cost),
        })
        previous_weights = weights

    completed: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    for symbol in symbols:
        trades, opened = _symbol_trades(
            symbol, clean[symbol], filtered_targets[symbol], funding.get(symbol, pd.DataFrame()),
            cost_bps=float(spec["round_trip_cost_bps"]), as_of=as_of,
        )
        completed.extend(trades)
        if opened is not None:
            opened["portfolio_weight"] = float(previous_weights.get(symbol, 0.0))
            open_positions.append(opened)
    stats = _portfolio_stats(intervals)
    return {
        "schema_version": 1,
        "experiment": "markov-ev-shadow-trend-v1",
        "shadow_candidate_id": clone["shadow_candidate_id"],
        "base_candidate_id": clone["base_candidate_id"],
        "as_of_utc": as_of.isoformat(),
        "shadow_execution_start_utc": start.isoformat(),
        "status": "waiting_for_forward_start" if as_of < start else "collecting",
        "metrics": {**stats, "completed_symbol_trades": len(completed), "open_symbol_positions": len(open_positions),
                    "pass_count": sum(d["decision"] == "PASS" for d in decisions), "veto_count": sum(d["decision"] == "VETO" for d in decisions)},
        "current_weights": {s: float(previous_weights[s]) for s in symbols},
        "entry_decisions": sorted(decisions, key=lambda x: (x["execution_time"], x["symbol"])),
        "completed_trades": sorted(completed, key=lambda x: (x["exit_time"], x["symbol"])),
        "open_positions": sorted(open_positions, key=lambda x: x["symbol"]),
        "portfolio_intervals": intervals,
        "claims": {"paper_shadow_only": True, "base_candidate_modified": False, "markov_can_reverse": False,
                   "verified_out_of_sample_evidence": False, "profitable_edge_established": False,
                   "live_order_transmission_supported": False},
    }


def build_cross_sectional_shadow_report(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    base_candidate: Mapping[str, Any],
    clone: Mapping[str, Any],
    markov_config: Mapping[str, Any],
    ev_config: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    as_of = _utc(as_of_utc)
    start = _utc(clone["shadow_execution_start_utc"])
    spec = base_candidate["specification"]
    symbols = [str(x) for x in spec["symbols"]]
    clean, common = _validate_xs_frames(frames, symbols)
    state_spec = _state_spec_from_config(markov_config)
    policy = ev_config["reward_model"]
    horizon = int(clone["primary_horizon_bars"])
    cost_bps = float(policy["fresh_entry_round_trip_cost_bps"])
    minimum = int(policy["minimum_state_transition_count_for_actionable_label"])
    z = float(policy["conservative_score_z"])
    fits = {
        s: fit_markov_reward(clean[s], training_end_exclusive_utc=str(clone["training_end_exclusive_utc"]), state_spec=state_spec)
        for s in symbols
    }
    base_rebalances = build_rebalance_weights(clean, base_candidate, as_of_utc=as_of)
    filtered_rebalances: dict[pd.Timestamp, pd.Series] = {}
    decisions: list[dict[str, Any]] = []
    for ts, base_weights in sorted(base_rebalances.items()):
        if ts < start:
            continue
        filtered = pd.Series(0.0, index=symbols, dtype=float)
        for symbol in symbols:
            weight = float(base_weights[symbol])
            if abs(weight) < 1e-15:
                continue
            side = 1.0 if weight > 0 else -1.0
            decision = assess_entry(
                fits[symbol], state_timestamp_utc=ts - ONE_DAY, side=side, horizon_bars=horizon,
                round_trip_cost_bps=cost_bps, minimum_state_transitions=minimum, conservative_score_z=z,
            )
            decision.update({"symbol": symbol, "execution_time": ts.isoformat(), "base_weight": weight})
            decisions.append(decision)
            if decision["decision"] == "PASS":
                filtered[symbol] = weight
        filtered_rebalances[ts] = filtered

    side_cost = float(spec["round_trip_cost_bps"]) / 2.0 / 10_000.0
    weights = pd.Series(0.0, index=symbols, dtype=float)
    intervals: list[dict[str, Any]] = []
    rebalance_events: list[dict[str, Any]] = []
    first_exec = min(filtered_rebalances) if filtered_rebalances else None
    if first_exec is not None:
        day_starts = [ts for ts in common if first_exec <= ts <= as_of.floor("d")]
        for ts in day_starts:
            previous = weights.copy()
            if ts in filtered_rebalances:
                weights = filtered_rebalances[ts].copy()
                turnover = float((weights - previous).abs().sum())
                rebalance_events.append({"execution_time": ts.isoformat(), "turnover": turnover,
                                         "weights": {s: float(weights[s]) for s in symbols}})
            else:
                turnover = 0.0
            end = as_of if ts == as_of.floor("d") else ts + ONE_DAY
            if end <= ts:
                continue
            gross = 0.0
            funding_return = 0.0
            for symbol in symbols:
                weight = float(weights[symbol])
                if abs(weight) < 1e-15:
                    continue
                entry = float(clean[symbol].loc[ts, "open"])
                mark = float(clean[symbol].loc[ts, "close"]) if ts == as_of.floor("d") else float(clean[symbol].loc[end, "open"])
                gross += weight * (mark / entry - 1.0)
                funding_return += -weight * _xs_funding_between(funding.get(symbol, pd.DataFrame()), ts, end)
            trading_cost = turnover * side_cost
            intervals.append({"start": ts.isoformat(), "end": end.isoformat(),
                              "is_current_mark_to_market_interval": bool(ts == as_of.floor("d")),
                              "gross_return": float(gross), "funding_return": float(funding_return), "turnover": turnover,
                              "trading_cost_return": float(-trading_cost), "net_return": float(gross + funding_return - trading_cost)})

    returns = np.asarray([float(row["net_return"]) for row in intervals], dtype=float)
    if returns.size:
        equity = np.cumprod(1.0 + returns)
        peaks = np.maximum.accumulate(equity)
        net_return = float(equity[-1] - 1.0)
        max_drawdown = float(np.min(equity / peaks - 1.0))
    else:
        net_return = 0.0
        max_drawdown = 0.0
    return {
        "schema_version": 1, "experiment": "markov-ev-shadow-cross-sectional-v1",
        "shadow_candidate_id": clone["shadow_candidate_id"], "base_candidate_id": clone["base_candidate_id"],
        "as_of_utc": as_of.isoformat(), "shadow_execution_start_utc": start.isoformat(),
        "status": "waiting_for_forward_start" if as_of < start else "collecting",
        "metrics": {"net_return": net_return, "net_pnl_per_1000_usdt": net_return * 1000.0, "max_drawdown": max_drawdown,
                    "executed_rebalances": len(rebalance_events), "completed_holding_periods": max(0, len(rebalance_events) - 1),
                    "open_symbol_positions": int((weights.abs() > 1e-15).sum()),
                    "pass_count": sum(d["decision"] == "PASS" for d in decisions), "veto_count": sum(d["decision"] == "VETO" for d in decisions)},
        "current_weights": {s: float(weights[s]) for s in symbols}, "entry_decisions": decisions,
        "rebalance_events": rebalance_events, "portfolio_intervals": intervals,
        "claims": {"paper_shadow_only": True, "base_candidate_modified": False, "markov_can_reverse": False,
                   "weights_renormalized_after_veto": False, "verified_out_of_sample_evidence": False,
                   "profitable_edge_established": False, "live_order_transmission_supported": False},
    }


def build_ena_shadow_report(
    frame: pd.DataFrame,
    base_candidate: Mapping[str, Any],
    clone: Mapping[str, Any],
    markov_config: Mapping[str, Any],
    ev_config: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    clean = _validate_ena_frame(frame)
    as_of = _utc(as_of_utc)
    start = _utc(clone["shadow_execution_start_utc"])
    spec = base_candidate["specification"]
    state_spec = _state_spec_from_config(markov_config)
    fit = fit_markov_reward(clean, training_end_exclusive_utc=str(clone["training_end_exclusive_utc"]), state_spec=state_spec)
    policy = ev_config["reward_model"]
    horizon = int(clone["primary_horizon_bars"])
    cost_bps = float(policy["fresh_entry_round_trip_cost_bps"])
    minimum = int(policy["minimum_state_transition_count_for_actionable_label"])
    z = float(policy["conservative_score_z"])

    target = build_forward_target(clean, base_candidate)
    desired = target.shift(1).fillna(0.0).clip(-1.0, 1.0)
    signal_atr = _atr(clean, int(spec["atr_period"])).shift(1)
    stop_multiple = float(spec["hard_stop_atr_multiple"])
    cost_fraction = float(spec["round_trip_cost_bps"]) / 10_000.0
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    side = 0
    stop_locked_side = 0
    vetoed_side = 0
    entry_index: int | None = None
    entry_price: float | None = None
    atr_at_entry: float | None = None
    stop_price: float | None = None
    mae = 0.0
    mfe = 0.0

    def close_trade(exit_index: int, exit_price: float, reason: str) -> None:
        nonlocal side, entry_index, entry_price, atr_at_entry, stop_price, mae, mfe
        if side == 0 or entry_index is None or entry_price is None or atr_at_entry is None:
            raise MarkovEVShadowError("incomplete ENA shadow position")
        gross = side * (float(exit_price) / entry_price - 1.0)
        trades.append({"entry_time": clean.index[entry_index].isoformat(), "exit_time": clean.index[exit_index].isoformat(),
                       "side": "long" if side > 0 else "short", "entry_price": entry_price, "exit_price": float(exit_price),
                       "exit_reason": reason, "gross_return": float(gross), "net_return": float(gross - cost_fraction),
                       "atr_at_entry": atr_at_entry, "stop_price": stop_price, "mae_bps": float(mae * 10_000.0),
                       "mfe_bps": float(mfe * 10_000.0)})
        side = 0
        entry_index = None
        entry_price = None
        atr_at_entry = None
        stop_price = None
        mae = 0.0
        mfe = 0.0

    for index, (ts, row) in enumerate(clean.iterrows()):
        if ts < start:
            continue
        requested = int(desired.iloc[index])
        if stop_locked_side and requested != stop_locked_side:
            stop_locked_side = 0
        if vetoed_side and requested != vetoed_side:
            vetoed_side = 0
        if side and requested != side:
            previous_side = side
            close_trade(index, float(row["open"]), "signal_exit")
            if requested == -previous_side:
                stop_locked_side = 0
        if side == 0 and requested and requested != stop_locked_side and requested != vetoed_side:
            candidate_atr = signal_atr.iloc[index]
            if pd.notna(candidate_atr) and float(candidate_atr) > 0:
                decision = assess_entry(
                    fit, state_timestamp_utc=ts - pd.Timedelta(hours=1), side=float(requested), horizon_bars=horizon,
                    round_trip_cost_bps=cost_bps, minimum_state_transitions=minimum, conservative_score_z=z,
                )
                decision.update({"symbol": "ENA_USDT", "execution_time": ts.isoformat(), "base_requested_side": requested})
                decisions.append(decision)
                if decision["decision"] == "PASS":
                    side = requested
                    entry_index = index
                    entry_price = float(row["open"])
                    atr_at_entry = float(candidate_atr)
                    stop_price = entry_price - side * atr_at_entry * stop_multiple
                    mae = 0.0
                    mfe = 0.0
                else:
                    vetoed_side = requested
        if side == 0 or entry_price is None or atr_at_entry is None or stop_price is None:
            continue
        if side > 0:
            adverse = float(row["low"]) / entry_price - 1.0
            favorable = float(row["high"]) / entry_price - 1.0
            stop_hit = float(row["low"]) <= stop_price
        else:
            adverse = -(float(row["high"]) / entry_price - 1.0)
            favorable = -(float(row["low"]) / entry_price - 1.0)
            stop_hit = float(row["high"]) >= stop_price
        mae = min(mae, adverse)
        mfe = max(mfe, favorable)
        if stop_hit:
            exit_side = side
            close_trade(index, float(stop_price), "stop")
            stop_locked_side = exit_side

    open_position = None
    if side and entry_price is not None and entry_index is not None:
        mark = float(clean["close"].iloc[-1])
        gross = side * (mark / entry_price - 1.0)
        open_position = {"entry_time": clean.index[entry_index].isoformat(), "side": "long" if side > 0 else "short",
                         "entry_price": entry_price, "mark_price": mark, "unrealized_gross_return": float(gross),
                         "stop_price": stop_price, "mae_bps": float(mae * 10_000.0), "mfe_bps": float(mfe * 10_000.0)}
    stats = _trade_stats(trades)
    completed_pnl = float(stats.get("compounded_return") or 0.0) * 1000.0
    open_gross_pnl = float(open_position.get("unrealized_gross_return") or 0.0) * 1000.0 if open_position else 0.0
    return {
        "schema_version": 1, "experiment": "markov-ev-shadow-ena-v1",
        "shadow_candidate_id": clone["shadow_candidate_id"], "base_candidate_id": clone["base_candidate_id"],
        "as_of_utc": as_of.isoformat(), "shadow_execution_start_utc": start.isoformat(),
        "status": "waiting_for_forward_start" if as_of < start else "collecting",
        "metrics": {**stats, "open_positions": 1 if open_position else 0,
                    "forward_pnl_per_1000_usdt_completed_net_plus_open_gross": completed_pnl + open_gross_pnl,
                    "pass_count": sum(d["decision"] == "PASS" for d in decisions), "veto_count": sum(d["decision"] == "VETO" for d in decisions)},
        "entry_decisions": decisions, "completed_trades": trades, "open_position": open_position,
        "claims": {"paper_shadow_only": True, "base_candidate_modified": False, "markov_can_reverse": False,
                   "verified_out_of_sample_evidence": False, "profitable_edge_established": False,
                   "live_order_transmission_supported": False},
    }

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_evaluation import (
    cscv_pbo,
    deflated_sharpe_probability,
    moving_block_bootstrap_mean,
    sharpe_unannualized,
    white_style_reality_check,
)


class DiscoveryV2Sprint1Error(ValueError):
    pass


@dataclass(frozen=True)
class VariantRun:
    observations: pd.DataFrame
    contributions: pd.DataFrame


def _validate_price_frames(frames: Mapping[str, pd.DataFrame], symbols: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            raise DiscoveryV2Sprint1Error(f"missing price frame: {symbol}")
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise DiscoveryV2Sprint1Error(f"{symbol}: DatetimeIndex required")
        if not {"open", "close"}.issubset(frame.columns):
            raise DiscoveryV2Sprint1Error(f"{symbol}: open/close required")
        clean = frame.sort_index()
        if clean.index.has_duplicates:
            raise DiscoveryV2Sprint1Error(f"{symbol}: duplicate timestamps")
        opens[symbol] = pd.to_numeric(clean["open"], errors="coerce")
        closes[symbol] = pd.to_numeric(clean["close"], errors="coerce")
    open_frame = pd.concat(opens, axis=1, join="inner").dropna()
    close_frame = pd.concat(closes, axis=1, join="inner").dropna()
    idx = open_frame.index.intersection(close_frame.index).sort_values()
    open_frame = open_frame.loc[idx].astype(float)
    close_frame = close_frame.loc[idx].astype(float)
    if len(idx) < 100:
        raise DiscoveryV2Sprint1Error(f"insufficient aligned history: {len(idx)}")
    if (open_frame <= 0).any().any() or (close_frame <= 0).any().any():
        raise DiscoveryV2Sprint1Error("non-positive price")
    return open_frame, close_frame


def _funding_sum(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    mask = (rates.index > start) & (rates.index < end)
    return float(rates.loc[mask].sum())


def _rank_weights(scores: pd.Series, *, reverse: bool = False, quantile_fraction: float = 0.25) -> pd.Series:
    clean = pd.to_numeric(scores, errors="coerce").dropna().sort_values()
    if len(clean) < 4:
        raise DiscoveryV2Sprint1Error("at least four ranked symbols required")
    n_select = max(1, int(math.floor(len(clean) * float(quantile_fraction))))
    low = list(clean.index[:n_select])
    high = list(clean.index[-n_select:])
    out = pd.Series(0.0, index=scores.index, dtype=float)
    if reverse:
        out.loc[high] = 0.5 / len(high)
        out.loc[low] = -0.5 / len(low)
    else:
        out.loc[low] = 0.5 / len(low)
        out.loc[high] = -0.5 / len(high)
    return out


def _momentum_weights(scores: pd.Series, *, reverse: bool = False, quantile_fraction: float = 0.25) -> pd.Series:
    # Normal momentum is long high / short low. `_rank_weights` is reversal, so invert its normal result.
    return -_rank_weights(scores, reverse=reverse, quantile_fraction=quantile_fraction)


def _period_return(
    weights: pd.Series,
    previous_weights: pd.Series,
    opens: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    funding_frames: Mapping[str, pd.DataFrame] | None,
    side_cost_bps: float,
    *,
    force_liquidation: bool = False,
) -> tuple[float, float, dict[str, float]]:
    if start not in opens.index or end not in opens.index or end <= start:
        raise DiscoveryV2Sprint1Error("invalid execution period")
    price = opens.loc[end] / opens.loc[start] - 1.0
    contrib: dict[str, float] = {}
    gross = 0.0
    cost = 0.0
    for symbol in weights.index:
        w = float(weights[symbol])
        prev = float(previous_weights.get(symbol, 0.0))
        funding = _funding_sum(funding_frames.get(symbol) if funding_frames else None, start, end)
        leg_gross = w * (float(price[symbol]) - funding)
        leg_cost = abs(w - prev) * float(side_cost_bps) / 10_000.0
        if force_liquidation:
            leg_cost += abs(w) * float(side_cost_bps) / 10_000.0
        gross += leg_gross
        cost += leg_cost
        contrib[symbol] = leg_gross - leg_cost
    return float(gross), float(cost), contrib


def dispersion_conditioned_xs_momentum(
    frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    dispersion_lookback_days: int,
    momentum_lookback_days: int = 30,
    holding_days: int = 7,
    quantile_fraction: float = 0.25,
    side_cost_bps: float = 10.0,
    reverse: bool = False,
    ungated: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(frames, symbols)
    returns = closes.pct_change()
    dispersion = returns.std(axis=1, ddof=1)
    threshold = dispersion.shift(1).rolling(int(dispersion_lookback_days), min_periods=int(dispersion_lookback_days)).median()
    trailing = closes / closes.shift(int(momentum_lookback_days)) - 1.0
    signal_rows = list(range(int(momentum_lookback_days), len(closes), int(holding_days)))
    rows: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    previous = pd.Series(0.0, index=closes.columns, dtype=float)

    eligible: list[tuple[int, pd.Series]] = []
    for i in signal_rows:
        if i + 1 >= len(closes):
            continue
        if not ungated and not np.isfinite(float(threshold.iloc[i])):
            continue
        if trailing.iloc[i].isna().any():
            continue
        gate = True if ungated else bool(float(dispersion.iloc[i]) <= float(threshold.iloc[i]))
        if gate:
            target = _momentum_weights(trailing.iloc[i], reverse=reverse, quantile_fraction=quantile_fraction)
        else:
            target = pd.Series(0.0, index=closes.columns, dtype=float)
        eligible.append((i, target))

    for j, (signal_i, target) in enumerate(eligible):
        if j + 1 >= len(eligible):
            break
        next_signal_i = eligible[j + 1][0]
        start_i = signal_i + 1
        end_i = next_signal_i + 1
        if end_i >= len(opens):
            break
        start, end = opens.index[start_i], opens.index[end_i]
        force_liquidation = j + 2 >= len(eligible)
        gross, cost, legs = _period_return(
            target,
            previous,
            opens,
            start,
            end,
            funding_frames,
            side_cost_bps,
            force_liquidation=force_liquidation,
        )
        rows.append(
            {
                "timestamp": start,
                "end_timestamp": end,
                "gross_return_bps": gross * 10_000.0,
                "cost_bps": cost * 10_000.0,
                "net_return_bps": (gross - cost) * 10_000.0,
                "active_gross": float(target.abs().sum()),
            }
        )
        for symbol, value in legs.items():
            contributions.append({"timestamp": start, "symbol": symbol, "net_contribution_bps": value * 10_000.0})
        previous = target
    return VariantRun(pd.DataFrame(rows).set_index("timestamp"), pd.DataFrame(contributions))


def _next_index_after(index: pd.DatetimeIndex, timestamp: pd.Timestamp) -> pd.Timestamp | None:
    pos = int(index.searchsorted(timestamp, side="right"))
    if pos >= len(index):
        return None
    return index[pos]


def funding_extreme_reversal(
    hourly_frames: Mapping[str, pd.DataFrame],
    funding_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    lookback_settlements: int,
    z_threshold_abs: float = 2.0,
    round_trip_cost_bps: float = 20.0,
    reverse: bool = False,
) -> VariantRun:
    for symbol in symbols:
        if symbol not in hourly_frames or hourly_frames[symbol].empty:
            raise DiscoveryV2Sprint1Error(f"missing hourly frame: {symbol}")
        if symbol not in funding_frames or funding_frames[symbol].empty:
            raise DiscoveryV2Sprint1Error(f"missing funding history: {symbol}")
    event_union = sorted(set().union(*[set(funding_frames[s].index) for s in symbols]))
    rows: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []

    event_positions: dict[str, dict[pd.Timestamp, int]] = {}
    for symbol in symbols:
        event_positions[symbol] = {ts: i for i, ts in enumerate(funding_frames[symbol].index)}

    for event_time in event_union:
        active: list[tuple[str, float, pd.Timestamp, pd.Timestamp, float]] = []
        for symbol in symbols:
            frame = funding_frames[symbol]
            pos = event_positions[symbol].get(event_time)
            if pos is None or pos < int(lookback_settlements) or pos + 1 >= len(frame):
                continue
            current = float(frame["funding_rate"].iloc[pos])
            prior = pd.to_numeric(frame["funding_rate"].iloc[pos - int(lookback_settlements):pos], errors="coerce").dropna().to_numpy(dtype=float)
            if len(prior) != int(lookback_settlements):
                continue
            std = float(np.std(prior, ddof=1))
            if not math.isfinite(std) or std <= 0:
                continue
            z = (current - float(np.mean(prior))) / std
            if abs(z) < float(z_threshold_abs):
                continue
            side = -1.0 if z > 0 else 1.0
            if reverse:
                side *= -1.0
            next_settlement = frame.index[pos + 1]
            hourly = hourly_frames[symbol].sort_index()
            entry = _next_index_after(hourly.index, event_time)
            exit_ = _next_index_after(hourly.index, next_settlement)
            if entry is None or exit_ is None or exit_ <= entry:
                raise DiscoveryV2Sprint1Error(f"{symbol}: missing causal hourly execution around {event_time}")
            entry_px = float(hourly.loc[entry, "open"])
            exit_px = float(hourly.loc[exit_, "open"])
            next_rate = float(frame["funding_rate"].iloc[pos + 1])
            # Positive funding: long pays, short receives.
            leg_gross = side * (exit_px / entry_px - 1.0) - side * next_rate
            active.append((symbol, leg_gross, entry, exit_, side))

        if active:
            n = len(active)
            portfolio_gross = float(sum(item[1] for item in active) / n)
            portfolio_cost = float(round_trip_cost_bps) / 10_000.0
            rows.append(
                {
                    "timestamp": event_time,
                    "end_timestamp": max(item[3] for item in active),
                    "gross_return_bps": portfolio_gross * 10_000.0,
                    "cost_bps": float(round_trip_cost_bps),
                    "net_return_bps": (portfolio_gross - portfolio_cost) * 10_000.0,
                    "active_symbols": n,
                }
            )
            for symbol, leg_gross, _, _, _ in active:
                leg_net = leg_gross / n - portfolio_cost / n
                contributions.append({"timestamp": event_time, "symbol": symbol, "net_contribution_bps": leg_net * 10_000.0})
        else:
            rows.append(
                {
                    "timestamp": event_time,
                    "end_timestamp": event_time,
                    "gross_return_bps": 0.0,
                    "cost_bps": 0.0,
                    "net_return_bps": 0.0,
                    "active_symbols": 0,
                }
            )
    return VariantRun(pd.DataFrame(rows).set_index("timestamp"), pd.DataFrame(contributions))


def _ols_prediction(x_train: np.ndarray, y_train: np.ndarray, x_current: float) -> float:
    xmat = np.column_stack([np.ones(len(x_train)), x_train])
    coef, *_ = np.linalg.lstsq(xmat, y_train, rcond=None)
    return float(coef[0] + coef[1] * x_current)


def btc_residual_shock_reversal(
    frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    beta_lookback_days: int,
    quantile_fraction: float = 0.25,
    side_cost_bps: float = 10.0,
    reverse: bool = False,
    raw_return_control: bool = False,
) -> VariantRun:
    if "BTC_USDT" not in symbols:
        raise DiscoveryV2Sprint1Error("BTC_USDT is required as factor")
    opens, closes = _validate_price_frames(frames, symbols)
    returns = closes.pct_change()
    alts = [s for s in symbols if s != "BTC_USDT"]
    previous = pd.Series(0.0, index=closes.columns, dtype=float)
    rows: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    signals: list[tuple[int, pd.Series]] = []

    for i in range(int(beta_lookback_days) + 1, len(closes) - 1):
        btc_train = returns["BTC_USDT"].iloc[i - int(beta_lookback_days):i].to_numpy(dtype=float)
        btc_now = float(returns["BTC_USDT"].iloc[i])
        if not np.isfinite(btc_train).all() or not math.isfinite(btc_now):
            continue
        scores = pd.Series(index=alts, dtype=float)
        for symbol in alts:
            current = float(returns[symbol].iloc[i])
            if raw_return_control:
                scores[symbol] = current
                continue
            y_train = returns[symbol].iloc[i - int(beta_lookback_days):i].to_numpy(dtype=float)
            if not np.isfinite(y_train).all() or not math.isfinite(current):
                scores[symbol] = np.nan
                continue
            predicted = _ols_prediction(btc_train, y_train, btc_now)
            scores[symbol] = current - predicted
        if scores.dropna().size < 4:
            continue
        alt_weights = _rank_weights(scores, reverse=reverse, quantile_fraction=quantile_fraction)
        target = pd.Series(0.0, index=closes.columns, dtype=float)
        target.loc[alts] = alt_weights
        signals.append((i, target))

    for j, (signal_i, target) in enumerate(signals):
        start_i = signal_i + 1
        end_i = signal_i + 2
        if end_i >= len(opens):
            break
        start, end = opens.index[start_i], opens.index[end_i]
        force_liquidation = j + 1 >= len(signals)
        gross, cost, legs = _period_return(
            target,
            previous,
            opens,
            start,
            end,
            funding_frames,
            side_cost_bps,
            force_liquidation=force_liquidation,
        )
        rows.append(
            {
                "timestamp": start,
                "end_timestamp": end,
                "gross_return_bps": gross * 10_000.0,
                "cost_bps": cost * 10_000.0,
                "net_return_bps": (gross - cost) * 10_000.0,
                "active_gross": float(target.abs().sum()),
            }
        )
        for symbol, value in legs.items():
            if symbol == "BTC_USDT" and abs(value) <= 1e-15:
                continue
            contributions.append({"timestamp": start, "symbol": symbol, "net_contribution_bps": value * 10_000.0})
        previous = target
    return VariantRun(pd.DataFrame(rows).set_index("timestamp"), pd.DataFrame(contributions))


def _positive_share(values: pd.Series) -> float | None:
    positive = values[values > 0]
    total = float(positive.sum())
    if total <= 0 or positive.empty:
        return None
    return float(positive.max() / total)


def variant_summary(run: VariantRun, *, cost_multipliers: Sequence[float], bootstrap_cfg: Mapping[str, Any]) -> dict[str, Any]:
    obs = run.observations.copy()
    if obs.empty:
        raise DiscoveryV2Sprint1Error("variant has no observations")
    cases: dict[str, Any] = {}
    for multiplier in cost_multipliers:
        net = obs["gross_return_bps"].astype(float) - obs["cost_bps"].astype(float) * float(multiplier)
        cases[str(float(multiplier))] = {
            "mean_net_bps": float(net.mean()),
            "median_net_bps": float(net.median()),
            "positive_fraction": float((net > 0).mean()),
        }
    boot = moving_block_bootstrap_mean(
        obs["net_return_bps"].astype(float).to_numpy(),
        block_length=int(bootstrap_cfg["block_bootstrap_length"]),
        resamples=int(bootstrap_cfg["block_bootstrap_resamples"]),
        confidence=float(bootstrap_cfg["confidence_level"]),
    )
    contrib = run.contributions.copy()
    symbol_sums: dict[str, float] = {}
    loo: dict[str, float] = {}
    if not contrib.empty:
        grouped = contrib.groupby("symbol", observed=True)["net_contribution_bps"].sum().sort_values(ascending=False)
        symbol_sums = {str(k): float(v) for k, v in grouped.items()}
        pivot = contrib.pivot_table(index="timestamp", columns="symbol", values="net_contribution_bps", aggfunc="sum", fill_value=0.0)
        base = obs["net_return_bps"].astype(float)
        for symbol in pivot.columns:
            aligned = base.reindex(pivot.index).fillna(0.0) - pivot[symbol].astype(float)
            loo[str(symbol)] = float(aligned.mean())
    by_month = obs["net_return_bps"].groupby(obs.index.to_period("M")).sum().sort_values(ascending=False)
    positive_obs = obs.loc[obs["net_return_bps"] > 0, "net_return_bps"].sort_values(ascending=False)
    positive_total = float(positive_obs.sum())
    top5 = float(positive_obs.head(5).sum() / positive_total) if positive_total > 0 else None
    symbol_series = pd.Series(symbol_sums, dtype=float)
    return {
        "observations": int(len(obs)),
        "start": obs.index.min().isoformat(),
        "end": obs.index.max().isoformat(),
        "mean_gross_bps": float(obs["gross_return_bps"].mean()),
        "mean_cost_bps": float(obs["cost_bps"].mean()),
        "mean_net_bps": float(obs["net_return_bps"].mean()),
        "bootstrap_mean_bps": boot.mean,
        "bootstrap_lower_bps": boot.lower,
        "bootstrap_upper_bps": boot.upper,
        "cost_cases": cases,
        "per_symbol_sum_bps": symbol_sums,
        "best_symbol_positive_pnl_share": _positive_share(symbol_series) if not symbol_series.empty else None,
        "best_calendar_month_positive_pnl_share": _positive_share(by_month),
        "top5_positive_period_share": top5,
        "leave_one_symbol_out_mean_bps": loo,
        "minimum_leave_one_symbol_out_mean_bps": min(loo.values()) if loo else None,
    }


def _largest_positive_neighborhood(variant_ids: Sequence[str], summaries: Mapping[str, Mapping[str, Any]]) -> list[str]:
    best: list[str] = []
    current: list[str] = []
    for variant_id in variant_ids:
        value = float(summaries[variant_id]["cost_cases"]["1.5"]["mean_net_bps"])
        if value > 0:
            current.append(variant_id)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    return best


def _select_conservative_median(neighborhood: Sequence[str], ordered_ids: Sequence[str]) -> str | None:
    if not neighborhood:
        return None
    positions = sorted(ordered_ids.index(v) for v in neighborhood)
    # Upper median -> longer/more conservative lookback for the preregistered ascending lists.
    return ordered_ids[positions[len(positions) // 2]]


def evaluate_family(
    variants: Mapping[str, VariantRun],
    controls: Mapping[str, VariantRun],
    *,
    ordered_variant_ids: Sequence[str],
    evaluation_config: Mapping[str, Any],
    principal_control_for_variant: Mapping[str, str],
) -> dict[str, Any]:
    if list(variants) != list(ordered_variant_ids):
        missing = [v for v in ordered_variant_ids if v not in variants]
        if missing:
            raise DiscoveryV2Sprint1Error(f"missing variants: {missing}")
    stats_cfg = evaluation_config["statistics"]
    econ_cfg = evaluation_config["economics"]
    conc_cfg = evaluation_config["concentration"]
    summaries = {
        variant_id: variant_summary(
            variants[variant_id],
            cost_multipliers=econ_cfg["cost_multipliers"],
            bootstrap_cfg=stats_cfg,
        )
        for variant_id in ordered_variant_ids
    }
    control_summaries = {
        control_id: variant_summary(run, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
        for control_id, run in controls.items()
    }

    aligned = pd.concat(
        [variants[v].observations["net_return_bps"].rename(v) for v in ordered_variant_ids],
        axis=1,
        join="inner",
    ).dropna()
    family_stats: dict[str, Any] = {"aligned_observations": int(len(aligned))}
    if len(aligned) >= int(stats_cfg["cscv_partitions"]) and aligned.shape[1] >= int(stats_cfg["minimum_variants_for_pbo"]):
        sharpes = [sharpe_unannualized(aligned[col].to_numpy()) for col in aligned.columns]
        diagnostic_reference = str(aligned.mean().idxmax())
        family_stats.update(
            {
                "diagnostic_reference_variant": diagnostic_reference,
                "deflated_sharpe": deflated_sharpe_probability(aligned[diagnostic_reference].to_numpy(), sharpes),
                "pbo_cscv": cscv_pbo(aligned, partitions=int(stats_cfg["cscv_partitions"])),
                "reality_check": white_style_reality_check(
                    aligned,
                    block_length=int(stats_cfg["block_bootstrap_length"]),
                    resamples=int(stats_cfg["block_bootstrap_resamples"]),
                ),
            }
        )
    else:
        family_stats["status"] = "insufficient_aligned_observations_for_family_selection_diagnostics"

    baseline_positive = [v for v in ordered_variant_ids if float(summaries[v]["cost_cases"]["1.0"]["mean_net_bps"]) > 0]
    neighborhood = _largest_positive_neighborhood(ordered_variant_ids, summaries)
    selected = _select_conservative_median(neighborhood, list(ordered_variant_ids)) if len(neighborhood) >= 2 else None
    median_candidate_mean = float(np.median([float(summaries[v]["mean_net_bps"]) for v in ordered_variant_ids]))
    control_advantage = None
    control_ok = False
    concentration_ok = False
    selected_control = None
    if selected is not None:
        selected_control = principal_control_for_variant[selected]
        if selected_control not in control_summaries:
            raise DiscoveryV2Sprint1Error(f"missing principal control: {selected_control}")
        control_mean = float(control_summaries[selected_control]["mean_net_bps"])
        control_advantage = median_candidate_mean - control_mean
        control_ok = control_advantage >= 5.0
        sel = summaries[selected]
        loo_min = sel["minimum_leave_one_symbol_out_mean_bps"]
        concentration_ok = loo_min is not None and float(loo_min) > 0
        for value_key, threshold_key in (
            ("best_symbol_positive_pnl_share", "maximum_best_symbol_positive_pnl_share"),
            ("best_calendar_month_positive_pnl_share", "maximum_best_calendar_month_positive_pnl_share"),
            ("top5_positive_period_share", "maximum_top5_positive_pnl_share"),
        ):
            value = sel[value_key]
            if value is not None and float(value) > float(conc_cfg[threshold_key]):
                concentration_ok = False

    hard_checks = {
        "variant_breadth_3_of_4_positive_baseline": len(baseline_positive) >= 3,
        "contiguous_two_positive_at_1_5x": len(neighborhood) >= 2,
        "reversed_control_weaker_by_at_least_5bps": control_ok,
        "selected_variant_concentration_pass": concentration_ok,
    }
    state = "REPLICATION_PENDING" if selected is not None and all(hard_checks.values()) else "FALSIFIED"
    return {
        "state": state,
        "selected_variant_if_survived": selected if state == "REPLICATION_PENDING" else None,
        "stable_neighborhood": neighborhood,
        "baseline_positive_variants": baseline_positive,
        "median_candidate_mean_net_bps": median_candidate_mean,
        "selected_principal_control": selected_control,
        "control_advantage_bps": control_advantage,
        "hard_checks": hard_checks,
        "variant_summaries": summaries,
        "control_summaries": control_summaries,
        "family_selection_diagnostics": family_stats,
        "claims": {
            "d0_result_establishes_edge": False,
            "replication_pending_means_validated": False,
            "live_eligible": False,
        },
    }

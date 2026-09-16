from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames, variant_summary
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals
from orderflow_edge_lab.discovery_v2_sprint8 import _wilder_adx


class DiscoveryV2Sprint11Error(ValueError):
    pass


def _quality_spread(scores: pd.Series) -> float:
    clean = pd.to_numeric(scores, errors="coerce").dropna()
    if len(clean) < 6:
        return float("nan")
    return float(clean.quantile(0.80) - clean.quantile(0.20))


def _prior_quality_threshold(history: list[float], *, history_days: int, percentile: float) -> float:
    valid = [float(x) for x in history if np.isfinite(x)]
    if len(valid) < int(history_days):
        return float("nan")
    return float(np.quantile(np.asarray(valid[-int(history_days):], dtype=float), float(percentile)))


def _zero(columns: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=columns, dtype=float)


def _target(scores: pd.Series, columns: pd.Index, *, reverse: bool) -> pd.Series:
    if pd.to_numeric(scores, errors="coerce").notna().sum() < 6:
        return _zero(columns)
    return _rank(scores, long_high=not bool(reverse)).reindex(columns, fill_value=0.0)


def selective_trend_acceleration_5d(
    daily_frames,
    *,
    symbols: Sequence[str],
    funding_frames,
    quality_history_days: int,
    quality_percentile: float,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
    selective: bool = True,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    adx = _wilder_adx(daily_frames["BTC_USDT"], 14).reindex(opens.index)
    qualities: list[float] = []
    signals: list[tuple[int, int, pd.Series]] = []
    n = 5
    for i in range(int(common_warmup_days), len(opens) - 2):
        recent = ret.iloc[i - n + 1:i + 1].sum(axis=0, min_count=n)
        previous = ret.iloc[i - 2 * n + 1:i - n + 1].sum(axis=0, min_count=n)
        scores = (recent - previous).replace([np.inf, -np.inf], np.nan)
        quality = _quality_spread(scores)
        threshold = _prior_quality_threshold(
            qualities, history_days=int(quality_history_days), percentile=float(quality_percentile)
        )
        trend_ok = bool(np.isfinite(float(adx.iloc[i])) and float(adx.iloc[i]) >= 25.0)
        quality_ok = bool(np.isfinite(quality) and np.isfinite(threshold) and quality > threshold)
        base = _target(scores, opens.columns, reverse=reverse)
        active = trend_ok and (quality_ok if selective else True)
        signals.append((i + 1, i + 2, base if active else _zero(opens.columns)))
        qualities.append(quality)
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def selective_low_skew_90d(
    daily_frames,
    *,
    symbols: Sequence[str],
    funding_frames,
    quality_history_days: int,
    quality_percentile: float,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
    selective: bool = True,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    qualities: list[float] = []
    signals: list[tuple[int, int, pd.Series]] = []
    n = 90
    for i in range(int(common_warmup_days), len(opens) - 2):
        window = ret.iloc[i - n + 1:i + 1]
        scores = (-window.skew(axis=0)).replace([np.inf, -np.inf], np.nan)
        quality = _quality_spread(scores)
        threshold = _prior_quality_threshold(
            qualities, history_days=int(quality_history_days), percentile=float(quality_percentile)
        )
        quality_ok = bool(np.isfinite(quality) and np.isfinite(threshold) and quality > threshold)
        base = _target(scores, opens.columns, reverse=reverse)
        active = quality_ok if selective else True
        signals.append((i + 1, i + 2, base if active else _zero(opens.columns)))
        qualities.append(quality)
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def selective_funding_carry_14d(
    daily_frames,
    *,
    symbols: Sequence[str],
    funding_frames,
    quality_history_days: int,
    quality_percentile: float,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
    selective: bool = True,
) -> VariantRun:
    opens, _ = _validate_price_frames(daily_frames, symbols)
    qualities: list[float] = []
    signals: list[tuple[int, int, pd.Series]] = []
    n = 14
    for i in range(int(common_warmup_days), len(opens) - 2):
        execution_ts = opens.index[i + 1]
        lower = execution_ts - pd.Timedelta(days=n)
        scores = pd.Series(np.nan, index=opens.columns, dtype=float)
        for symbol in opens.columns:
            frame = funding_frames.get(symbol)
            if frame is None or frame.empty or "funding_rate" not in frame.columns:
                continue
            rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
            recent = rates.loc[(rates.index >= lower) & (rates.index < execution_ts)]
            if recent.empty:
                continue
            scores.loc[symbol] = -float(recent.sum()) / float(n)
        quality = _quality_spread(scores)
        threshold = _prior_quality_threshold(
            qualities, history_days=int(quality_history_days), percentile=float(quality_percentile)
        )
        quality_ok = bool(np.isfinite(quality) and np.isfinite(threshold) and quality > threshold)
        base = _target(scores, opens.columns, reverse=reverse)
        active = quality_ok if selective else True
        signals.append((i + 1, i + 2, base if active else _zero(opens.columns)))
        qualities.append(quality)
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def _active_period_returns(run: VariantRun, *, cost_multiplier: float = 1.0) -> pd.Series:
    obs = run.observations.copy()
    active = pd.to_numeric(obs["active_gross"], errors="coerce").fillna(0.0) > 0.0
    net = pd.to_numeric(obs["gross_return_bps"], errors="coerce") - pd.to_numeric(obs["cost_bps"], errors="coerce") * float(cost_multiplier)
    values: list[float] = []
    index: list[pd.Timestamp] = []
    for i in range(len(obs)):
        if not bool(active.iloc[i]):
            continue
        value = float(net.iloc[i])
        if i + 1 < len(obs) and not bool(active.iloc[i + 1]):
            # Attribute the explicit transition-to-cash cost to the setup that caused it.
            value += float(net.iloc[i + 1])
        values.append(value)
        index.append(pd.Timestamp(obs.index[i]))
    return pd.Series(values, index=pd.DatetimeIndex(index), dtype=float)


def evaluate_selective_family(
    candidate: VariantRun,
    reversed_same_gate: VariantRun,
    ungated_parent: VariantRun,
    *,
    evaluation_config: Mapping[str, Any],
    gate: Mapping[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    stats_cfg = evaluation_config["statistics"]
    econ_cfg = evaluation_config["economics"]
    summary = variant_summary(candidate, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    reverse_summary = variant_summary(reversed_same_gate, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    parent_summary = variant_summary(ungated_parent, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)

    active = _active_period_returns(candidate, cost_multiplier=1.0)
    reverse_active = _active_period_returns(reversed_same_gate, cost_multiplier=1.0)
    parent_active = _active_period_returns(ungated_parent, cost_multiplier=1.0)
    active_mean = float(active.mean()) if len(active) else float("nan")
    reverse_active_mean = float(reverse_active.mean()) if len(reverse_active) else float("nan")
    parent_active_mean = float(parent_active.mean()) if len(parent_active) else float("nan")
    reverse_advantage = active_mean - reverse_active_mean
    parent_advantage = active_mean - parent_active_mean

    checks = {
        "minimum_active_periods": len(active) >= int(gate["minimum_active_periods"]),
        "calendar_day_mean_positive": float(summary["mean_net_bps"]) > 0.0,
        "calendar_day_mean_positive_at_1_5x": float(summary["cost_cases"]["1.5"]["mean_net_bps"]) > 0.0,
        "active_day_mean_above_floor": np.isfinite(active_mean) and active_mean >= float(gate["minimum_active_day_mean_net_bps"]),
        "beats_reversed_same_gate": np.isfinite(reverse_advantage) and reverse_advantage >= float(gate["minimum_active_day_advantage_vs_reversed_same_gate_bps"]),
        "beats_ungated_parent": np.isfinite(parent_advantage) and parent_advantage >= float(gate["minimum_active_day_advantage_vs_ungated_parent_bps"]),
        "best_symbol_share": summary["best_symbol_positive_pnl_share"] is not None and float(summary["best_symbol_positive_pnl_share"]) <= float(gate["maximum_best_symbol_positive_pnl_share"]),
        "best_month_share": summary["best_calendar_month_positive_pnl_share"] is not None and float(summary["best_calendar_month_positive_pnl_share"]) <= float(gate["maximum_best_calendar_month_positive_pnl_share"]),
        "top5_share": summary["top5_positive_period_share"] is not None and float(summary["top5_positive_period_share"]) <= float(gate["maximum_top5_positive_period_share"]),
    }
    passed = all(bool(v) for v in checks.values())
    return {
        "state": "RESEARCH_CANDIDATE_FREEZE_PENDING" if passed else "FALSIFIED",
        "candidate_id_if_passed": candidate_id if passed else None,
        "hard_checks": checks,
        "candidate_summary": summary,
        "reversed_same_gate_summary": reverse_summary,
        "ungated_parent_summary": parent_summary,
        "selectivity": {
            "active_periods": int(len(active)),
            "calendar_periods": int(len(candidate.observations)),
            "active_fraction": float(len(active) / len(candidate.observations)) if len(candidate.observations) else None,
            "active_period_mean_net_bps_including_exit_to_cash_cost": active_mean,
            "reversed_same_gate_active_period_mean_net_bps": reverse_active_mean,
            "ungated_parent_active_period_mean_net_bps": parent_active_mean,
            "active_period_advantage_vs_reversed_bps": reverse_advantage,
            "active_period_advantage_vs_ungated_parent_bps": parent_advantage,
        },
        "d0_diagnostics_not_hard_gates": {
            "bootstrap_lower_bps": summary["bootstrap_lower_bps"],
            "minimum_leave_one_symbol_out_mean_bps": summary["minimum_leave_one_symbol_out_mean_bps"],
        },
        "claims": {
            "research_candidate_is_validated_edge": False,
            "live_eligible": False,
            "leverage_eligible": False,
        },
    }

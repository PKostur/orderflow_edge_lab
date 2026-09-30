from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, variant_summary
from orderflow_edge_lab.discovery_v2_sprint2 import _simulate_signals
from orderflow_edge_lab.discovery_v2_sprint11 import _active_period_returns
from orderflow_edge_lab.discovery_v2_sprint12 import _build_primary_setups, _zero


@dataclass(frozen=True)
class PayoffMetaRun:
    candidate: VariantRun
    reversed_same_decisions: VariantRun
    ungated_parent: VariantRun
    anti_meta: VariantRun
    predictions: pd.DataFrame


def _model(alpha: float) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=float(alpha), fit_intercept=True)),
        ]
    )


def run_payoff_meta(
    daily_frames,
    *,
    symbols: Sequence[str],
    funding_frames,
    side_cost_bps: float,
    ridge_alpha: float = 10.0,
    training_window: int = 80,
    minimum_training: int = 60,
    trade_threshold_bps: float = 0.0,
) -> PayoffMetaRun:
    opens, _, records = _build_primary_setups(
        "meta_trend_acceleration_5d",
        daily_frames,
        symbols=symbols,
        funding_frames=funding_frames,
        side_cost_bps=side_cost_bps,
    )
    rows: list[dict[str, Any]] = []
    first_decision_signal_i: int | None = None
    for current in records:
        prior = [r for r in records if pd.Timestamp(r["end_timestamp"]) < pd.Timestamp(current["start_timestamp"])]
        prior = prior[-int(training_window) :]
        prediction = float("nan")
        if len(prior) >= int(minimum_training):
            x_train = np.vstack([r["features"] for r in prior])
            y_train = np.asarray([r["standalone_label_bps"] for r in prior], dtype=float)
            m = _model(float(ridge_alpha))
            m.fit(x_train, y_train)
            prediction = float(m.predict(np.asarray(current["features"], dtype=float).reshape(1, -1))[0])
        trade = bool(np.isfinite(prediction) and prediction > float(trade_threshold_bps))
        anti_trade = bool(np.isfinite(prediction) and prediction < float(trade_threshold_bps))
        if np.isfinite(prediction) and first_decision_signal_i is None:
            first_decision_signal_i = int(current["signal_i"])
        rows.append(
            {
                "signal_timestamp": current["signal_timestamp"],
                "start_timestamp": current["start_timestamp"],
                "end_timestamp": current["end_timestamp"],
                "signal_i": int(current["signal_i"]),
                "predicted_standalone_net_bps": prediction,
                "trade": trade,
                "anti_trade": anti_trade,
                "standalone_label_bps": float(current["standalone_label_bps"]),
                "target": current["target"],
                "reversed_target": current["reversed_target"],
            }
        )
    if first_decision_signal_i is None:
        raise ValueError("frozen payoff model never had enough strictly prior labeled setups")
    by_i = {int(r["signal_i"]): r for r in rows}
    candidate_signals = []
    reverse_signals = []
    parent_signals = []
    anti_signals = []
    for i in range(first_decision_signal_i, len(opens) - 2):
        row = by_i.get(i)
        zero = _zero(opens.columns)
        if row is None:
            candidate = reverse = parent = anti = zero
        else:
            parent = row["target"]
            candidate = row["target"] if bool(row["trade"]) else zero
            reverse = row["reversed_target"] if bool(row["trade"]) else zero
            anti = row["target"] if bool(row["anti_trade"]) else zero
        candidate_signals.append((i + 1, i + 2, candidate))
        reverse_signals.append((i + 1, i + 2, reverse))
        parent_signals.append((i + 1, i + 2, parent))
        anti_signals.append((i + 1, i + 2, anti))
    predictions = pd.DataFrame(rows)
    predictions = predictions.loc[predictions["signal_i"] >= first_decision_signal_i].copy()
    return PayoffMetaRun(
        candidate=_simulate_signals(candidate_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        reversed_same_decisions=_simulate_signals(reverse_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        ungated_parent=_simulate_signals(parent_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        anti_meta=_simulate_signals(anti_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        predictions=predictions,
    )


def _rank_correlation(x: pd.Series, y: pd.Series) -> float:
    pair = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(pair) < 3:
        return float("nan")
    xr = pair.iloc[:, 0].rank(method="average")
    yr = pair.iloc[:, 1].rank(method="average")
    return float(xr.corr(yr))


def evaluate_payoff_meta(
    run: PayoffMetaRun,
    *,
    evaluation_config: Mapping[str, Any],
    gate: Mapping[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    stats_cfg = evaluation_config["statistics"]
    econ_cfg = evaluation_config["economics"]
    summary = variant_summary(run.candidate, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    reverse_summary = variant_summary(run.reversed_same_decisions, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    parent_summary = variant_summary(run.ungated_parent, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    anti_summary = variant_summary(run.anti_meta, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)

    active = _active_period_returns(run.candidate, cost_multiplier=1.0)
    reverse_active = _active_period_returns(run.reversed_same_decisions, cost_multiplier=1.0)
    parent_active = _active_period_returns(run.ungated_parent, cost_multiplier=1.0)
    predictions = run.predictions.loc[
        np.isfinite(pd.to_numeric(run.predictions["predicted_standalone_net_bps"], errors="coerce"))
    ].copy()
    accepted = predictions.loc[predictions["trade"]]
    rejected = predictions.loc[~predictions["trade"]]
    acceptance_fraction = float(len(accepted) / len(predictions)) if len(predictions) else float("nan")
    active_mean = float(active.mean()) if len(active) else float("nan")
    reverse_mean = float(reverse_active.mean()) if len(reverse_active) else float("nan")
    parent_mean = float(parent_active.mean()) if len(parent_active) else float("nan")
    accepted_payoff = float(accepted["standalone_label_bps"].mean()) if len(accepted) else float("nan")
    rejected_payoff = float(rejected["standalone_label_bps"].mean()) if len(rejected) else float("nan")
    payoff_advantage = accepted_payoff - rejected_payoff
    positive_accepted = int((pd.to_numeric(accepted["standalone_label_bps"], errors="coerce") > 0.0).sum())
    rank_corr = _rank_correlation(predictions["predicted_standalone_net_bps"], predictions["standalone_label_bps"])

    positive = pd.to_numeric(run.candidate.observations["net_return_bps"], errors="coerce")
    positive = positive.loc[positive > 0.0]
    positive_total = float(positive.sum())
    max_positive_share = float(positive.max() / positive_total) if positive_total > 0 and len(positive) else None

    reverse_advantage = active_mean - reverse_mean
    parent_advantage = active_mean - parent_mean
    checks = {
        "minimum_accepted_setups": len(accepted) >= int(gate["minimum_accepted_setups"]),
        "minimum_positive_accepted_setups": positive_accepted >= int(gate["minimum_positive_accepted_setups"]),
        "acceptance_fraction_below_cap": np.isfinite(acceptance_fraction)
        and acceptance_fraction <= float(gate["maximum_acceptance_fraction"]),
        "calendar_day_mean_positive": float(summary["mean_net_bps"]) > 0.0,
        "calendar_day_mean_positive_at_1_5x": float(summary["cost_cases"]["1.5"]["mean_net_bps"]) > 0.0,
        "accepted_setup_mean_above_floor": np.isfinite(active_mean)
        and active_mean >= float(gate["minimum_accepted_setup_mean_net_bps_including_exit_to_cash"]),
        "beats_ungated_parent": np.isfinite(parent_advantage)
        and parent_advantage >= float(gate["minimum_advantage_vs_ungated_parent_active_setup_mean_bps"]),
        "beats_reversed_primary_same_decisions": np.isfinite(reverse_advantage)
        and reverse_advantage >= float(gate["minimum_advantage_vs_reversed_primary_same_decisions_bps"]),
        "accepted_payoff_beats_rejected": np.isfinite(payoff_advantage)
        and payoff_advantage >= float(gate["minimum_accepted_minus_rejected_standalone_payoff_mean_bps"]),
        "best_symbol_share": summary["best_symbol_positive_pnl_share"] is not None
        and float(summary["best_symbol_positive_pnl_share"]) <= float(gate["maximum_best_symbol_positive_pnl_share"]),
        "best_month_share": summary["best_calendar_month_positive_pnl_share"] is not None
        and float(summary["best_calendar_month_positive_pnl_share"]) <= float(gate["maximum_best_calendar_month_positive_pnl_share"]),
        "single_positive_period_share": max_positive_share is not None
        and float(max_positive_share) <= float(gate["maximum_single_positive_period_share"]),
    }
    passed = all(bool(v) for v in checks.values())
    return {
        "state": "RESEARCH_CANDIDATE_FREEZE_PENDING" if passed else "FALSIFIED",
        "candidate_id_if_passed": candidate_id if passed else None,
        "hard_checks": checks,
        "candidate_summary": summary,
        "reversed_same_decisions_summary": reverse_summary,
        "ungated_parent_summary": parent_summary,
        "anti_meta_diagnostic_summary": anti_summary,
        "payoff_meta": {
            "scored_setups": int(len(predictions)),
            "accepted_setups": int(len(accepted)),
            "rejected_setups": int(len(rejected)),
            "positive_accepted_setups": positive_accepted,
            "acceptance_fraction": acceptance_fraction,
            "accepted_active_period_mean_net_bps_including_exit_to_cash": active_mean,
            "ungated_parent_active_period_mean_net_bps": parent_mean,
            "reversed_same_decisions_active_period_mean_net_bps": reverse_mean,
            "advantage_vs_ungated_parent_bps": parent_advantage,
            "advantage_vs_reversed_bps": reverse_advantage,
            "accepted_standalone_payoff_mean_bps": accepted_payoff,
            "rejected_standalone_payoff_mean_bps": rejected_payoff,
            "accepted_minus_rejected_standalone_payoff_mean_bps": payoff_advantage,
            "prediction_realized_rank_correlation": rank_corr,
            "maximum_single_positive_period_share": max_positive_share,
        },
        "d0_diagnostics_not_hard_gates": {
            "bootstrap_lower_bps": summary["bootstrap_lower_bps"],
            "minimum_leave_one_symbol_out_mean_bps": summary["minimum_leave_one_symbol_out_mean_bps"],
            "top5_positive_period_share": summary["top5_positive_period_share"],
            "prediction_realized_rank_correlation": rank_corr,
        },
        "claims": {
            "research_candidate_is_validated_edge": False,
            "live_eligible": False,
            "leverage_eligible": False,
        },
    }

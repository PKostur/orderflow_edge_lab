from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from orderflow_edge_lab.discovery_v2_sprint1 import (
    VariantRun,
    _period_return,
    _validate_price_frames,
    variant_summary,
)
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals
from orderflow_edge_lab.discovery_v2_sprint8 import _wilder_adx
from orderflow_edge_lab.discovery_v2_sprint11 import _active_period_returns


class DiscoveryV2Sprint12Error(ValueError):
    pass


@dataclass(frozen=True)
class MetaFamilyRun:
    candidate: VariantRun
    reversed_same_decisions: VariantRun
    ungated_parent: VariantRun
    anti_meta: VariantRun
    predictions: pd.DataFrame


def _zero(columns: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=columns, dtype=float)


def _score_spread(scores: pd.Series) -> float:
    x = pd.to_numeric(scores, errors="coerce").dropna()
    if len(x) < 6:
        return float("nan")
    return float(x.quantile(0.80) - x.quantile(0.20))


def _funding_burden_per_day(
    funding_frames: Mapping[str, pd.DataFrame],
    symbols: Sequence[str],
    *,
    execution_ts: pd.Timestamp,
    calendar_days: int,
) -> pd.Series:
    lower = execution_ts - pd.Timedelta(days=int(calendar_days))
    out = pd.Series(np.nan, index=list(symbols), dtype=float)
    for symbol in symbols:
        frame = funding_frames.get(symbol)
        if frame is None or frame.empty or "funding_rate" not in frame.columns:
            continue
        rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
        recent = rates.loc[(rates.index >= lower) & (rates.index < execution_ts)]
        if recent.empty:
            continue
        out.loc[symbol] = float(recent.sum()) / float(calendar_days)
    return out


def _primary_scores(
    family: str,
    i: int,
    *,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    returns: pd.DataFrame,
    funding_frames: Mapping[str, pd.DataFrame],
    adx14: pd.Series,
) -> tuple[pd.Series, bool]:
    if family == "meta_trend_acceleration_5d":
        n = 5
        recent = returns.iloc[i - n + 1 : i + 1].sum(axis=0, min_count=n)
        previous = returns.iloc[i - 2 * n + 1 : i - n + 1].sum(axis=0, min_count=n)
        scores = (recent - previous).replace([np.inf, -np.inf], np.nan)
        state_ok = bool(np.isfinite(float(adx14.iloc[i])) and float(adx14.iloc[i]) >= 25.0)
        return scores, state_ok and scores.notna().sum() >= 6
    if family == "meta_low_skew_90d":
        n = 90
        scores = (-returns.iloc[i - n + 1 : i + 1].skew(axis=0)).replace([np.inf, -np.inf], np.nan)
        return scores, scores.notna().sum() >= 6
    if family == "meta_funding_carry_14d":
        execution_ts = opens.index[i + 1]
        burden = _funding_burden_per_day(
            funding_frames,
            list(opens.columns),
            execution_ts=execution_ts,
            calendar_days=14,
        )
        scores = (-burden).replace([np.inf, -np.inf], np.nan)
        return scores, scores.notna().sum() >= 6
    raise DiscoveryV2Sprint12Error(f"unsupported family: {family}")


def _meta_features(
    scores: pd.Series,
    i: int,
    *,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    returns: pd.DataFrame,
    funding_frames: Mapping[str, pd.DataFrame],
    adx14: pd.Series,
) -> np.ndarray:
    btc = "BTC_USDT"
    if btc not in returns.columns:
        raise DiscoveryV2Sprint12Error("BTC_USDT factor required")
    btc_1d = float(returns[btc].iloc[i])
    btc_5d = float(closes[btc].iloc[i] / closes[btc].iloc[i - 5] - 1.0)
    btc_rv20 = float(returns[btc].iloc[i - 19 : i + 1].std(ddof=1) * np.sqrt(365.0))
    xs_rv20 = returns.iloc[i - 19 : i + 1].std(axis=0, ddof=1) * np.sqrt(365.0)
    xs_median_rv20 = float(xs_rv20.median())
    corr_window = returns.iloc[i - 29 : i + 1]
    correlations = []
    for symbol in returns.columns:
        if symbol == btc:
            continue
        pair = corr_window[[btc, symbol]].dropna()
        if len(pair) < 20:
            continue
        correlations.append(float(pair[btc].corr(pair[symbol])))
    median_corr = float(np.median(correlations)) if correlations else float("nan")
    execution_ts = opens.index[i + 1]
    burden3 = _funding_burden_per_day(
        funding_frames,
        list(opens.columns),
        execution_ts=execution_ts,
        calendar_days=3,
    ).dropna()
    funding_disp = (
        float(burden3.quantile(0.80) - burden3.quantile(0.20)) if len(burden3) >= 6 else float("nan")
    )
    values = np.asarray(
        [
            _score_spread(scores),
            btc_1d,
            btc_5d,
            float(adx14.iloc[i]),
            btc_rv20,
            xs_median_rv20,
            median_corr,
            funding_disp,
        ],
        dtype=float,
    )
    return values


def _standalone_label_bps(
    target: pd.Series,
    *,
    opens: pd.DataFrame,
    start_i: int,
    end_i: int,
    funding_frames: Mapping[str, pd.DataFrame],
    side_cost_bps: float,
) -> float:
    zero = _zero(opens.columns)
    gross, cost, _ = _period_return(
        target,
        zero,
        opens,
        opens.index[start_i],
        opens.index[end_i],
        funding_frames,
        float(side_cost_bps),
        force_liquidation=True,
    )
    return float((gross - cost) * 10_000.0)


def _build_primary_setups(
    family: str,
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame],
    side_cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    returns = closes.pct_change()
    adx14 = _wilder_adx(daily_frames["BTC_USDT"], 14).reindex(opens.index)
    minimum_i = {"meta_trend_acceleration_5d": 30, "meta_low_skew_90d": 90, "meta_funding_carry_14d": 30}[family]
    records: list[dict[str, Any]] = []
    for i in range(minimum_i, len(opens) - 2):
        scores, primary_active = _primary_scores(
            family,
            i,
            opens=opens,
            closes=closes,
            returns=returns,
            funding_frames=funding_frames,
            adx14=adx14,
        )
        if not primary_active:
            continue
        features = _meta_features(
            scores,
            i,
            opens=opens,
            closes=closes,
            returns=returns,
            funding_frames=funding_frames,
            adx14=adx14,
        )
        if not np.isfinite(features).all():
            continue
        target = _rank(scores, long_high=True).reindex(opens.columns, fill_value=0.0)
        reversed_target = _rank(scores, long_high=False).reindex(opens.columns, fill_value=0.0)
        start_i, end_i = i + 1, i + 2
        label_bps = _standalone_label_bps(
            target,
            opens=opens,
            start_i=start_i,
            end_i=end_i,
            funding_frames=funding_frames,
            side_cost_bps=side_cost_bps,
        )
        records.append(
            {
                "signal_i": i,
                "signal_timestamp": opens.index[i],
                "start_i": start_i,
                "start_timestamp": opens.index[start_i],
                "end_i": end_i,
                "end_timestamp": opens.index[end_i],
                "target": target,
                "reversed_target": reversed_target,
                "features": features,
                "standalone_label_bps": label_bps,
                "label_positive": int(label_bps > 0.0),
            }
        )
    if not records:
        raise DiscoveryV2Sprint12Error(f"{family}: no eligible primary setups")
    return opens, closes, records


def _model() -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "logit",
                LogisticRegression(
                    penalty="l2",
                    C=1.0,
                    solver="lbfgs",
                    max_iter=2000,
                    class_weight=None,
                    random_state=1212,
                ),
            ),
        ]
    )


def run_meta_family(
    family: str,
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame],
    side_cost_bps: float,
    training_window: int = 80,
    minimum_training: int = 60,
    accept_probability: float = 0.60,
) -> MetaFamilyRun:
    opens, _, records = _build_primary_setups(
        family,
        daily_frames,
        symbols=symbols,
        funding_frames=funding_frames,
        side_cost_bps=side_cost_bps,
    )
    prediction_rows: list[dict[str, Any]] = []
    first_decision_signal_i: int | None = None
    for current in records:
        prior = [r for r in records if pd.Timestamp(r["end_timestamp"]) < pd.Timestamp(current["start_timestamp"])]
        prior = prior[-int(training_window) :]
        probability = float("nan")
        if len(prior) >= int(minimum_training):
            x_train = np.vstack([r["features"] for r in prior])
            y_train = np.asarray([r["label_positive"] for r in prior], dtype=int)
            if len(np.unique(y_train)) >= 2:
                m = _model()
                m.fit(x_train, y_train)
                probability = float(m.predict_proba(np.asarray(current["features"], dtype=float).reshape(1, -1))[0, 1])
        trade = bool(np.isfinite(probability) and probability >= float(accept_probability))
        anti_trade = bool(np.isfinite(probability) and probability <= 1.0 - float(accept_probability))
        if np.isfinite(probability) and first_decision_signal_i is None:
            first_decision_signal_i = int(current["signal_i"])
        prediction_rows.append(
            {
                "signal_timestamp": current["signal_timestamp"],
                "start_timestamp": current["start_timestamp"],
                "end_timestamp": current["end_timestamp"],
                "signal_i": int(current["signal_i"]),
                "probability_positive": probability,
                "trade": trade,
                "anti_trade": anti_trade,
                "standalone_label_bps": float(current["standalone_label_bps"]),
                "label_positive": int(current["label_positive"]),
                "target": current["target"],
                "reversed_target": current["reversed_target"],
            }
        )
    if first_decision_signal_i is None:
        raise DiscoveryV2Sprint12Error(f"{family}: frozen model never had enough prior labeled setups")
    by_i = {int(r["signal_i"]): r for r in prediction_rows}
    candidate_signals: list[tuple[int, int, pd.Series]] = []
    reverse_signals: list[tuple[int, int, pd.Series]] = []
    parent_signals: list[tuple[int, int, pd.Series]] = []
    anti_signals: list[tuple[int, int, pd.Series]] = []
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
    predictions = pd.DataFrame(prediction_rows)
    predictions = predictions.loc[predictions["signal_i"] >= first_decision_signal_i].copy()
    return MetaFamilyRun(
        candidate=_simulate_signals(candidate_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        reversed_same_decisions=_simulate_signals(reverse_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        ungated_parent=_simulate_signals(parent_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        anti_meta=_simulate_signals(anti_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        predictions=predictions,
    )


def evaluate_meta_family(
    run: MetaFamilyRun,
    *,
    evaluation_config: Mapping[str, Any],
    gate: Mapping[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    stats_cfg = evaluation_config["statistics"]
    econ_cfg = evaluation_config["economics"]
    summary = variant_summary(run.candidate, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    reverse_summary = variant_summary(
        run.reversed_same_decisions, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg
    )
    parent_summary = variant_summary(run.ungated_parent, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    anti_summary = variant_summary(run.anti_meta, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    active = _active_period_returns(run.candidate, cost_multiplier=1.0)
    reverse_active = _active_period_returns(run.reversed_same_decisions, cost_multiplier=1.0)
    parent_active = _active_period_returns(run.ungated_parent, cost_multiplier=1.0)
    predictions = run.predictions.loc[np.isfinite(pd.to_numeric(run.predictions["probability_positive"], errors="coerce"))].copy()
    accepted = predictions.loc[predictions["trade"]]
    rejected = predictions.loc[~predictions["trade"]]
    acceptance_fraction = float(len(accepted) / len(predictions)) if len(predictions) else float("nan")
    active_mean = float(active.mean()) if len(active) else float("nan")
    reverse_mean = float(reverse_active.mean()) if len(reverse_active) else float("nan")
    parent_mean = float(parent_active.mean()) if len(parent_active) else float("nan")
    accepted_label_mean = float(accepted["standalone_label_bps"].mean()) if len(accepted) else float("nan")
    rejected_label_mean = float(rejected["standalone_label_bps"].mean()) if len(rejected) else float("nan")
    label_advantage = accepted_label_mean - rejected_label_mean
    reverse_advantage = active_mean - reverse_mean
    parent_advantage = active_mean - parent_mean
    auc = float("nan")
    if len(predictions) >= 2 and predictions["label_positive"].nunique() >= 2:
        auc = float(roc_auc_score(predictions["label_positive"], predictions["probability_positive"]))
    checks = {
        "minimum_accepted_setups": len(accepted) >= int(gate["minimum_accepted_setups"]),
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
        "accepted_labels_beat_rejected": np.isfinite(label_advantage)
        and label_advantage >= float(gate["minimum_accepted_minus_rejected_standalone_label_mean_bps"]),
        "best_symbol_share": summary["best_symbol_positive_pnl_share"] is not None
        and float(summary["best_symbol_positive_pnl_share"]) <= float(gate["maximum_best_symbol_positive_pnl_share"]),
        "best_month_share": summary["best_calendar_month_positive_pnl_share"] is not None
        and float(summary["best_calendar_month_positive_pnl_share"]) <= float(gate["maximum_best_calendar_month_positive_pnl_share"]),
        "top5_share": summary["top5_positive_period_share"] is not None
        and float(summary["top5_positive_period_share"]) <= float(gate["maximum_top5_positive_period_share"]),
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
        "meta_selection": {
            "scored_setups": int(len(predictions)),
            "accepted_setups": int(len(accepted)),
            "rejected_setups": int(len(rejected)),
            "acceptance_fraction": acceptance_fraction,
            "accepted_active_period_mean_net_bps_including_exit_to_cash": active_mean,
            "reversed_same_decisions_active_period_mean_net_bps": reverse_mean,
            "ungated_parent_active_period_mean_net_bps": parent_mean,
            "advantage_vs_reversed_bps": reverse_advantage,
            "advantage_vs_ungated_parent_bps": parent_advantage,
            "accepted_standalone_label_mean_bps": accepted_label_mean,
            "rejected_standalone_label_mean_bps": rejected_label_mean,
            "accepted_minus_rejected_standalone_label_mean_bps": label_advantage,
            "walk_forward_auc": auc,
        },
        "d0_diagnostics_not_hard_gates": {
            "bootstrap_lower_bps": summary["bootstrap_lower_bps"],
            "minimum_leave_one_symbol_out_mean_bps": summary["minimum_leave_one_symbol_out_mean_bps"],
            "walk_forward_auc": auc,
        },
        "claims": {
            "research_candidate_is_validated_edge": False,
            "live_eligible": False,
            "leverage_eligible": False,
        },
    }

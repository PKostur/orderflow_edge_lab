from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals
from orderflow_edge_lab.discovery_v2_sprint8 import _wilder_adx
from orderflow_edge_lab.discovery_v2_sprint12 import (
    _build_primary_setups,
    _meta_features,
    _primary_scores,
    _zero,
)
from orderflow_edge_lab.discovery_v2_sprint13 import _model, run_payoff_meta


def _as_utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _safe_mean(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return float(clean.mean()) if len(clean) else None


def _standalone_ledger(predictions: pd.DataFrame, *, start: pd.Timestamp) -> pd.DataFrame:
    p = predictions.copy()
    p["start_timestamp"] = pd.to_datetime(p["start_timestamp"], utc=True)
    p["end_timestamp"] = pd.to_datetime(p["end_timestamp"], utc=True)
    p = p.loc[p["start_timestamp"] >= start].copy()
    cols = [
        "signal_timestamp",
        "start_timestamp",
        "end_timestamp",
        "predicted_standalone_net_bps",
        "trade",
        "anti_trade",
        "standalone_label_bps",
    ]
    return p[cols].sort_values("start_timestamp").reset_index(drop=True)


def _prospective_sequential_runs(
    meta,
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame],
    prospective_start: pd.Timestamp,
    side_cost_bps: float,
):
    opens, _ = _validate_price_frames(daily_frames, symbols)
    by_i = {int(r.signal_i): r for r in meta.predictions.itertuples(index=False)}
    candidate_signals = []
    reverse_signals = []
    parent_signals = []
    anti_signals = []
    for i in range(0, len(opens) - 2):
        start_ts = pd.Timestamp(opens.index[i + 1])
        if start_ts < prospective_start:
            continue
        row = by_i.get(i)
        zero = _zero(opens.columns)
        if row is None:
            candidate = reverse = parent = anti = zero
        else:
            parent = row.target
            candidate = row.target if bool(row.trade) else zero
            reverse = row.reversed_target if bool(row.trade) else zero
            anti = row.target if bool(row.anti_trade) else zero
        candidate_signals.append((i + 1, i + 2, candidate))
        reverse_signals.append((i + 1, i + 2, reverse))
        parent_signals.append((i + 1, i + 2, parent))
        anti_signals.append((i + 1, i + 2, anti))
    if not candidate_signals:
        return None
    return {
        "candidate": _simulate_signals(candidate_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        "reversed_same_decisions": _simulate_signals(reverse_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        "ungated_parent": _simulate_signals(parent_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
        "anti_meta": _simulate_signals(anti_signals, opens, funding_frames, side_cost_bps=side_cost_bps),
    }


def _latest_open_decision(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame],
    side_cost_bps: float,
    ridge_alpha: float,
    training_window: int,
    minimum_training: int,
    threshold_bps: float,
) -> dict[str, Any]:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    returns = closes.pct_change()
    if len(opens) < 100:
        return {"status": "INSUFFICIENT_HISTORY"}
    signal_i = len(opens) - 2
    start_i = signal_i + 1
    signal_ts = pd.Timestamp(opens.index[signal_i])
    entry_ts = pd.Timestamp(opens.index[start_i])
    adx14 = _wilder_adx(daily_frames["BTC_USDT"], 14).reindex(opens.index)
    scores, primary_active = _primary_scores(
        "meta_trend_acceleration_5d",
        signal_i,
        opens=opens,
        closes=closes,
        returns=returns,
        funding_frames=funding_frames,
        adx14=adx14,
    )
    if not primary_active:
        return {
            "status": "NO_PRIMARY_SETUP",
            "signal_timestamp": signal_ts.isoformat(),
            "entry_timestamp": entry_ts.isoformat(),
        }
    features = _meta_features(
        scores,
        signal_i,
        opens=opens,
        closes=closes,
        returns=returns,
        funding_frames=funding_frames,
        adx14=adx14,
    )
    if not np.isfinite(features).all():
        return {
            "status": "PASS_MISSING_FEATURE",
            "signal_timestamp": signal_ts.isoformat(),
            "entry_timestamp": entry_ts.isoformat(),
        }
    _, _, records = _build_primary_setups(
        "meta_trend_acceleration_5d",
        daily_frames,
        symbols=symbols,
        funding_frames=funding_frames,
        side_cost_bps=side_cost_bps,
    )
    prior = [r for r in records if pd.Timestamp(r["end_timestamp"]) < entry_ts]
    prior = prior[-int(training_window) :]
    if len(prior) < int(minimum_training):
        return {
            "status": "PASS_INSUFFICIENT_TRAINING",
            "signal_timestamp": signal_ts.isoformat(),
            "entry_timestamp": entry_ts.isoformat(),
            "prior_labeled_setups": len(prior),
        }
    model = _model(float(ridge_alpha))
    x = np.vstack([r["features"] for r in prior])
    y = np.asarray([r["standalone_label_bps"] for r in prior], dtype=float)
    model.fit(x, y)
    prediction = float(model.predict(np.asarray(features).reshape(1, -1))[0])
    target = _rank(scores, long_high=True).reindex(opens.columns, fill_value=0.0)
    weights = {str(k): float(v) for k, v in target.items() if abs(float(v)) > 1e-15}
    trade = bool(prediction > float(threshold_bps))
    return {
        "status": "TRADE" if trade else "PASS_MODEL",
        "signal_timestamp": signal_ts.isoformat(),
        "entry_timestamp": entry_ts.isoformat(),
        "prior_labeled_setups": len(prior),
        "predicted_standalone_net_bps": prediction,
        "threshold_bps": float(threshold_bps),
        "weights_if_trade": weights if trade else {},
    }


def build_forward_snapshot(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame],
    prospective_start_utc: str,
    as_of_utc: str | pd.Timestamp,
    side_cost_bps: float = 10.0,
    ridge_alpha: float = 10.0,
    training_window: int = 80,
    minimum_training: int = 60,
    threshold_bps: float = 0.0,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    start = _as_utc(prospective_start_utc)
    as_of = _as_utc(as_of_utc)
    if as_of < start:
        return (
            {
                "status": "PRE_START",
                "prospective_start_utc": start.isoformat(),
                "as_of_utc": as_of.isoformat(),
                "completed_forward_setups": 0,
                "accepted_completed_setups": 0,
                "claims": {
                    "candidate_promoted": False,
                    "D4_validation": False,
                    "live_execution_supported": False,
                    "leverage_supported": False,
                },
            },
            {},
        )

    meta = run_payoff_meta(
        daily_frames,
        symbols=symbols,
        funding_frames=funding_frames,
        side_cost_bps=side_cost_bps,
        ridge_alpha=ridge_alpha,
        training_window=training_window,
        minimum_training=minimum_training,
        trade_threshold_bps=threshold_bps,
    )
    ledger = _standalone_ledger(meta.predictions, start=start)
    accepted = ledger.loc[ledger["trade"]].copy() if not ledger.empty else ledger.copy()
    rejected = ledger.loc[~ledger["trade"]].copy() if not ledger.empty else ledger.copy()
    sequential = _prospective_sequential_runs(
        meta,
        daily_frames,
        symbols=symbols,
        funding_frames=funding_frames,
        prospective_start=start,
        side_cost_bps=side_cost_bps,
    )
    seq_metrics: dict[str, Any] | None = None
    tables: dict[str, pd.DataFrame] = {"completed_setup_ledger": ledger}
    if sequential is not None:
        for name, run in sequential.items():
            tables[f"{name}_observations"] = run.observations.copy()
            tables[f"{name}_contributions"] = run.contributions.copy()
        c = sequential["candidate"].observations
        p = sequential["ungated_parent"].observations
        r = sequential["reversed_same_decisions"].observations
        seq_metrics = {
            "calendar_periods": int(len(c)),
            "candidate_total_net_bps_snapshot_closed": float(c["net_return_bps"].sum()),
            "candidate_mean_net_bps_snapshot_closed": float(c["net_return_bps"].mean()),
            "ungated_parent_mean_net_bps_snapshot_closed": float(p["net_return_bps"].mean()),
            "reversed_same_decisions_mean_net_bps_snapshot_closed": float(r["net_return_bps"].mean()),
        }
    latest = _latest_open_decision(
        daily_frames,
        symbols=symbols,
        funding_frames=funding_frames,
        side_cost_bps=side_cost_bps,
        ridge_alpha=ridge_alpha,
        training_window=training_window,
        minimum_training=minimum_training,
        threshold_bps=threshold_bps,
    )
    if latest.get("entry_timestamp") and _as_utc(latest["entry_timestamp"]) < start:
        latest = {"status": "NO_POST_START_OPEN_DECISION"}
    accepted_mean = _safe_mean(accepted["standalone_label_bps"]) if not accepted.empty else None
    rejected_mean = _safe_mean(rejected["standalone_label_bps"]) if not rejected.empty else None
    report = {
        "status": "FORWARD_RESEARCH_SHADOW",
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "completed_forward_setups": int(len(ledger)),
        "accepted_completed_setups": int(len(accepted)),
        "rejected_completed_setups": int(len(rejected)),
        "accepted_fraction_completed_setups": float(len(accepted) / len(ledger)) if len(ledger) else None,
        "accepted_standalone_payoff_mean_bps": accepted_mean,
        "rejected_standalone_payoff_mean_bps": rejected_mean,
        "accepted_minus_rejected_standalone_payoff_mean_bps": (
            float(accepted_mean - rejected_mean)
            if accepted_mean is not None and rejected_mean is not None
            else None
        ),
        "accepted_standalone_payoff_total_bps": (
            float(pd.to_numeric(accepted["standalone_label_bps"], errors="coerce").sum()) if len(accepted) else 0.0
        ),
        "sequential_paper_snapshot": seq_metrics,
        "latest_open_decision": latest,
        "claims": {
            "candidate_promoted": False,
            "D0_passed": False,
            "D4_validation": False,
            "live_execution_supported": False,
            "leverage_supported": False,
        },
    }
    return report, tables

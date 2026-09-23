from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.session_metrics import (
    DEFAULT_SESSIONS,
    SessionSpec,
    session_memberships,
    session_phase_memberships,
    session_regime,
)
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    legacy_strategy,
    run_canonical_backtest,
)


class UniversalSessionAlignmentShadowError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _validate_frame(frame: pd.DataFrame, symbol: str, as_of: pd.Timestamp) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise UniversalSessionAlignmentShadowError(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise UniversalSessionAlignmentShadowError(f"{symbol}: duplicate timestamps")
    required = {"open", "high", "low", "close"}
    if not required.issubset(out.columns):
        raise UniversalSessionAlignmentShadowError(f"{symbol}: missing OHLC columns")
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    values = out[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise UniversalSessionAlignmentShadowError(f"{symbol}: invalid OHLC values")
    boundary = as_of.floor("8h")
    out = out[out.index <= boundary]
    if len(out) < 100:
        raise UniversalSessionAlignmentShadowError(f"{symbol}: insufficient warmup bars")
    return out


def _alignment(side: int, value: float | None) -> str:
    if value is None or not math.isfinite(value) or value == 0.0:
        return "NEUTRAL"
    direction = 1 if value > 0.0 else -1
    return "ALIGNED" if direction == side else "AGAINST"


def _prior_three_bar_return(frame: pd.DataFrame, entry: pd.Timestamp) -> float | None:
    try:
        location = frame.index.get_loc(entry)
    except KeyError:
        return None
    if not isinstance(location, (int, np.integer)) or int(location) < 3:
        return None
    i = int(location)
    start = float(frame["open"].iloc[i - 3])
    end = float(frame["close"].iloc[i - 1])
    if start <= 0.0 or not math.isfinite(start) or not math.isfinite(end):
        return None
    return end / start - 1.0


def _btc_prior_bar_return(btc_frame: pd.DataFrame, entry: pd.Timestamp) -> float | None:
    prior = btc_frame[btc_frame.index < entry]
    if prior.empty:
        return None
    row = prior.iloc[-1]
    start = float(row["open"])
    end = float(row["close"])
    if start <= 0.0 or not math.isfinite(start) or not math.isfinite(end):
        return None
    return end / start - 1.0


def _annotate_trade(
    trade: Mapping[str, Any],
    frame: pd.DataFrame,
    btc_frame: pd.DataFrame,
    *,
    symbol: str,
    audit_id: str,
    sessions: Sequence[SessionSpec],
) -> dict[str, Any]:
    entry = _utc(trade["entry"])
    side = int(trade.get("side") or 0)
    if side not in (-1, 1):
        raise UniversalSessionAlignmentShadowError("canonical trade side must be -1 or 1")
    memberships = session_memberships(entry.to_pydatetime(), sessions)
    own_prior_three = _prior_three_bar_return(frame, entry)
    btc_prior = _btc_prior_bar_return(btc_frame, entry)
    return {
        **dict(trade),
        "symbol": symbol,
        "audit_id": audit_id,
        "entry_utc": entry.isoformat(),
        "exclusive_session_regime": session_regime(entry.to_pydatetime(), sessions),
        "session_memberships": list(memberships),
        "session_phases": list(session_phase_memberships(entry.to_pydatetime(), sessions)),
        "own_prior_3bar_direction": _alignment(side, own_prior_three),
        "btc_prior_bar_direction": _alignment(side, btc_prior),
        "scored_completed_trade": not bool(trade.get("terminal_liquidation")),
    }


def _profit_factor(values: Sequence[float]) -> float | str | None:
    gains = sum(value for value in values if value > 0.0)
    losses = -sum(value for value in values if value < 0.0)
    if losses > 0.0:
        return gains / losses
    return "INF" if gains > 0.0 else None


def _max_drawdown(values_bps: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values_bps:
        factor = 1.0 + float(value) / 10_000.0
        if factor <= 0.0:
            raise UniversalSessionAlignmentShadowError("completed trade factor is non-positive")
        equity *= factor
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row["entry_utc"]), str(row["symbol"])))
    if not ordered:
        return {
            "completed_trade_count": 0,
            "compounded_completed_trade_return": 0.0,
            "expectancy_bps": None,
            "median_trade_bps": None,
            "win_rate": None,
            "profit_factor": None,
            "correct_direction_count": 0,
            "correct_direction_rate": None,
            "mean_correct_direction_mfe_bps": None,
            "median_correct_direction_mfe_bps": None,
            "max_completed_trade_sequence_drawdown": 0.0,
        }
    values = [float(row["net_bps"]) for row in ordered]
    equity = 1.0
    for value in values:
        factor = 1.0 + value / 10_000.0
        if factor <= 0.0:
            raise UniversalSessionAlignmentShadowError("completed trade factor is non-positive")
        equity *= factor
    correct = [row for row in ordered if float(row["gross_bps"]) > 0.0]
    mfe = [float(row["mfe_bps"]) for row in correct]
    return {
        "completed_trade_count": len(ordered),
        "compounded_completed_trade_return": equity - 1.0,
        "expectancy_bps": statistics.fmean(values),
        "median_trade_bps": statistics.median(values),
        "win_rate": sum(value > 0.0 for value in values) / len(values),
        "profit_factor": _profit_factor(values),
        "correct_direction_count": len(correct),
        "correct_direction_rate": len(correct) / len(ordered),
        "mean_correct_direction_mfe_bps": statistics.fmean(mfe) if mfe else None,
        "median_correct_direction_mfe_bps": statistics.median(mfe) if mfe else None,
        "max_completed_trade_sequence_drawdown": _max_drawdown(values),
    }


def _factor_rows(
    rows: Sequence[Mapping[str, Any]],
    factor: str,
    states: Sequence[str],
) -> list[dict[str, Any]]:
    return [
        {
            "state": state,
            **_summary([row for row in rows if str(row.get(factor)) == state]),
        }
        for state in states
    ]


def _difference(left: Mapping[str, Any], right: Mapping[str, Any], field: str) -> float | None:
    a = left.get(field)
    b = right.get(field)
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _comparison(
    rows: Sequence[Mapping[str, Any]],
    hypothesis: Mapping[str, Any],
) -> dict[str, Any]:
    factor = str(hypothesis["factor"])
    left_state = str(hypothesis["aligned_state"])
    right_state = str(hypothesis["comparison_state"])
    left = _summary([row for row in rows if str(row.get(factor)) == left_state])
    right = _summary([row for row in rows if str(row.get(factor)) == right_state])
    return {
        "hypothesis_id": hypothesis["hypothesis_id"],
        "factor": factor,
        "aligned_state": left_state,
        "comparison_state": right_state,
        "aligned": left,
        "comparison": right,
        "expectancy_difference_bps": _difference(left, right, "expectancy_bps"),
        "win_rate_difference": _difference(left, right, "win_rate"),
        "correct_direction_mfe_difference_bps": _difference(
            left, right, "mean_correct_direction_mfe_bps"
        ),
        "formal_verdict": "WITHHELD",
    }


def build_shadow_report(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of_utc: str | pd.Timestamp,
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of = _utc(as_of_utc)
    symbols = [str(value) for value in config["source"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise UniversalSessionAlignmentShadowError(f"missing symbol frames: {missing}")
    clean = {symbol: _validate_frame(frames[symbol], symbol, as_of) for symbol in symbols}
    btc = clean.get("BTC_USDT")
    if btc is None:
        raise UniversalSessionAlignmentShadowError("BTC_USDT frame is required for frozen alignment labels")

    cost = float(config["economics"]["round_trip_cost_bps"])
    review_days = int(config["reporting"]["review_after_calendar_days"])
    minimum_trades = int(config["reporting"]["minimum_completed_trades_per_strategy"])
    days_elapsed = max(0, int((as_of - start) / pd.Timedelta(days=1))) if as_of >= start else 0
    hypotheses = list(config.get("frozen_hypotheses", []))

    reports: list[dict[str, Any]] = []
    for variant in config["variants"]:
        audit_id = str(variant["audit_id"])
        strategy = legacy_strategy(str(variant["family"]))
        params = dict(variant["parameters"])
        completed: list[dict[str, Any]] = []
        open_snapshots: list[dict[str, Any]] = []

        for symbol in symbols:
            result = run_canonical_backtest(
                clean[symbol],
                strategy,
                params,
                ExecutionModel(
                    round_trip_cost_bps=cost,
                    max_abs_position=float(config["economics"].get("max_abs_position", 1.0)),
                ),
            )
            accounting = result.get("accounting") or {}
            version = accounting.get("version")
            if result.get("trades", 0) and int(version or 0) != int(config["economics"]["canonical_accounting_version"]):
                raise UniversalSessionAlignmentShadowError(
                    f"{audit_id}/{symbol}: canonical accounting version mismatch"
                )
            for trade in result.get("trades_ledger", []):
                entry = _utc(trade["entry"])
                if entry < start:
                    continue
                annotated = _annotate_trade(
                    trade,
                    clean[symbol],
                    btc,
                    symbol=symbol,
                    audit_id=audit_id,
                    sessions=sessions,
                )
                if annotated["scored_completed_trade"]:
                    completed.append(annotated)
                else:
                    open_snapshots.append(annotated)

        by_session = []
        regimes = sorted({str(row["exclusive_session_regime"]) for row in completed})
        for regime in regimes:
            by_session.append(
                {
                    "exclusive_session_regime": regime,
                    **_summary([row for row in completed if row["exclusive_session_regime"] == regime]),
                }
            )

        applicable = [
            hypothesis
            for hypothesis in hypotheses
            if audit_id in [str(value) for value in hypothesis.get("applies_to", [])]
        ]
        ready = days_elapsed >= review_days and len(completed) >= minimum_trades
        reports.append(
            {
                "audit_id": audit_id,
                "family": variant["family"],
                "parameters": params,
                "role": variant["role"],
                "summary": _summary(completed),
                "by_exclusive_session_regime": by_session,
                "by_btc_prior_bar_direction": _factor_rows(
                    completed, "btc_prior_bar_direction", ("ALIGNED", "AGAINST", "NEUTRAL")
                ),
                "by_own_prior_3bar_direction": _factor_rows(
                    completed, "own_prior_3bar_direction", ("ALIGNED", "AGAINST", "NEUTRAL")
                ),
                "frozen_hypothesis_comparisons": [
                    _comparison(completed, hypothesis) for hypothesis in applicable
                ],
                "completed_trades": sorted(
                    completed, key=lambda row: (str(row["entry_utc"]), str(row["symbol"]))
                ),
                "open_terminal_snapshots_not_scored": sorted(
                    open_snapshots, key=lambda row: (str(row["entry_utc"]), str(row["symbol"]))
                ),
                "review_requirement": {
                    "minimum_calendar_days": review_days,
                    "minimum_completed_trades": minimum_trades,
                },
                "ready_for_review": ready,
                "formal_verdict": "WITHHELD",
            }
        )

    if as_of < start:
        status = "PRE_START"
    elif reports and all(bool(report["ready_for_review"]) for report in reports):
        status = "READY_FOR_REVIEW"
    else:
        status = "ACCUMULATING"

    return {
        "schema_version": 1,
        "analysis": "universal_session_alignment_prospective_shadow",
        "watch_id": config["watch_id"],
        "status": status,
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "calendar_days_elapsed": days_elapsed,
        "source": config["source"],
        "economics": config["economics"],
        "shadow_labels": config["shadow_labels"],
        "frozen_hypotheses": hypotheses,
        "reports": reports,
        "claims": {
            **dict(config["claims"]),
            "pre_start_entries_excluded_from_scoring": True,
            "terminal_snapshot_liquidations_excluded_from_completed_trade_scoring": True,
            "labels_do_not_gate_trade_generation": True,
            "formal_verdict_withheld_until_review_requirements": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
        },
    }

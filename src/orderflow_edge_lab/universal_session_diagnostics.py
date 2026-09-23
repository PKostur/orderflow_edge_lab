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


class UniversalSessionDiagnosticsError(ValueError):
    pass


def _as_timestamp(value: Any) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise UniversalSessionDiagnosticsError(f"invalid trade timestamp: {value!r}") from exc
    if ts.tzinfo is None:
        raise UniversalSessionDiagnosticsError("trade timestamps must be timezone-aware")
    return ts.tz_convert("UTC")


def _alignment(side: int, value: float | None) -> str:
    if value is None or not math.isfinite(value) or value == 0.0:
        return "NEUTRAL"
    direction = 1 if value > 0.0 else -1
    return "ALIGNED" if direction == side else "AGAINST"


def _compound(values_bps: Sequence[float]) -> float:
    equity = 1.0
    for value in values_bps:
        factor = 1.0 + float(value) / 10_000.0
        if factor <= 0.0:
            raise UniversalSessionDiagnosticsError("trade factor is non-positive")
        equity *= factor
    return equity - 1.0


def _profit_factor(values: Sequence[float]) -> float | str | None:
    gains = sum(value for value in values if value > 0.0)
    losses = -sum(value for value in values if value < 0.0)
    if losses > 0.0:
        return gains / losses
    return "INF" if gains > 0.0 else None


def _trade_drawdown(values_bps: Sequence[float]) -> float | None:
    if not values_bps:
        return None
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values_bps:
        equity *= 1.0 + float(value) / 10_000.0
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "observations": 0,
            "cumulative_return": 0.0,
            "expectancy_bps": None,
            "median_trade_bps": None,
            "win_rate": None,
            "profit_factor": None,
            "max_trade_sequence_drawdown": None,
            "correct_direction_observations": 0,
            "correct_direction_rate": None,
            "mean_correct_direction_mfe_bps": None,
            "median_correct_direction_mfe_bps": None,
            "p75_correct_direction_mfe_bps": None,
            "mean_correct_direction_gross_bps": None,
            "median_correct_direction_gross_bps": None,
        }
    ordered = sorted(rows, key=lambda row: row["_entry_timestamp"])
    net = [float(row["net_bps"]) for row in ordered]
    correct = [row for row in ordered if float(row["gross_bps"]) > 0.0]
    correct_mfe = [float(row["mfe_bps"]) for row in correct]
    correct_gross = [float(row["gross_bps"]) for row in correct]
    return {
        "observations": len(ordered),
        "cumulative_return": _compound(net),
        "expectancy_bps": statistics.fmean(net),
        "median_trade_bps": statistics.median(net),
        "win_rate": sum(value > 0.0 for value in net) / len(net),
        "profit_factor": _profit_factor(net),
        "max_trade_sequence_drawdown": _trade_drawdown(net),
        "correct_direction_observations": len(correct),
        "correct_direction_rate": len(correct) / len(ordered),
        "mean_correct_direction_mfe_bps": statistics.fmean(correct_mfe) if correct_mfe else None,
        "median_correct_direction_mfe_bps": statistics.median(correct_mfe) if correct_mfe else None,
        "p75_correct_direction_mfe_bps": float(np.percentile(correct_mfe, 75)) if correct_mfe else None,
        "mean_correct_direction_gross_bps": statistics.fmean(correct_gross) if correct_gross else None,
        "median_correct_direction_gross_bps": statistics.median(correct_gross) if correct_gross else None,
    }


def _with_deltas(summary: dict[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    for key, output_key in (
        ("expectancy_bps", "expectancy_delta_vs_all_bps"),
        ("win_rate", "win_rate_delta_vs_all"),
        ("median_correct_direction_mfe_bps", "correct_direction_mfe_delta_vs_all_bps"),
    ):
        value = summary.get(key)
        base = baseline.get(key)
        out[output_key] = float(value) - float(base) if value is not None and base is not None else None
    out["sample_warning"] = int(summary.get("observations") or 0) < 20
    return out


def _prior_return(frame: pd.DataFrame, entry_index: int, bars: int) -> float | None:
    if bars <= 0 or entry_index < bars:
        return None
    start = entry_index - bars
    open_price = float(frame["open"].iloc[start])
    close_price = float(frame["close"].iloc[entry_index - 1])
    if not math.isfinite(open_price) or not math.isfinite(close_price) or open_price <= 0.0:
        return None
    return close_price / open_price - 1.0


def _btc_prior_return(context_frame: pd.DataFrame | None, entry: pd.Timestamp) -> float | None:
    if context_frame is None or len(context_frame) == 0:
        return None
    before = context_frame.index < entry
    if not bool(before.any()):
        return None
    row = context_frame.loc[before].iloc[-1]
    open_price = float(row["open"])
    close_price = float(row["close"])
    if not math.isfinite(open_price) or not math.isfinite(close_price) or open_price <= 0.0:
        return None
    return close_price / open_price - 1.0


def _enrich_trade(
    trade: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    btc_frame: pd.DataFrame | None,
    sessions: Sequence[SessionSpec],
) -> dict[str, Any]:
    entry = _as_timestamp(trade.get("entry"))
    try:
        loc = frame.index.get_loc(entry)
    except KeyError as exc:
        raise UniversalSessionDiagnosticsError(f"trade entry {entry.isoformat()} not present in frame") from exc
    if not isinstance(loc, (int, np.integer)):
        raise UniversalSessionDiagnosticsError("trade entry does not resolve to one market row")
    side = int(trade.get("side") or 0)
    if side not in (-1, 1):
        raise UniversalSessionDiagnosticsError("trade side must be -1 or 1")
    prior_1 = _prior_return(frame, int(loc), 1)
    prior_3 = _prior_return(frame, int(loc), 3)
    btc_prior_1 = _btc_prior_return(btc_frame, entry)
    factors = {
        "prior_bar_direction": _alignment(side, prior_1),
        "prior_3bar_direction": _alignment(side, prior_3),
        "btc_prior_bar_direction": _alignment(side, btc_prior_1),
    }
    available = [state for state in factors.values() if state != "NEUTRAL"]
    aligned_count = sum(state == "ALIGNED" for state in available)
    against_count = sum(state == "AGAINST" for state in available)
    memberships = session_memberships(entry.to_pydatetime(), sessions)
    return {
        **dict(trade),
        "_entry_timestamp": entry,
        "_session_memberships": memberships,
        "_session_regime": session_regime(entry.to_pydatetime(), sessions),
        "_session_phases": session_phase_memberships(entry.to_pydatetime(), sessions),
        "_alignment_factors": factors,
        "_alignment_available": len(available),
        "_aligned_factor_count": aligned_count,
        "_against_factor_count": against_count,
    }


def build_universal_session_diagnostics(
    frame: pd.DataFrame,
    canonical_result: Mapping[str, Any],
    *,
    symbol: str,
    btc_frame: pd.DataFrame | None = None,
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> dict[str, Any]:
    ledger = canonical_result.get("trades_ledger") or []
    if not isinstance(ledger, list):
        raise UniversalSessionDiagnosticsError("canonical trades_ledger must be a list")
    enriched = [
        _enrich_trade(trade, frame, btc_frame=btc_frame, sessions=sessions)
        for trade in ledger
        if isinstance(trade, Mapping)
    ]
    baseline = _summary(enriched)

    by_session = []
    for spec in sessions:
        rows = [row for row in enriched if spec.name in row["_session_memberships"]]
        by_session.append({
            "session": spec.name,
            "timezone": spec.timezone_name,
            "local_window": f"{spec.start_local.strftime('%H:%M')}-{spec.end_local.strftime('%H:%M')}",
            **_with_deltas(_summary(rows), baseline),
        })

    regimes = sorted({str(row["_session_regime"]) for row in enriched})
    by_regime = [
        {"regime": regime, **_with_deltas(_summary([row for row in enriched if row["_session_regime"] == regime]), baseline)}
        for regime in regimes
    ]

    phases = sorted({phase for row in enriched for phase in row["_session_phases"]})
    by_phase = [
        {"session_phase": phase, **_with_deltas(_summary([row for row in enriched if phase in row["_session_phases"]]), baseline)}
        for phase in phases
    ]

    factor_rows = []
    factor_names = ("prior_bar_direction", "prior_3bar_direction", "btc_prior_bar_direction")
    for factor in factor_names:
        for state in ("ALIGNED", "AGAINST", "NEUTRAL"):
            rows = [row for row in enriched if row["_alignment_factors"][factor] == state]
            if rows:
                factor_rows.append({
                    "factor": factor,
                    "state": state,
                    **_with_deltas(_summary(rows), baseline),
                })

    stack_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        stack_groups[(int(row["_aligned_factor_count"]), int(row["_alignment_available"]))].append(row)
    by_stack = [
        {
            "aligned_factor_count": aligned_count,
            "available_factor_count": available_count,
            **_with_deltas(_summary(rows), baseline),
        }
        for (aligned_count, available_count), rows in sorted(stack_groups.items())
    ]

    canonical_return = canonical_result.get("total_return")
    return {
        "schema_version": 1,
        "analysis": "universal_session_diagnostics",
        "symbol": symbol,
        "accounting_version": (canonical_result.get("accounting") or {}).get("version"),
        "baseline": baseline,
        "baseline_reconciles_to_canonical_total_return": (
            bool(np.isclose(float(baseline["cumulative_return"]), float(canonical_return), rtol=1e-10, atol=1e-12))
            if canonical_return is not None else None
        ),
        "by_session_membership": by_session,
        "by_exclusive_regime": by_regime,
        "by_session_phase": by_phase,
        "by_alignment_factor": factor_rows,
        "by_alignment_stack": by_stack,
        "protocol": {
            "entry_timestamp_assigns_session": True,
            "session_membership_is_multilabel": True,
            "overlaps_are_not_forced_into_one_named_session": True,
            "correct_direction_definition": "gross_bps > 0",
            "distance_travelled_measure": "canonical unweighted MFE in bps over the trade episode",
            "cumulative_return_definition": "product(1 + canonical_net_bps/10000) - 1",
            "alignment_factors": {
                "prior_bar_direction": "trade side versus open-to-close return of the immediately preceding completed bar",
                "prior_3bar_direction": "trade side versus open of the third preceding bar to close of the immediately preceding bar",
                "btc_prior_bar_direction": "trade side versus the latest completed BTC_USDT bar before entry when BTC context is available",
            },
            "alignment_uses_pre_entry_information_only": True,
        },
        "claims": {
            "descriptive_only": True,
            "frozen_strategy_targets_unchanged": True,
            "diagnostics_do_not_affect_compatibility_pass": True,
            "same_period_analysis_is_not_future_oos": True,
            "session_filter_authorized": False,
            "strategy_promotion_authorized": False,
            "live_trading_authorized": False,
        },
    }

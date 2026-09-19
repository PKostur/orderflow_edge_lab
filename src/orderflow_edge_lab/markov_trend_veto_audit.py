from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class MarkovTrendVetoAuditError(ValueError):
    pass


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _funding_between(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0)
    return float(values[(values.index > start) & (values.index <= end)].sum())


def _group_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = np.asarray([float(row["realized_net_return"]) for row in rows], dtype=float)
    if values.size == 0:
        return {
            "decisions": 0,
            "mean_realized_net_bps": None,
            "median_realized_net_bps": None,
            "win_rate": None,
            "profit_factor": None,
            "compounded_return": None,
        }
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses > 0:
        pf: float | str | None = gains / losses
    elif gains > 0:
        pf = "INF"
    else:
        pf = None
    return {
        "decisions": int(values.size),
        "mean_realized_net_bps": float(values.mean() * 10_000.0),
        "median_realized_net_bps": float(np.median(values) * 10_000.0),
        "win_rate": float(np.mean(values > 0)),
        "profit_factor": pf,
        "compounded_return": float(np.prod(1.0 + values) - 1.0),
    }


def audit_trend_decisions(
    decisions: Sequence[Mapping[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    *,
    horizon_bars: int,
    round_trip_cost_bps: float,
    minimum_completed_decisions_for_review: int,
) -> dict[str, Any]:
    if horizon_bars < 1:
        raise MarkovTrendVetoAuditError("horizon_bars must be positive")
    rows: list[dict[str, Any]] = []
    censored: list[dict[str, Any]] = []
    cost = float(round_trip_cost_bps) / 10_000.0

    for raw in decisions:
        symbol = str(raw["symbol"])
        if symbol not in frames:
            raise MarkovTrendVetoAuditError(f"missing frame for {symbol}")
        frame = frames[symbol].sort_index()
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise MarkovTrendVetoAuditError(f"{symbol}: DatetimeIndex required")
        if frame.index.tz is None:
            frame = frame.copy()
            frame.index = frame.index.tz_localize("UTC")
        else:
            frame = frame.copy()
            frame.index = frame.index.tz_convert("UTC")
        ts = _utc(str(raw["execution_time"]))
        if ts not in frame.index:
            raise MarkovTrendVetoAuditError(f"{symbol}: missing execution bar {ts.isoformat()}")
        loc = frame.index.get_loc(ts)
        if not isinstance(loc, (int, np.integer)):
            raise MarkovTrendVetoAuditError(f"{symbol}: ambiguous execution index")
        exit_loc = int(loc) + int(horizon_bars)
        if exit_loc >= len(frame):
            censored.append({
                "symbol": symbol,
                "execution_time": ts.isoformat(),
                "decision": str(raw["decision"]),
                "reason": "horizon_not_fully_observed",
            })
            continue
        exit_ts = frame.index[exit_loc]
        entry = float(frame.iloc[int(loc)]["open"])
        exit_price = float(frame.iloc[exit_loc]["open"])
        side = float(raw.get("base_requested_side", 1.0 if str(raw.get("side")) == "long" else -1.0))
        if side not in (-1.0, 1.0):
            raise MarkovTrendVetoAuditError("base_requested_side must be -1 or +1")
        gross = side * (exit_price / entry - 1.0)
        funding_sum = _funding_between(funding.get(symbol), ts, exit_ts)
        funding_return = -side * funding_sum
        net = gross + funding_return - cost
        rows.append({
            "symbol": symbol,
            "execution_time": ts.isoformat(),
            "exit_time": exit_ts.isoformat(),
            "decision": str(raw["decision"]),
            "state": raw.get("state"),
            "side": "long" if side > 0 else "short",
            "conservative_score_bps": raw.get("conservative_score_bps"),
            "entry_price": entry,
            "exit_price": exit_price,
            "gross_return": float(gross),
            "funding_return": float(funding_return),
            "round_trip_cost_bps": float(round_trip_cost_bps),
            "realized_net_return": float(net),
            "realized_net_bps": float(net * 10_000.0),
        })

    passed = [row for row in rows if row["decision"] == "PASS"]
    vetoed = [row for row in rows if row["decision"] == "VETO"]
    pass_stats = _group_stats(passed)
    veto_stats = _group_stats(vetoed)
    pmean = pass_stats["mean_realized_net_bps"]
    vmean = veto_stats["mean_realized_net_bps"]
    discrimination = float(pmean - vmean) if pmean is not None and vmean is not None else None
    avoided_losses = sum(float(row["realized_net_return"]) < 0 for row in vetoed)
    missed_winners = sum(float(row["realized_net_return"]) > 0 for row in vetoed)
    completed = len(rows)

    return {
        "completed_decisions": completed,
        "censored_decisions": len(censored),
        "minimum_completed_decisions_for_review": int(minimum_completed_decisions_for_review),
        "reviewable_count_reached": completed >= int(minimum_completed_decisions_for_review),
        "pass": pass_stats,
        "veto": veto_stats,
        "pass_minus_veto_mean_realized_net_bps": discrimination,
        "avoided_veto_losses": int(avoided_losses),
        "missed_veto_winners": int(missed_winners),
        "decision_outcomes": sorted(rows, key=lambda x: (x["execution_time"], x["symbol"])),
        "censored": sorted(censored, key=lambda x: (x["execution_time"], x["symbol"])),
        "claims": {
            "markov_rule_modified": False,
            "realized_outcomes_used_for_retuning": False,
            "paper_diagnostic_only": True,
            "verified_out_of_sample_edge": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

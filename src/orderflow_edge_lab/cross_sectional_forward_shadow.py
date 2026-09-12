from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


class CrossSectionalForwardError(ValueError):
    pass


ONE_DAY = pd.Timedelta(days=1)


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def verify_candidate_spec(candidate: Mapping[str, Any]) -> bool:
    expected = candidate.get("spec_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(candidate)
    unsigned.pop("spec_sha256", None)
    return _canonical_sha256(unsigned) == expected


def load_candidate(path: str | Path) -> tuple[dict[str, Any], str]:
    source = Path(path)
    raw = source.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or not verify_candidate_spec(payload):
        raise CrossSectionalForwardError("candidate specification hash is invalid")
    return payload, sha256(raw).hexdigest()


def _validate_frames(frames: Mapping[str, pd.DataFrame], symbols: list[str]) -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    clean: dict[str, pd.DataFrame] = {}
    common: pd.DatetimeIndex | None = None
    for symbol in symbols:
        if symbol not in frames:
            raise CrossSectionalForwardError(f"missing frozen symbol: {symbol}")
        frame = frames[symbol].copy().sort_index()
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise CrossSectionalForwardError(f"{symbol}: index must be DatetimeIndex")
        frame.index = frame.index.tz_localize("UTC") if frame.index.tz is None else frame.index.tz_convert("UTC")
        if frame.index.has_duplicates or not {"open", "close"}.issubset(frame.columns):
            raise CrossSectionalForwardError(f"{symbol}: invalid daily frame")
        for column in ("open", "close"):
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any():
                raise CrossSectionalForwardError(f"{symbol}: invalid {column}")
            frame[column] = values.astype(float)
        clean[symbol] = frame
        common = frame.index if common is None else common.intersection(frame.index)
    if common is None or len(common) < 31:
        raise CrossSectionalForwardError("insufficient common daily history")
    return clean, common.sort_values()


def _funding_between(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    series = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0)
    return float(series[(series.index > start) & (series.index <= end)].sum())


def build_rebalance_weights(
    frames: Mapping[str, pd.DataFrame],
    candidate: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[pd.Timestamp, pd.Series]:
    if not verify_candidate_spec(candidate):
        raise CrossSectionalForwardError("candidate specification hash is invalid")
    spec = candidate["specification"]
    symbols = [str(value) for value in spec["symbols"]]
    clean, common = _validate_frames(frames, symbols)
    as_of = _utc(as_of_utc)
    current_day = as_of.floor("d")
    closed_index = common[common < current_day]
    if len(closed_index) < int(spec["lookback_days"]) + 1:
        return {}
    closes = pd.DataFrame({s: clean[s].loc[closed_index, "close"] for s in symbols}, index=closed_index)
    start = _utc(candidate["forward_signal_start_utc"])
    eligible = list(closed_index[closed_index >= start])
    if not eligible:
        return {}
    first_signal = eligible[0]
    holding = int(spec["holding_days"])
    lookback = int(spec["lookback_days"])
    n_select = max(1, int(math.floor(len(symbols) * float(spec["quantile_fraction"]))))
    rebalances: dict[pd.Timestamp, pd.Series] = {}
    for offset, signal_ts in enumerate(eligible):
        if offset % holding:
            continue
        loc = closes.index.get_loc(signal_ts)
        if not isinstance(loc, int) or loc < lookback:
            continue
        scores = closes.iloc[loc] / closes.iloc[loc - lookback] - 1.0
        scores = scores.dropna().sort_values()
        if len(scores) < max(4, n_select * 2):
            continue
        winners = list(scores.index[-n_select:])
        losers = list(scores.index[:n_select])
        weights = pd.Series(0.0, index=symbols, dtype=float)
        weights.loc[winners] = 0.5 / len(winners)
        weights.loc[losers] = -0.5 / len(losers)
        execution_ts = signal_ts + ONE_DAY
        if execution_ts <= current_day:
            rebalances[execution_ts] = weights
    return rebalances


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
        raise CrossSectionalForwardError("candidate specification hash is invalid")
    as_of = _utc(as_of_utc)
    spec = candidate["specification"]
    symbols = [str(value) for value in spec["symbols"]]
    clean, common = _validate_frames(frames, symbols)
    current_day = as_of.floor("d")
    rebalance_weights = build_rebalance_weights(clean, candidate, as_of_utc=as_of)
    cost_bps = float(spec["round_trip_cost_bps"])
    side_cost = cost_bps / 2.0 / 10_000.0
    weights = pd.Series(0.0, index=symbols, dtype=float)
    intervals: list[dict[str, Any]] = []
    rebalance_events: list[dict[str, Any]] = []

    first_exec = min(rebalance_weights) if rebalance_weights else None
    if first_exec is not None:
        day_starts = [ts for ts in common if first_exec <= ts <= current_day]
        for ts in day_starts:
            previous = weights.copy()
            if ts in rebalance_weights:
                weights = rebalance_weights[ts].copy()
                turnover = float((weights - previous).abs().sum())
                rebalance_events.append({
                    "execution_time": ts.isoformat(),
                    "turnover": turnover,
                    "weights": {s: float(weights[s]) for s in symbols},
                })
            else:
                turnover = 0.0
            end = as_of if ts == current_day else ts + ONE_DAY
            if end <= ts:
                continue
            gross = 0.0
            funding_return = 0.0
            for symbol in symbols:
                weight = float(weights[symbol])
                if abs(weight) < 1e-15:
                    continue
                frame = clean[symbol]
                if ts not in frame.index:
                    raise CrossSectionalForwardError(f"{symbol}: missing execution day {ts}")
                entry = float(frame.loc[ts, "open"])
                if ts == current_day:
                    mark = float(frame.loc[ts, "close"])
                else:
                    if end not in frame.index:
                        raise CrossSectionalForwardError(f"{symbol}: missing next daily open {end}")
                    mark = float(frame.loc[end, "open"])
                gross += weight * (mark / entry - 1.0)
                funding_return += -weight * _funding_between(funding.get(symbol, pd.DataFrame()), ts, end)
            trading_cost = turnover * side_cost
            intervals.append({
                "start": ts.isoformat(),
                "end": end.isoformat(),
                "is_current_mark_to_market_interval": bool(ts == current_day),
                "gross_return": float(gross),
                "funding_return": float(funding_return),
                "turnover": turnover,
                "trading_cost_return": float(-trading_cost),
                "net_return": float(gross + funding_return - trading_cost),
            })

    returns = np.asarray([float(row["net_return"]) for row in intervals], dtype=float)
    if len(returns):
        equity = np.cumprod(1.0 + returns)
        peaks = np.maximum.accumulate(equity)
        net_return = float(equity[-1] - 1.0)
        max_drawdown = float(np.min(equity / peaks - 1.0))
    else:
        net_return = 0.0
        max_drawdown = 0.0
    completed_holding_periods = max(0, len(rebalance_events) - 1)
    minimum = int(candidate["forward_protocol"]["minimum_completed_forward_rebalances_for_edge_review"])
    first_possible = _utc(candidate["forward_protocol"]["first_possible_execution_utc"])
    if as_of < first_possible:
        status = "waiting_for_first_executable_forward_rebalance"
    elif completed_holding_periods >= minimum:
        status = "reviewable_rebalance_count_reached"
    else:
        status = "collecting"
    open_positions = int((weights.abs() > 1e-15).sum())
    return {
        "schema_version": 1,
        "experiment": "cross-sectional-forward-shadow-v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_spec_sha256": candidate["spec_sha256"],
        "candidate_file_sha256": candidate_file_sha256,
        "source_sha256": dict(source_sha256 or {}),
        "as_of_utc": as_of.isoformat(),
        "forward_signal_start_utc": candidate["forward_signal_start_utc"],
        "status": status,
        "economics": {
            "round_trip_cost_bps": cost_bps,
            "funding": "actual public MEXC funding events",
            "gross_exposure_cap": float(spec["gross_portfolio_exposure_cap"]),
            "leverage": float(spec["leverage"]),
        },
        "metrics": {
            "net_return": net_return,
            "net_pnl_per_1000_usdt": float(net_return * 1000.0),
            "max_drawdown": max_drawdown,
            "executed_rebalances": len(rebalance_events),
            "completed_holding_periods": completed_holding_periods,
            "open_symbol_positions": open_positions,
            "minimum_completed_rebalances_for_edge_review": minimum,
        },
        "current_weights": {symbol: float(weights[symbol]) for symbol in symbols},
        "rebalance_events": rebalance_events,
        "portfolio_intervals": intervals,
        "claims": {
            "candidate_specification_frozen": True,
            "paper_shadow_only": True,
            "forward_sample_minimum_reached": completed_holding_periods >= minimum,
            "visible_forward_pnl_is_statistical_proof": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

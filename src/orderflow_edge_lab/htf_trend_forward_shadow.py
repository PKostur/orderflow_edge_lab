from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import generate_target_position


class HtfTrendForwardError(ValueError):
    pass


EIGHT_HOURS = pd.Timedelta(hours=8)


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
        raise HtfTrendForwardError("candidate specification hash is invalid")
    return payload, sha256(raw).hexdigest()


def _validate_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise HtfTrendForwardError(f"{symbol}: missing OHLC columns")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise HtfTrendForwardError(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    if out.index.has_duplicates:
        raise HtfTrendForwardError(f"{symbol}: duplicate timestamps")
    for column in required:
        values = pd.to_numeric(out[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any():
            raise HtfTrendForwardError(f"{symbol}: invalid {column}")
        out[column] = values.astype(float)
    return out


def _candidate_params(candidate: Mapping[str, Any]) -> dict[str, Any]:
    spec = candidate["specification"]
    return {
        "fast": int(spec["fast_ema"]),
        "slow": int(spec["slow_ema"]),
        "atr_period": int(spec["atr_period"]),
        "min_atr_spread": float(spec["min_atr_spread"]),
    }


def build_execution_targets(
    frame: pd.DataFrame,
    candidate: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
) -> pd.Series:
    """Build positions executable only from completed 8h bars.

    A target computed from the completed candle whose open is t becomes executable
    at the next 8h bar open, t+8h. Pre-forward candles are warmup only.
    """
    as_of = _utc(as_of_utc)
    current_bar_start = as_of.floor("8h")
    start = _utc(candidate["forward_signal_start_utc"])
    clean = _validate_frame(frame, "symbol")
    closed = clean[clean.index < current_bar_start]
    if closed.empty:
        return pd.Series(dtype=float)
    raw_target = generate_target_position(closed, "ema_tsmom", _candidate_params(candidate)).clip(-1.0, 1.0)
    raw_target = raw_target[raw_target.index >= start]
    if raw_target.empty:
        return pd.Series(dtype=float)
    executable = raw_target.copy()
    executable.index = executable.index + EIGHT_HOURS
    executable = executable[executable.index <= current_bar_start]
    executable.name = "target"
    return executable.astype(float)


def _funding_between(funding: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if funding.empty or "funding_rate" not in funding.columns:
        return 0.0
    series = pd.to_numeric(funding["funding_rate"], errors="coerce").fillna(0.0)
    return float(series[(series.index > start) & (series.index <= end)].sum())


def _portfolio_stats(interval_rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in interval_rows]
    if not returns:
        return {
            "completed_or_marked_intervals": 0,
            "net_return": 0.0,
            "net_pnl_per_1000_usdt": 0.0,
            "max_drawdown": 0.0,
            "positive_interval_fraction": None,
        }
    equity = np.cumprod(1.0 + np.asarray(returns, dtype=float))
    peaks = np.maximum.accumulate(equity)
    return {
        "completed_or_marked_intervals": len(returns),
        "net_return": float(equity[-1] - 1.0),
        "net_pnl_per_1000_usdt": float((equity[-1] - 1.0) * 1000.0),
        "max_drawdown": float(np.min(equity / peaks - 1.0)),
        "positive_interval_fraction": float(np.mean(np.asarray(returns) > 0)),
    }


def _symbol_trades(
    symbol: str,
    frame: pd.DataFrame,
    target: pd.Series,
    funding: pd.DataFrame,
    *,
    cost_bps: float,
    as_of: pd.Timestamp,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if target.empty:
        return [], None
    side = 0.0
    entry_time: pd.Timestamp | None = None
    entry_price: float | None = None
    trades: list[dict[str, Any]] = []
    half_cost = float(cost_bps) / 2.0 / 10_000.0
    full_cost = float(cost_bps) / 10_000.0

    for ts, requested_value in target.sort_index().items():
        requested = float(requested_value)
        if ts not in frame.index:
            continue
        price = float(frame.loc[ts, "open"])
        if requested == side:
            continue
        if side != 0.0 and entry_time is not None and entry_price is not None:
            funding_sum = _funding_between(funding, entry_time, ts)
            gross = side * (price / entry_price - 1.0)
            funding_return = -side * funding_sum
            net = gross + funding_return - full_cost
            trades.append({
                "symbol": symbol,
                "entry_time": entry_time.isoformat(),
                "exit_time": ts.isoformat(),
                "side": "long" if side > 0 else "short",
                "entry_price": entry_price,
                "exit_price": price,
                "gross_return": float(gross),
                "funding_return": float(funding_return),
                "net_return": float(net),
                "round_trip_cost_bps": float(cost_bps),
            })
            side = 0.0
            entry_time = None
            entry_price = None
        if requested != 0.0:
            side = requested
            entry_time = ts
            entry_price = price

    if side == 0.0 or entry_time is None or entry_price is None:
        return trades, None
    current_bar_start = as_of.floor("8h")
    mark = float(frame.loc[current_bar_start, "close"]) if current_bar_start in frame.index else float(frame["close"].iloc[-1])
    funding_sum = _funding_between(funding, entry_time, as_of)
    gross = side * (mark / entry_price - 1.0)
    funding_return = -side * funding_sum
    open_net = gross + funding_return - half_cost
    return trades, {
        "symbol": symbol,
        "entry_time": entry_time.isoformat(),
        "side": "long" if side > 0 else "short",
        "entry_price": entry_price,
        "mark_price": mark,
        "as_of_utc": as_of.isoformat(),
        "gross_return": float(gross),
        "funding_return": float(funding_return),
        "entry_cost_bps": float(cost_bps) / 2.0,
        "net_mark_to_market_return_after_entry_cost": float(open_net),
    }


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
        raise HtfTrendForwardError("candidate specification hash is invalid")
    as_of = _utc(as_of_utc)
    spec = candidate["specification"]
    symbols = [str(value) for value in spec["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise HtfTrendForwardError(f"missing frozen symbols: {missing}")
    clean = {symbol: _validate_frame(frames[symbol], symbol) for symbol in symbols}
    current_bar_start = as_of.floor("8h")
    targets = {
        symbol: build_execution_targets(clean[symbol], candidate, as_of_utc=as_of)
        for symbol in symbols
    }
    execution_times = sorted({ts for series in targets.values() for ts in series.index if ts <= current_bar_start})
    cost_bps = float(spec["round_trip_cost_bps"])
    side_cost = cost_bps / 2.0 / 10_000.0
    previous_weights = pd.Series(0.0, index=symbols, dtype=float)
    interval_rows: list[dict[str, Any]] = []

    for i, ts in enumerate(execution_times):
        requested = pd.Series({
            symbol: float(targets[symbol].get(ts, previous_weights[symbol] and math.copysign(1.0, previous_weights[symbol]) or 0.0))
            for symbol in symbols
        }, dtype=float)
        active = int((requested != 0.0).sum())
        weights = requested / active if active else requested * 0.0
        turnover = float((weights - previous_weights).abs().sum())
        trading_cost = turnover * side_cost
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
            frame = clean[symbol]
            if ts not in frame.index:
                raise HtfTrendForwardError(f"{symbol}: missing execution bar {ts}")
            entry_open = float(frame.loc[ts, "open"])
            if is_current:
                mark = float(frame.loc[ts, "close"])
            else:
                if end not in frame.index:
                    raise HtfTrendForwardError(f"{symbol}: missing next execution bar {end}")
                mark = float(frame.loc[end, "open"])
            gross += weight * (mark / entry_open - 1.0)
            funding_return += -weight * _funding_between(funding.get(symbol, pd.DataFrame()), ts, end)
        net = gross + funding_return - trading_cost
        interval_rows.append({
            "start": ts.isoformat(),
            "end": end.isoformat(),
            "is_current_mark_to_market_interval": bool(is_current),
            "active_symbols": active,
            "gross_return": float(gross),
            "funding_return": float(funding_return),
            "turnover": turnover,
            "trading_cost_return": float(-trading_cost),
            "net_return": float(net),
        })
        previous_weights = weights

    completed_trades: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    for symbol in symbols:
        trades, open_position = _symbol_trades(
            symbol,
            clean[symbol],
            targets[symbol],
            funding.get(symbol, pd.DataFrame()),
            cost_bps=cost_bps,
            as_of=as_of,
        )
        completed_trades.extend(trades)
        if open_position is not None:
            open_position["portfolio_weight"] = float(previous_weights.get(symbol, 0.0))
            open_positions.append(open_position)

    stats = _portfolio_stats(interval_rows)
    minimum = int(candidate["forward_protocol"]["minimum_completed_forward_trades_for_edge_review"])
    count = len(completed_trades)
    start = _utc(candidate["forward_signal_start_utc"])
    if as_of < start + EIGHT_HOURS:
        status = "waiting_for_first_executable_forward_signal"
    elif count >= minimum:
        status = "reviewable_trade_count_reached"
    else:
        status = "collecting"
    return {
        "schema_version": 1,
        "experiment": "htf-trend-forward-shadow-v1",
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
            **stats,
            "completed_symbol_trades": count,
            "open_symbol_positions": len(open_positions),
            "minimum_completed_trades_for_edge_review": minimum,
        },
        "current_weights": {symbol: float(previous_weights[symbol]) for symbol in symbols},
        "completed_trades": sorted(completed_trades, key=lambda row: (row["exit_time"], row["symbol"])),
        "open_positions": sorted(open_positions, key=lambda row: row["symbol"]),
        "portfolio_intervals": interval_rows,
        "claims": {
            "candidate_specification_frozen": True,
            "paper_shadow_only": True,
            "forward_sample_minimum_reached": count >= minimum,
            "visible_forward_pnl_is_statistical_proof": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

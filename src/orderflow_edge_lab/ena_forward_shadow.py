from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.ena_mean_reversion_risk import _atr, _trade_stats, _validate_frame
from orderflow_edge_lab.strategy_tournament import _bollinger, _rsi, _stateful_events


class EnaForwardShadowError(ValueError):
    pass


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
        raise EnaForwardShadowError("candidate specification hash is invalid")
    return payload, sha256(raw).hexdigest()


def _timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def build_forward_target(frame: pd.DataFrame, candidate: Mapping[str, Any]) -> pd.Series:
    frame = _validate_frame(frame)
    spec = candidate["specification"]
    start = _timestamp(candidate["forward_signal_start_utc"])

    close = frame["close"].astype(float)
    mid, upper, lower, _ = _bollinger(
        close,
        int(spec["bollinger_period"]),
        float(spec["bollinger_std"]),
    )
    rsi = _rsi(close, int(spec["rsi_period"]))

    eligible = frame.index >= start
    long_entry = ((close < lower) & (rsi < float(spec["rsi_long_threshold"])))[eligible]
    short_entry = ((close > upper) & (rsi > float(spec["rsi_short_threshold"])))[eligible]
    long_exit = (close >= mid)[eligible]
    short_exit = (close <= mid)[eligible]

    target = pd.Series(0.0, index=frame.index, dtype=float)
    if eligible.any():
        forward_target = _stateful_events(
            long_entry,
            short_entry,
            long_exit,
            short_exit,
            int(spec["max_hold_bars"]),
        )
        target.loc[forward_target.index] = forward_target
    return target


def simulate_forward_shadow(
    frame: pd.DataFrame,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    if not verify_candidate_spec(candidate):
        raise EnaForwardShadowError("candidate specification hash is invalid")
    spec = candidate["specification"]
    start = _timestamp(candidate["forward_signal_start_utc"])
    if frame.index.max() < start:
        return {
            "completed_trades": [],
            "open_position": None,
            "target_position": pd.Series(0.0, index=frame.index, dtype=float),
        }

    target = build_forward_target(frame, candidate)
    desired = target.shift(1).fillna(0.0).clip(-1.0, 1.0)
    signal_atr = _atr(frame, int(spec["atr_period"])).shift(1)
    stop_multiple = float(spec["hard_stop_atr_multiple"])
    cost_fraction = float(spec["round_trip_cost_bps"]) / 10_000.0

    trades: list[dict[str, Any]] = []
    side = 0
    locked_side = 0
    entry_index: int | None = None
    entry_price: float | None = None
    atr_at_entry: float | None = None
    stop_price: float | None = None
    mae = 0.0
    mfe = 0.0

    def close_trade(exit_index: int, exit_price: float, reason: str) -> None:
        nonlocal side, entry_index, entry_price, atr_at_entry, stop_price, mae, mfe
        if side == 0 or entry_index is None or entry_price is None or atr_at_entry is None:
            raise EnaForwardShadowError("incomplete open position")
        gross = side * (float(exit_price) / entry_price - 1.0)
        trades.append(
            {
                "entry_time": frame.index[entry_index].isoformat(),
                "exit_time": frame.index[exit_index].isoformat(),
                "side": "long" if side > 0 else "short",
                "entry_price": entry_price,
                "exit_price": float(exit_price),
                "exit_reason": reason,
                "gross_return": float(gross),
                "net_return": float(gross - cost_fraction),
                "atr_at_entry": atr_at_entry,
                "stop_price": stop_price,
                "mae_bps": float(mae * 10_000.0),
                "mfe_bps": float(mfe * 10_000.0),
                "mae_atr": float(mae * entry_price / atr_at_entry),
                "mfe_atr": float(mfe * entry_price / atr_at_entry),
            }
        )
        side = 0
        entry_index = None
        entry_price = None
        atr_at_entry = None
        stop_price = None
        mae = 0.0
        mfe = 0.0

    for index, (_, row) in enumerate(frame.iterrows()):
        requested = int(desired.iloc[index])
        if locked_side and requested != locked_side:
            locked_side = 0

        if side and requested != side:
            previous_side = side
            close_trade(index, float(row["open"]), "signal_exit")
            if requested == -previous_side:
                locked_side = 0

        if side == 0 and requested and requested != locked_side:
            candidate_atr = signal_atr.iloc[index]
            if (
                frame.index[index] > start
                and pd.notna(candidate_atr)
                and float(candidate_atr) > 0
            ):
                side = requested
                entry_index = index
                entry_price = float(row["open"])
                atr_at_entry = float(candidate_atr)
                stop_price = entry_price - side * atr_at_entry * stop_multiple
                mae = 0.0
                mfe = 0.0

        if side == 0 or entry_price is None or atr_at_entry is None or stop_price is None:
            continue

        if side > 0:
            adverse = float(row["low"]) / entry_price - 1.0
            favorable = float(row["high"]) / entry_price - 1.0
            stop_hit = float(row["low"]) <= stop_price
        else:
            adverse = -(float(row["high"]) / entry_price - 1.0)
            favorable = -(float(row["low"]) / entry_price - 1.0)
            stop_hit = float(row["high"]) >= stop_price
        mae = min(mae, adverse)
        mfe = max(mfe, favorable)

        if stop_hit:
            exit_side = side
            close_trade(index, stop_price, "stop")
            locked_side = exit_side

    open_position = None
    if side and entry_price is not None and entry_index is not None and atr_at_entry is not None:
        mark = float(frame["close"].iloc[-1])
        gross = side * (mark / entry_price - 1.0)
        open_position = {
            "entry_time": frame.index[entry_index].isoformat(),
            "side": "long" if side > 0 else "short",
            "entry_price": entry_price,
            "atr_at_entry": atr_at_entry,
            "stop_price": stop_price,
            "last_closed_bar_time": frame.index[-1].isoformat(),
            "mark_price": mark,
            "unrealized_gross_return": float(gross),
            "mae_bps": float(mae * 10_000.0),
            "mfe_bps": float(mfe * 10_000.0),
        }

    return {
        "completed_trades": trades,
        "open_position": open_position,
        "target_position": target,
    }


def build_forward_report(
    frame: pd.DataFrame,
    candidate: Mapping[str, Any],
    *,
    candidate_file_sha256: str | None = None,
    source_sha256: str | None = None,
    as_of_utc: str | pd.Timestamp | None = None,
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    simulated = simulate_forward_shadow(frame, candidate)
    trades = simulated["completed_trades"]
    stats = _trade_stats(trades)
    minimum = int(candidate["forward_protocol"]["minimum_completed_forward_trades_for_any_edge_review"])
    count = int(stats["trades"])
    status = "reviewable_sample_reached" if count >= minimum else "collecting"
    if frame.index.max() < _timestamp(candidate["forward_signal_start_utc"]):
        status = "waiting_for_first_closed_forward_bar"
    claims = {
        "candidate_specification_frozen": True,
        "paper_shadow_only": True,
        "forward_sample_minimum_reached": count >= minimum,
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
        "live_order_transmission_supported": False,
    }
    return {
        "schema_version": 1,
        "experiment": "ena-forward-shadow-v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_spec_sha256": candidate["spec_sha256"],
        "candidate_file_sha256": candidate_file_sha256,
        "source_sha256": source_sha256,
        "as_of_utc": _timestamp(as_of_utc or pd.Timestamp.now(tz="UTC")).isoformat(),
        "forward_signal_start_utc": candidate["forward_signal_start_utc"],
        "last_closed_candle_open_time": frame.index.max().isoformat(),
        "status": status,
        "minimum_completed_forward_trades_for_review": minimum,
        "metrics": stats,
        "completed_trades": trades,
        "open_position": simulated["open_position"],
        "claims": claims,
    }

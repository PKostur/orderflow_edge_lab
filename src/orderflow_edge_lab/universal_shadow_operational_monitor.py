from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_backtest import legacy_strategy


class UniversalShadowOperationalMonitorError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _clean_frame(frame: pd.DataFrame, symbol: str, boundary: pd.Timestamp) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise UniversalShadowOperationalMonitorError(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise UniversalShadowOperationalMonitorError(f"{symbol}: duplicate timestamps")
    required = {"open", "high", "low", "close"}
    if not required.issubset(out.columns):
        raise UniversalShadowOperationalMonitorError(f"{symbol}: missing OHLC columns")
    out = out[out.index <= boundary]
    if len(out) < 100:
        raise UniversalShadowOperationalMonitorError(f"{symbol}: insufficient warmup")
    return out


def _last_change(position: pd.Series, at_or_before: pd.Timestamp) -> pd.Timestamp | None:
    s = position[position.index <= at_or_before].astype(float)
    if s.empty:
        return None
    changed = s.ne(s.shift(1).fillna(0.0))
    points = s.index[changed]
    return points[-1] if len(points) else None


def _symbol_state(
    position: pd.Series,
    *,
    start: pd.Timestamp,
    boundary: pd.Timestamp,
    symbol: str,
) -> dict[str, Any]:
    s = position[position.index <= boundary].astype(float)
    if s.empty:
        raise UniversalShadowOperationalMonitorError(f"{symbol}: no executable positions")
    current = float(s.iloc[-1])
    if not np.isfinite(current):
        raise UniversalShadowOperationalMonitorError(f"{symbol}: non-finite position")
    last_change = _last_change(s, boundary)
    post_start_changes = s[
        (s.index >= start) & s.ne(s.shift(1).fillna(0.0))
    ]
    change_rows = [
        {
            "entry_boundary_utc": ts.isoformat(),
            "executed_position": float(value),
        }
        for ts, value in post_start_changes.items()
    ]
    position_age_hours = (
        (boundary - last_change).total_seconds() / 3600.0
        if last_change is not None
        else None
    )
    return {
        "symbol": symbol,
        "current_executed_position": current,
        "current_side": "LONG" if current > 0 else "SHORT" if current < 0 else "FLAT",
        "last_position_change_utc": last_change.isoformat() if last_change is not None else None,
        "position_age_hours": position_age_hours,
        "post_start_position_change_count": len(change_rows),
        "post_start_position_changes": change_rows,
        "carried_pre_start_position": bool(
            current != 0.0 and last_change is not None and last_change < start
        ),
        "flat_without_post_start_change": bool(
            current == 0.0 and len(change_rows) == 0
        ),
    }


def build_operational_monitor(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of = _utc(as_of_utc)
    interval = str(config["source"]["interval"])
    if interval != "8h":
        raise UniversalShadowOperationalMonitorError("v1 monitor requires frozen 8h interval")
    boundary = as_of.floor("8h")
    symbols = [str(value) for value in config["source"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise UniversalShadowOperationalMonitorError(f"missing symbol frames: {missing}")

    boundary_count = max(
        0,
        int((boundary - start) / pd.Timedelta(hours=8)) + (1 if boundary >= start else 0),
    )

    strategies: list[dict[str, Any]] = []
    for variant in config["variants"]:
        audit_id = str(variant["audit_id"])
        strategy = legacy_strategy(str(variant["family"]))
        params = dict(variant["parameters"])
        symbol_rows: list[dict[str, Any]] = []
        for symbol in symbols:
            frame = _clean_frame(frames[symbol], symbol, boundary)
            target = (
                strategy.generate_target(frame, params, None)
                .reindex(frame.index)
                .fillna(0.0)
                .astype(float)
            )
            if not np.isfinite(target.to_numpy(dtype=float)).all():
                raise UniversalShadowOperationalMonitorError(
                    f"{audit_id}/{symbol}: non-finite target"
                )
            position = target.shift(1).fillna(0.0)
            symbol_rows.append(
                _symbol_state(
                    position,
                    start=start,
                    boundary=boundary,
                    symbol=symbol,
                )
            )

        position_ages = [
            float(row["position_age_hours"])
            for row in symbol_rows
            if row["position_age_hours"] is not None
        ]
        current_positions = [float(row["current_executed_position"]) for row in symbol_rows]
        strategies.append(
            {
                "audit_id": audit_id,
                "family": variant["family"],
                "parameters": params,
                "current_nonzero_symbol_count": sum(value != 0.0 for value in current_positions),
                "current_long_symbol_count": sum(value > 0.0 for value in current_positions),
                "current_short_symbol_count": sum(value < 0.0 for value in current_positions),
                "current_flat_symbol_count": sum(value == 0.0 for value in current_positions),
                "net_position_sum": float(sum(current_positions)),
                "gross_position_sum": float(sum(abs(value) for value in current_positions)),
                "long_symbol_fraction": (
                    sum(value > 0.0 for value in current_positions) / len(current_positions)
                    if current_positions else 0.0
                ),
                "median_position_age_hours": (
                    float(np.median(position_ages)) if position_ages else None
                ),
                "max_position_age_hours": max(position_ages) if position_ages else None,
                "min_position_age_hours": min(position_ages) if position_ages else None,
                "carried_pre_start_position_count": sum(
                    row["carried_pre_start_position"] for row in symbol_rows
                ),
                "flat_without_post_start_change_count": sum(
                    row["flat_without_post_start_change"] for row in symbol_rows
                ),
                "post_start_position_change_count": sum(
                    int(row["post_start_position_change_count"]) for row in symbol_rows
                ),
                "symbols_with_post_start_change": [
                    row["symbol"]
                    for row in symbol_rows
                    if row["post_start_position_change_count"] > 0
                ],
                "per_symbol": symbol_rows,
            }
        )

    return {
        "schema_version": 1,
        "analysis": "universal_shadow_operational_monitor_v1",
        "watch_id": str(config["watch_id"]),
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "latest_execution_boundary_utc": boundary.isoformat(),
        "execution_boundaries_since_start_including_start": boundary_count,
        "strategies": strategies,
        "claims": {
            "operational_only": True,
            "not_prospective_evidence": True,
            "does_not_change_frozen_shadow": True,
            "does_not_change_strategy_rules": True,
            "does_not_affect_jev_v1_decision_contract": True,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }

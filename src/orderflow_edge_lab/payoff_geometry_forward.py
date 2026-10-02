from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import enrich_trade_geometry
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    legacy_strategy,
    run_canonical_backtest,
)


class PayoffGeometryForwardError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _validate_frame(
    frame: pd.DataFrame,
    symbol: str,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise PayoffGeometryForwardError(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise PayoffGeometryForwardError(f"{symbol}: duplicate timestamps")
    required = {"open", "high", "low", "close"}
    if not required.issubset(out.columns):
        raise PayoffGeometryForwardError(f"{symbol}: missing OHLC columns")
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    values = out[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise PayoffGeometryForwardError(f"{symbol}: invalid OHLC values")
    out = out[out.index <= as_of.floor("8h")]
    if len(out) < 100:
        raise PayoffGeometryForwardError(f"{symbol}: insufficient warmup bars")
    return out


def _quantiles(
    values: Sequence[float],
    quantiles: Sequence[float],
) -> dict[str, float | None]:
    clean = np.asarray(
        [float(v) for v in values if v is not None and math.isfinite(float(v))],
        dtype=float,
    )
    return {
        f"p{int(round(float(q) * 100)):02d}": (
            float(np.quantile(clean, float(q))) if len(clean) else None
        )
        for q in quantiles
    }


def _values(rows: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            values.append(number)
    return values


def _summary(
    rows: Sequence[Mapping[str, Any]],
    quantiles: Sequence[float],
) -> dict[str, Any]:
    net = _values(rows, "net_bps")
    gross = _values(rows, "gross_bps")
    mfe = _values(rows, "mfe_bps")
    mae = _values(rows, "abs_mae_bps")
    capture = _values(rows, "gross_to_mfe_ratio")
    winner_capture = _values(rows, "winner_gross_to_mfe_ratio")
    t_mfe = _values(rows, "time_to_mfe_hours")
    return {
        "completed_trade_count": len(rows),
        "observed_symbols": sorted({str(row["symbol"]) for row in rows}),
        "observed_symbol_count": len({str(row["symbol"]) for row in rows}),
        "expectancy_bps": statistics.fmean(net) if net else None,
        "win_rate": (
            sum(value > 0.0 for value in net) / len(net) if net else None
        ),
        "correct_direction_rate": (
            sum(float(row["gross_bps"]) > 0.0 for row in rows) / len(rows)
            if rows
            else None
        ),
        "median_mfe_bps": statistics.median(mfe) if mfe else None,
        "median_abs_mae_bps": statistics.median(mae) if mae else None,
        "median_gross_to_mfe_ratio": (
            statistics.median(capture) if capture else None
        ),
        "median_winner_gross_to_mfe_ratio": (
            statistics.median(winner_capture) if winner_capture else None
        ),
        "median_time_to_mfe_hours": statistics.median(t_mfe) if t_mfe else None,
        "distributions": {
            field: _quantiles(_values(rows, field), quantiles)
            for field in (
                "net_bps",
                "gross_bps",
                "mfe_bps",
                "abs_mae_bps",
                "gross_to_mfe_ratio",
                "winner_gross_to_mfe_ratio",
                "time_to_mfe_hours",
            )
        },
    }


def _difference(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    field: str,
) -> float | None:
    a = left.get(field)
    b = right.get(field)
    if a is None or b is None:
        return None
    return float(a) - float(b)


def build_payoff_geometry_forward_report(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of = _utc(as_of_utc)
    symbols = [str(value) for value in config["source"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise PayoffGeometryForwardError(f"missing frozen symbol frames: {missing}")
    clean = {
        symbol: _validate_frame(frames[symbol], symbol, as_of)
        for symbol in symbols
    }
    btc = clean.get("BTC_USDT")
    if btc is None:
        raise PayoffGeometryForwardError("BTC_USDT is required")

    cost = float(config["economics"]["round_trip_cost_bps"])
    vol_cfg = dict(config["volatility_state"])
    quantiles = [0.10, 0.25, 0.50, 0.75, 0.90]
    gate = config["review_gate"]
    days_elapsed = (
        max(0, int((as_of - start).total_seconds() // 86_400.0))
        if as_of >= start
        else 0
    )

    reports: list[dict[str, Any]] = []
    for spec in config["strategies"]:
        audit_id = str(spec["audit_id"])
        strategy = legacy_strategy(str(spec["family"]))
        params = dict(spec["parameters"])
        completed: list[dict[str, Any]] = []
        open_snapshots: list[dict[str, Any]] = []

        for symbol in symbols:
            canonical = run_canonical_backtest(
                clean[symbol],
                strategy,
                params,
                ExecutionModel(
                    round_trip_cost_bps=cost,
                    max_abs_position=float(
                        config["economics"].get("maximum_absolute_position", 1.0)
                    ),
                ),
            )
            for trade in canonical.get("trades_ledger") or []:
                entry = _utc(trade["entry"])
                if entry < start:
                    continue
                row = enrich_trade_geometry(
                    trade,
                    clean[symbol],
                    strategy_id=audit_id,
                    symbol=symbol,
                    cost_bps=cost,
                    btc_frame=btc,
                    volatility_config=vol_cfg,
                )
                if bool(trade.get("terminal_liquidation")):
                    open_snapshots.append(row)
                else:
                    completed.append(row)

        states = {
            state: _summary(
                [
                    row
                    for row in completed
                    if str(row["pre_entry_volatility_state"]) == state
                ],
                quantiles,
            )
            for state in ("LOW", "MID", "HIGH", "UNKNOWN")
        }
        total = _summary(completed, quantiles)
        high = states["HIGH"]
        low = states["LOW"]
        ready = (
            days_elapsed >= int(gate["minimum_calendar_days"])
            and len(completed)
            >= int(gate["minimum_completed_post_start_trades_per_strategy"])
            and int(high["completed_trade_count"])
            >= int(gate["minimum_completed_HIGH_trades_per_strategy"])
            and int(low["completed_trade_count"])
            >= int(gate["minimum_completed_LOW_trades_per_strategy"])
        )
        reports.append(
            {
                "audit_id": audit_id,
                "family": spec["family"],
                "parameters": params,
                "summary": total,
                "state_summaries": states,
                "high_minus_low": {
                    "median_mfe_bps": _difference(
                        high, low, "median_mfe_bps"
                    ),
                    "median_abs_mae_bps": _difference(
                        high, low, "median_abs_mae_bps"
                    ),
                    "median_gross_to_mfe_ratio": _difference(
                        high, low, "median_gross_to_mfe_ratio"
                    ),
                    "median_time_to_mfe_hours": _difference(
                        high, low, "median_time_to_mfe_hours"
                    ),
                    "correct_direction_rate": _difference(
                        high, low, "correct_direction_rate"
                    ),
                    "expectancy_bps": _difference(
                        high, low, "expectancy_bps"
                    ),
                },
                "open_terminal_snapshots_not_scored": sorted(
                    (
                        {k: v for k, v in row.items() if not str(k).startswith("_")}
                        for row in open_snapshots
                    ),
                    key=lambda row: (str(row["entry"]), str(row["symbol"])),
                ),
                "sample_progress": {
                    "calendar_days_elapsed": days_elapsed,
                    "calendar_day_requirement": int(
                        gate["minimum_calendar_days"]
                    ),
                    "completed_trade_count": len(completed),
                    "completed_trade_requirement": int(
                        gate["minimum_completed_post_start_trades_per_strategy"]
                    ),
                    "HIGH_completed_trade_count": int(
                        high["completed_trade_count"]
                    ),
                    "HIGH_trade_requirement": int(
                        gate["minimum_completed_HIGH_trades_per_strategy"]
                    ),
                    "LOW_completed_trade_count": int(
                        low["completed_trade_count"]
                    ),
                    "LOW_trade_requirement": int(
                        gate["minimum_completed_LOW_trades_per_strategy"]
                    ),
                    "open_terminal_snapshot_count": len(open_snapshots),
                    "ready_for_review": ready,
                },
                "formal_verdict": "WITHHELD",
            }
        )

    if as_of < start:
        status = "PRE_START"
    elif reports and all(
        bool(row["sample_progress"]["ready_for_review"]) for row in reports
    ):
        status = "READY_FOR_REVIEW"
    else:
        status = "ACCUMULATING"

    return {
        "schema_version": 1,
        "analysis": "payoff_geometry_forward_v1",
        "watch_id": config["watch_id"],
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "calendar_days_elapsed": days_elapsed,
        "status": status,
        "hypothesis_provenance": config["hypothesis_provenance"],
        "primary_hypotheses": config["primary_hypotheses"],
        "review_gate": gate,
        "reports": reports,
        "claims": {
            "historical_source_result_counted_as_forward_evidence": False,
            "volatility_labels_are_observational_only": True,
            "original_trade_generation_unchanged": True,
            "formal_verdict_withheld_until_review_gate": True,
            "volatility_filter_authorized": False,
            "candidate_promoted": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }

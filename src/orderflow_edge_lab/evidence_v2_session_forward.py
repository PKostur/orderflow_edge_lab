from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import generate_target_position


class EvidenceSessionForwardError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _bucket_name(hour: int, buckets: list[Mapping[str, Any]]) -> str:
    for bucket in buckets:
        start = int(bucket["start_utc_hour"])
        end = int(bucket["end_utc_hour"])
        if start <= hour < end:
            return str(bucket["name"])
    raise EvidenceSessionForwardError(f"hour {hour} is outside declared session buckets")


def _max_drawdown(returns: list[float]) -> float:
    if not returns:
        return 0.0
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "intervals": 0,
            "compounded_return": 0.0,
            "cumulative_simple_bps": 0.0,
            "mean_interval_bps": None,
            "median_interval_bps": None,
            "positive_interval_fraction": None,
            "max_drawdown": 0.0,
            "turnover_cost_bps": 0.0,
            "long_gross_contribution_bps": 0.0,
            "short_gross_contribution_bps": 0.0,
            "per_symbol_net_contribution_bps": {},
        }
    values = [float(row["portfolio_net_return"]) for row in rows]
    equity = 1.0
    for value in values:
        equity *= 1.0 + value
    symbol_totals: dict[str, float] = {}
    for row in rows:
        for symbol, value in row["symbol_net_contribution_bps"].items():
            symbol_totals[symbol] = symbol_totals.get(symbol, 0.0) + float(value)
    return {
        "intervals": len(rows),
        "first_interval_start_utc": rows[0]["start"],
        "last_interval_start_utc": rows[-1]["start"],
        "compounded_return": equity - 1.0,
        "cumulative_simple_bps": sum(values) * 10_000.0,
        "mean_interval_bps": statistics.fmean(values) * 10_000.0,
        "median_interval_bps": statistics.median(values) * 10_000.0,
        "positive_interval_fraction": sum(v > 0.0 for v in values) / len(values),
        "max_drawdown": _max_drawdown(values),
        "turnover_cost_bps": sum(float(r["portfolio_turnover_cost_bps"]) for r in rows),
        "long_gross_contribution_bps": sum(float(r["portfolio_long_gross_bps"]) for r in rows),
        "short_gross_contribution_bps": sum(float(r["portfolio_short_gross_bps"]) for r in rows),
        "per_symbol_net_contribution_bps": dict(sorted(symbol_totals.items())),
    }


def _validate_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = frame.copy().sort_index()
    if not isinstance(out.index, pd.DatetimeIndex):
        raise EvidenceSessionForwardError(f"{symbol}: index must be DatetimeIndex")
    out.index = pd.to_datetime(out.index, utc=True)
    required = {"open", "high", "low", "close"}
    if not required.issubset(out.columns):
        raise EvidenceSessionForwardError(f"{symbol}: missing OHLC columns")
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if out[list(required)].isna().any().any():
        raise EvidenceSessionForwardError(f"{symbol}: invalid OHLC values")
    if (out[list(required)] <= 0.0).any().any():
        raise EvidenceSessionForwardError(f"{symbol}: non-positive OHLC")
    return out


def _variant_intervals(
    frames: Mapping[str, pd.DataFrame],
    *,
    family: str,
    params: Mapping[str, Any],
    symbols: list[str],
    prospective_start: pd.Timestamp,
    as_of: pd.Timestamp,
    round_trip_cost_bps: float,
    buckets: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    clean: dict[str, pd.DataFrame] = {}
    positions: dict[str, pd.Series] = {}
    common: pd.DatetimeIndex | None = None
    for symbol in symbols:
        if symbol not in frames:
            raise EvidenceSessionForwardError(f"missing symbol frame: {symbol}")
        frame = _validate_frame(frames[symbol], symbol)
        clean[symbol] = frame
        target = generate_target_position(frame, family, params).reindex(frame.index).fillna(0.0).clip(-1.0, 1.0)
        positions[symbol] = target.shift(1).fillna(0.0)
        common = frame.index if common is None else common.intersection(frame.index)
    if common is None or len(common) < 2:
        return []
    common = common.sort_values()

    side_cost = float(round_trip_cost_bps) / 2.0 / 10_000.0
    sleeve = 1.0 / len(symbols)
    rows: list[dict[str, Any]] = []

    for pos_idx in range(len(common) - 1):
        start = common[pos_idx]
        end = common[pos_idx + 1]
        if start < prospective_start or end > as_of:
            continue

        symbol_net_bps: dict[str, float] = {}
        portfolio_net = 0.0
        portfolio_cost_bps = 0.0
        long_gross_bps = 0.0
        short_gross_bps = 0.0
        active = 0

        for symbol in symbols:
            frame = clean[symbol]
            position = positions[symbol]
            if start not in frame.index or end not in frame.index:
                raise EvidenceSessionForwardError(f"{symbol}: missing common interval boundary")
            current = float(position.loc[start])
            prev_loc = position.index.get_loc(start)
            previous = float(position.iloc[prev_loc - 1]) if isinstance(prev_loc, int) and prev_loc > 0 else 0.0
            gross = current * (float(frame.at[end, "open"]) / float(frame.at[start, "open"]) - 1.0)
            turnover = abs(current - previous)
            cost = turnover * side_cost
            net = gross - cost

            weighted_net = sleeve * net
            portfolio_net += weighted_net
            portfolio_cost_bps += sleeve * cost * 10_000.0
            symbol_net_bps[symbol] = weighted_net * 10_000.0
            if current > 0.0:
                long_gross_bps += sleeve * gross * 10_000.0
                active += 1
            elif current < 0.0:
                short_gross_bps += sleeve * gross * 10_000.0
                active += 1

        rows.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "session_bucket": _bucket_name(int(start.hour), buckets),
                "portfolio_net_return": portfolio_net,
                "portfolio_turnover_cost_bps": portfolio_cost_bps,
                "portfolio_long_gross_bps": long_gross_bps,
                "portfolio_short_gross_bps": short_gross_bps,
                "active_symbol_count": active,
                "symbol_net_contribution_bps": symbol_net_bps,
            }
        )
    return rows


def build_forward_session_report(
    config: Mapping[str, Any],
    *,
    frames_by_interval: Mapping[str, Mapping[str, pd.DataFrame]],
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of = _utc(as_of_utc)
    symbols = [str(x) for x in config["source"]["symbols"]]
    buckets = list(config["session_buckets"])
    cost = float(config["economics"]["round_trip_cost_bps"])

    if as_of < start:
        status = "PRE_START"
    else:
        days = max(0, int((as_of - start) / pd.Timedelta(days=1)))
        review_days = int(config["reporting"]["review_after_calendar_days"])
        status = "READY_FOR_REVIEW" if days >= review_days else "ACCUMULATING"

    reports: list[dict[str, Any]] = []
    for variant in config["variants"]:
        interval = str(variant["interval"])
        frames = frames_by_interval.get(interval)
        if frames is None:
            raise EvidenceSessionForwardError(f"missing frames for interval {interval}")
        rows = _variant_intervals(
            frames,
            family=str(variant["family"]),
            params=variant["parameters"],
            symbols=symbols,
            prospective_start=start,
            as_of=as_of,
            round_trip_cost_bps=cost,
            buckets=buckets,
        )
        by_bucket = []
        for bucket in buckets:
            name = str(bucket["name"])
            subset = [r for r in rows if r["session_bucket"] == name]
            by_bucket.append({"session_bucket": name, **_summary(subset)})

        reports.append(
            {
                "audit_id": variant["audit_id"],
                "family": variant["family"],
                "interval": interval,
                "parameters": variant["parameters"],
                "role": variant["role"],
                "all_intervals": _summary(rows),
                "by_session_bucket": by_bucket,
                "interval_rows": rows,
            }
        )

    primary = config["primary_hypothesis"]
    primary_report = next((r for r in reports if r["audit_id"] == primary["strategy"]), None)
    primary_observation = None
    if primary_report is not None:
        cells = {r["session_bucket"]: r for r in primary_report["by_session_bucket"]}
        london = cells.get("LONDON_PLUS_OVERLAP_08_16")
        asia = cells.get("ASIA_00_08")
        if london and asia:
            primary_observation = {
                "london_cumulative_simple_bps": london["cumulative_simple_bps"],
                "asia_cumulative_simple_bps": asia["cumulative_simple_bps"],
                "london_minus_asia_simple_bps": london["cumulative_simple_bps"] - asia["cumulative_simple_bps"],
                "london_compounded_return": london["compounded_return"],
                "asia_compounded_return": asia["compounded_return"],
                "formal_verdict_withheld_until_review": True,
            }

    return {
        "schema_version": 1,
        "analysis": "evidence_v2_cross_strategy_session_forward_v1",
        "watch_id": config["watch_id"],
        "status": status,
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "days_elapsed": max(0, int((as_of - start) / pd.Timedelta(days=1))) if as_of >= start else 0,
        "economics": config["economics"],
        "session_buckets": config["session_buckets"],
        "reports": reports,
        "primary_hypothesis": primary,
        "primary_observation": primary_observation,
        "claims": config["claims"],
    }


def load_config(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceSessionForwardError("config must be a JSON object")
    return payload

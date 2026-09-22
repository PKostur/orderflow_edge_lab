from __future__ import annotations

import statistics
from typing import Any, Mapping

import pandas as pd


BUCKETS = [
    ("ASIA_00_08", 0, 8),
    ("LONDON_PLUS_OVERLAP_08_16", 8, 16),
    ("NY_POST_PLUS_LATE_16_24", 16, 24),
]


class DailyPortfolioSessionError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _funding_between(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    series = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0)
    return float(series[(series.index > start) & (series.index <= end)].sum())


def _weights_for(report: Mapping[str, Any], ts: pd.Timestamp, symbols: list[str]) -> pd.Series:
    weights = pd.Series(0.0, index=symbols, dtype=float)
    for event in report.get("rebalance_events", []):
        if _utc(event["execution_time"]) <= ts:
            weights = pd.Series(event["weights"], dtype=float).reindex(symbols, fill_value=0.0)
    return weights


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"observations": 0}
    wins = [v for v in values if v > 0.0]
    losses = [v for v in values if v <= 0.0]
    positive = sum(wins)
    negative = -sum(v for v in values if v < 0.0)
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return {
        "observations": len(values),
        "cumulative_contribution_bps": sum(values),
        "mean_contribution_bps": statistics.fmean(values),
        "median_contribution_bps": statistics.median(values),
        "positive_fraction": len(wins) / len(values),
        "profit_factor": positive / negative if negative > 0.0 else ("INF" if positive > 0.0 else None),
        "max_drawdown_bps": worst,
        "largest_positive_interval_share": max(wins) / positive if wins and positive > 0.0 else None,
    }


def build_daily_portfolio_session_report(
    report: Mapping[str, Any],
    *,
    bars_8h: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    symbols = list(report.get("current_weights", {}).keys())
    if not symbols:
        raise DailyPortfolioSessionError("report has no portfolio symbols")

    clean: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        if symbol not in bars_8h:
            raise DailyPortfolioSessionError(f"missing 8h bars for {symbol}")
        frame = bars_8h[symbol].copy().sort_index()
        frame.index = pd.to_datetime(frame.index, utc=True)
        if "open" not in frame.columns:
            raise DailyPortfolioSessionError(f"{symbol}: 8h frame missing open")
        clean[symbol] = frame

    bucket_rows: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in BUCKETS}
    reconciliation = []
    for interval in report.get("portfolio_intervals", []):
        if bool(interval.get("is_current_mark_to_market_interval")):
            continue
        start = _utc(interval["start"])
        end = _utc(interval["end"])
        if end - start != pd.Timedelta(days=1):
            continue
        weights = _weights_for(report, start, symbols)
        reconstructed_gross = 0.0
        reconstructed_funding = 0.0

        for name, h0, h1 in BUCKETS:
            b0 = start + pd.Timedelta(hours=h0)
            b1 = start + pd.Timedelta(hours=h1)
            price = 0.0
            fund = 0.0
            for symbol in symbols:
                weight = float(weights[symbol])
                if abs(weight) < 1e-15:
                    continue
                frame = clean[symbol]
                if start not in frame.index or b0 not in frame.index or b1 not in frame.index:
                    raise DailyPortfolioSessionError(f"{symbol}: missing 8h boundary for {start}")
                entry = float(frame.at[start, "open"])
                p0 = float(frame.at[b0, "open"])
                p1 = float(frame.at[b1, "open"])
                price += weight * ((p1 - p0) / entry)
                f = funding.get(symbol, pd.DataFrame()).copy()
                if not f.empty:
                    f.index = pd.to_datetime(f.index, utc=True)
                fund += -weight * _funding_between(f, b0, b1)
            reconstructed_gross += price
            reconstructed_funding += fund
            bucket_rows[name].append({
                "date_utc": start.date().isoformat(),
                "price_contribution_bps": price * 10_000.0,
                "funding_contribution_bps": fund * 10_000.0,
                "gross_plus_funding_contribution_bps": (price + fund) * 10_000.0,
            })

        gross_error = reconstructed_gross - float(interval["gross_return"])
        funding_error = reconstructed_funding - float(interval["funding_return"])
        reconciliation.append({
            "date_utc": start.date().isoformat(),
            "gross_error_bps": gross_error * 10_000.0,
            "funding_error_bps": funding_error * 10_000.0,
            "trading_cost_bps_unallocated": float(interval.get("trading_cost_return", 0.0)) * 10_000.0,
        })

    metrics = {}
    for name, rows in bucket_rows.items():
        values = [float(r["gross_plus_funding_contribution_bps"]) for r in rows]
        metrics[name] = {**_summary(values), "path": rows}

    max_gross_error = max((abs(float(r["gross_error_bps"])) for r in reconciliation), default=0.0)
    max_funding_error = max((abs(float(r["funding_error_bps"])) for r in reconciliation), default=0.0)
    return {
        "schema_version": 1,
        "analysis": "daily_portfolio_additive_session_attribution",
        "candidate_id": report.get("candidate_id"),
        "as_of_utc": report.get("as_of_utc"),
        "bucket_semantics": {name: f"{h0:02d}:00-{h1:02d}:00 UTC" for name, h0, h1 in BUCKETS},
        "metrics": metrics,
        "reconciliation": {
            "completed_daily_intervals": len(reconciliation),
            "max_abs_gross_error_bps": max_gross_error,
            "max_abs_funding_error_bps": max_funding_error,
            "passed": max_gross_error <= 1e-6 and max_funding_error <= 1e-6,
            "rows": reconciliation,
        },
        "transaction_cost_policy": "rebalance transaction costs remain separate and are not assigned to a session bucket",
        "claims": {
            "observational_only": True,
            "strategy_definition_unchanged": True,
            "session_filter_promoted": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }

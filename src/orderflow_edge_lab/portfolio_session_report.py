from __future__ import annotations

import math
import statistics
from typing import Any, Mapping


BUCKETS = {
    0: "ASIA_00_08",
    8: "LONDON_PLUS_OVERLAP_08_16",
    16: "NY_POST_PLUS_LATE_16_24",
}


class PortfolioSessionReportError(ValueError):
    pass


def _profit_factor(values: list[float]) -> float | str | None:
    positive = sum(v for v in values if v > 0.0)
    negative = -sum(v for v in values if v < 0.0)
    if negative > 0.0:
        return positive / negative
    return "INF" if positive > 0.0 else None


def _max_drawdown(values: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return worst


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(r["net_bps"]) for r in rows]
    gross = [float(r["gross_bps"]) for r in rows]
    if not values:
        return {"observations": 0}
    winners = [v for v in values if v > 0.0]
    losers = [v for v in values if v <= 0.0]
    cumulative = 0.0
    path = []
    for row in rows:
        cumulative += float(row["net_bps"])
        path.append({
            "start": row["start"],
            "net_bps": float(row["net_bps"]),
            "cumulative_net_bps": cumulative,
        })
    positive_total = sum(winners)
    ranked = sorted(winners, reverse=True)
    return {
        "observations": len(values),
        "cumulative_net_bps": sum(values),
        "net_mean_bps": statistics.fmean(values),
        "net_median_bps": statistics.median(values),
        "gross_mean_bps": statistics.fmean(gross),
        "win_rate": len(winners) / len(values),
        "average_net_win_bps": statistics.fmean(winners) if winners else None,
        "average_net_loss_bps": statistics.fmean(losers) if losers else None,
        "profit_factor": _profit_factor(values),
        "max_drawdown_bps": _max_drawdown(values),
        "largest_positive_interval_share": (
            ranked[0] / positive_total if ranked and positive_total > 0.0 else None
        ),
        "path": path,
    }


def _parse_start_hour(text: str) -> int:
    # ISO timestamps in the forward reports are UTC-aware.
    try:
        return int(str(text)[11:13])
    except (TypeError, ValueError, IndexError) as exc:
        raise PortfolioSessionReportError(f"invalid interval start: {text!r}") from exc


def _single_report(report: Mapping[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in BUCKETS.values()}
    skipped = 0
    for source in report.get("portfolio_intervals", []):
        if not isinstance(source, Mapping):
            continue
        if bool(source.get("is_current_mark_to_market_interval")):
            continue
        hour = _parse_start_hour(str(source.get("start")))
        bucket = BUCKETS.get(hour)
        if bucket is None:
            skipped += 1
            continue
        grouped[bucket].append({
            "start": str(source["start"]),
            "net_bps": float(source["net_return"]) * 10_000.0,
            "gross_bps": float(source.get("gross_return", source["net_return"])) * 10_000.0,
        })

    return {
        "candidate_id": report.get("candidate_id") or report.get("shadow_candidate_id"),
        "base_candidate_id": report.get("base_candidate_id"),
        "status": report.get("status"),
        "as_of_utc": report.get("as_of_utc"),
        "completed_interval_rows_skipped_outside_fixed_8h_boundaries": skipped,
        "buckets": {name: _summarize(rows) for name, rows in grouped.items()},
    }


def build_portfolio_session_report(report: Mapping[str, Any]) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    if isinstance(report.get("reports"), Mapping):
        for key, value in report["reports"].items():
            if isinstance(value, Mapping) and value.get("portfolio_intervals") is not None:
                reports[str(key)] = _single_report(value)
    elif report.get("portfolio_intervals") is not None:
        key = str(report.get("candidate_id") or report.get("shadow_candidate_id") or "strategy")
        reports[key] = _single_report(report)
    else:
        raise PortfolioSessionReportError("report contains no portfolio_intervals")

    return {
        "schema_version": 1,
        "analysis": "coarse_crypto_8h_session_bucket_economics",
        "bucket_semantics": {
            "ASIA_00_08": "00:00-08:00 UTC",
            "LONDON_PLUS_OVERLAP_08_16": "08:00-16:00 UTC",
            "NY_POST_PLUS_LATE_16_24": "16:00-24:00 UTC",
            "warning": "These are fixed UTC 8h portfolio windows aligned to strategy bars. They are not pure named exchange sessions.",
        },
        "reports": reports,
        "interpretation": {
            "observational_only": True,
            "strategy_definition_unchanged": True,
            "do_not_filter_or_retime_current_candidate": True,
            "primary_metrics": [
                "cumulative_net_bps",
                "net_mean_bps",
                "net_median_bps",
                "win_rate",
                "profit_factor",
                "max_drawdown_bps",
                "largest_positive_interval_share",
                "path",
            ],
        },
        "claims": {
            "candidate_promoted": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }

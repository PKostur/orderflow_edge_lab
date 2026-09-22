from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from orderflow_edge_lab.session_metrics import session_phase_memberships


class SessionWatchError(ValueError):
    pass


def _parse_utc(text: str) -> datetime:
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise SessionWatchError("prospective watch start must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda r: int(r["signal_observed_at_ns"]))
    vals = [float(r["net_bps"]) for r in rows]
    gross = [float(r["gross_bps"]) for r in rows]
    if not vals:
        return {
            "observations": 0,
            "independent_batches": 0,
            "calendar_days": 0,
            "gross_mean_bps": None,
            "net_mean_bps": None,
            "net_median_bps": None,
            "cumulative_net_bps": 0.0,
            "win_rate": None,
            "profit_factor": None,
            "positive_batch_fraction": None,
            "positive_day_fraction": None,
            "max_drawdown_bps": 0.0,
            "peak_cumulative_net_bps": 0.0,
            "giveback_from_peak_bps": 0.0,
            "largest_positive_batch_share": None,
            "batch_curve": [],
            "daily_curve": [],
        }

    by_batch: dict[str, list[float]] = defaultdict(list)
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = float(row["net_bps"])
        by_batch[str(row["batch_id"])].append(value)
        dt = datetime.fromtimestamp(
            int(row["signal_observed_at_ns"]) / 1_000_000_000,
            tz=timezone.utc,
        )
        by_day[dt.date().isoformat()].append(value)

    pos = sum(v for v in vals if v > 0)
    neg = -sum(v for v in vals if v < 0)
    pf: float | str | None
    if neg > 0:
        pf = pos / neg
    elif pos > 0:
        pf = "INF"
    else:
        pf = None

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in vals:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)

    batch_means = [statistics.fmean(v) for v in by_batch.values()]
    day_means = [statistics.fmean(v) for v in by_day.values()]

    batch_first_ts: dict[str, int] = {}
    for row in rows:
        batch_id = str(row["batch_id"])
        ts = int(row["signal_observed_at_ns"])
        batch_first_ts[batch_id] = min(batch_first_ts.get(batch_id, ts), ts)

    batch_curve = []
    batch_cumulative = 0.0
    positive_batch_total = sum(sum(v) for v in by_batch.values() if sum(v) > 0)
    positive_batch_nets = []
    for batch_id in sorted(by_batch, key=lambda b: batch_first_ts[b]):
        batch_net = sum(by_batch[batch_id])
        batch_cumulative += batch_net
        if batch_net > 0:
            positive_batch_nets.append(batch_net)
        batch_curve.append({
            "batch_id": batch_id,
            "net_bps": batch_net,
            "cumulative_net_bps": batch_cumulative,
        })

    daily_curve = []
    day_cumulative = 0.0
    for day in sorted(by_day):
        day_net = sum(by_day[day])
        day_cumulative += day_net
        daily_curve.append({
            "date_utc": day,
            "net_bps": day_net,
            "cumulative_net_bps": day_cumulative,
        })

    return {
        "observations": len(vals),
        "independent_batches": len(by_batch),
        "calendar_days": len(by_day),
        "gross_mean_bps": statistics.fmean(gross),
        "net_mean_bps": statistics.fmean(vals),
        "net_median_bps": statistics.median(vals),
        "cumulative_net_bps": sum(vals),
        "win_rate": sum(v > 0 for v in vals) / len(vals),
        "profit_factor": pf,
        "positive_batch_fraction": sum(v > 0 for v in batch_means) / len(batch_means),
        "positive_day_fraction": sum(v > 0 for v in day_means) / len(day_means),
        "max_drawdown_bps": max_dd,
        "peak_cumulative_net_bps": peak,
        "giveback_from_peak_bps": sum(vals) - peak,
        "largest_positive_batch_share": (
            max(positive_batch_nets) / positive_batch_total
            if positive_batch_total > 0 and positive_batch_nets
            else None
        ),
        "batch_curve": batch_curve,
        "daily_curve": daily_curve,
    }


def _row_after_boundary(row: Mapping[str, Any], boundary: datetime) -> bool:
    observed = row.get("signal_observed_at_ns")
    if observed is None:
        return False
    dt = datetime.fromtimestamp(int(observed) / 1_000_000_000, tz=timezone.utc)
    return dt > boundary


def _matches_watch_base(row: Mapping[str, Any], watch: Mapping[str, Any], boundary: datetime) -> bool:
    if not _row_after_boundary(row, boundary):
        return False
    if str(row.get("family")) != str(watch["family"]):
        return False
    if watch.get("side") is not None:
        try:
            if int(row.get("side")) != int(watch["side"]):
                return False
        except (TypeError, ValueError):
            return False

    observed = datetime.fromtimestamp(
        int(row["signal_observed_at_ns"]) / 1_000_000_000,
        tz=timezone.utc,
    )
    phase = watch.get("session_phase")
    if phase is not None and str(phase) not in session_phase_memberships(observed):
        return False

    conditions = row.get("conditions") or {}
    for key, expected in (watch.get("conditions") or {}).items():
        if conditions.get(key) != expected:
            return False
    return True


def build_session_watch_report(
    condition_aggregate: Mapping[str, Any],
    watch_config: Mapping[str, Any],
) -> dict[str, Any]:
    if condition_aggregate.get("experiment") != "multi_batch_market_condition_aggregate":
        raise SessionWatchError("expected multi_batch_market_condition_aggregate")
    observations = [
        dict(row)
        for row in condition_aggregate.get("enriched_observations", [])
        if isinstance(row, Mapping)
    ]
    if not observations:
        raise SessionWatchError("no enriched observations")

    boundary = _parse_utc(str(watch_config["prospective_watch_start_utc"]))
    requirement = dict(watch_config.get("prospective_review_requirement") or {})
    min_batches = int(requirement.get("minimum_new_independent_batches", 10))
    min_days = int(requirement.get("minimum_new_calendar_days", 5))

    results: list[dict[str, Any]] = []
    for watch in watch_config.get("watches", []):
        if not isinstance(watch, Mapping):
            continue
        watch_boundary = _parse_utc(
            str(watch.get("prospective_watch_start_utc") or watch_config["prospective_watch_start_utc"])
        )
        watch_requirement = {
            **requirement,
            **dict(watch.get("prospective_review_requirement") or {}),
        }
        watch_min_signals = int(watch_requirement.get("minimum_new_signals", 0))
        watch_min_batches = int(watch_requirement.get("minimum_new_independent_batches", min_batches))
        watch_min_days = int(watch_requirement.get("minimum_new_calendar_days", min_days))
        base_rows = [
            row for row in observations if _matches_watch_base(row, watch, watch_boundary)
        ]
        horizons = [int(x) for x in watch.get("horizons_ms", [])]
        fees = [float(x) for x in watch.get("fees_bps_round_trip", [])]
        cells: list[dict[str, Any]] = []
        for fee in fees:
            for horizon in horizons:
                rows = [
                    row
                    for row in base_rows
                    if int(row.get("horizon_ms")) == horizon
                    and float(row.get("fee_bps_round_trip")) == fee
                ]
                cells.append(
                    {
                        "horizon_ms": horizon,
                        "fee_bps_round_trip": fee,
                        **_summary(rows),
                    }
                )

        # Use unique signal/batch/day evidence from the watch base, not duplicated
        # horizon/fee evaluations, for readiness.
        unique_signals: dict[tuple[str, int], dict[str, Any]] = {}
        for row in base_rows:
            key = (str(row.get("batch_id")), int(row["signal_observed_at_ns"]))
            unique_signals.setdefault(key, row)
        evidence_rows = list(unique_signals.values())
        evidence_batches = len({str(r.get("batch_id")) for r in evidence_rows})
        evidence_days = len(
            {
                datetime.fromtimestamp(
                    int(r["signal_observed_at_ns"]) / 1_000_000_000,
                    tz=timezone.utc,
                ).date().isoformat()
                for r in evidence_rows
            }
        )
        ready = (
            len(evidence_rows) >= watch_min_signals
            and evidence_batches >= watch_min_batches
            and evidence_days >= watch_min_days
        )

        travel_by_fee: list[dict[str, Any]] = []
        for fee in fees:
            parts = sorted(
                [c for c in cells if c["fee_bps_round_trip"] == fee],
                key=lambda c: c["horizon_ms"],
            )
            gross_values = [
                c["gross_mean_bps"]
                for c in parts
                if c["gross_mean_bps"] is not None
            ]
            travel_by_fee.append(
                {
                    "fee_bps_round_trip": fee,
                    "gross_travel_monotonic_non_decreasing": (
                        len(gross_values) >= 2
                        and all(
                            right >= left
                            for left, right in zip(gross_values, gross_values[1:])
                        )
                    ),
                    "horizons": [
                        {
                            "horizon_ms": c["horizon_ms"],
                            "gross_mean_bps": c["gross_mean_bps"],
                            "net_mean_bps": c["net_mean_bps"],
                            "observations": c["observations"],
                            "independent_batches": c["independent_batches"],
                            "positive_batch_fraction": c["positive_batch_fraction"],
                        }
                        for c in parts
                    ],
                }
            )

        results.append(
            {
                "watch_id": watch["watch_id"],
                "family": watch["family"],
                "side": watch.get("side"),
                "direction": watch.get("direction"),
                "session_phase": watch.get("session_phase"),
                "conditions": watch.get("conditions"),
                "prospective_watch_start_utc": watch_boundary.isoformat().replace("+00:00", "Z"),
                "prospective_unique_signals": len(evidence_rows),
                "prospective_independent_batches": evidence_batches,
                "prospective_calendar_days": evidence_days,
                "review_requirement": {
                    "minimum_new_signals": watch_min_signals,
                    "minimum_new_independent_batches": watch_min_batches,
                    "minimum_new_calendar_days": watch_min_days,
                },
                "ready_for_review": ready,
                "status": "READY_FOR_REVIEW" if ready else "ACCUMULATING",
                "cells": cells,
                "travel_by_fee": travel_by_fee,
                "development_snapshot_30s_4bps": watch.get(
                    "development_snapshot_30s_4bps"
                ),
            }
        )

    return {
        "schema_version": 1,
        "analysis": "prospective_session_development_watch",
        "symbol": condition_aggregate.get("symbol"),
        "context_symbol": condition_aggregate.get("context_symbol"),
        "prospective_watch_start_utc": boundary.isoformat().replace("+00:00", "Z"),
        "prospective_review_requirement": {
            "minimum_new_independent_batches": min_batches,
            "minimum_new_calendar_days": min_days,
        },
        "watches": results,
        "claims": {
            "development_watch_only": True,
            "promotion_before_review_target_forbidden": True,
            "live_order_transmission_supported": False,
            "leverage_authorized": False,
        },
    }


def load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SessionWatchError("expected JSON object")
    return payload

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


SESSION_METRICS_VERSION = "fixed_utc_session_attribution_v1"
NAMED_SESSIONS_UTC: dict[str, tuple[int, int]] = {
    "asia": (0, 8),
    "london": (8, 16),
    "new_york": (13, 21),
}
EXCLUSIVE_BUCKETS_UTC: dict[str, tuple[int, int]] = {
    "asia": (0, 8),
    "london_pre_overlap": (8, 13),
    "london_new_york_overlap": (13, 16),
    "new_york_post_overlap": (16, 21),
    "late_transition": (21, 24),
}


def _as_utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _utc_index(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    idx = pd.to_datetime(out.index, utc=True)
    out.index = idx
    return out.sort_index()


def _window_label(start_hour: int, end_hour: int) -> str:
    return f"{start_hour:02d}:00-{end_hour:02d}:00"


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    return int(start_hour) <= int(hour) < int(end_hour)


def _safe_mean(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return float(clean.mean()) if len(clean) else None


def _safe_fraction_positive(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return float((clean > 0.0).mean()) if len(clean) else None


def _summarize_setup_values(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "setup_count": 0,
            "accepted_setup_count": 0,
            "rejected_setup_count": 0,
            "all_primary_setup_mean_gross_contribution_bps": None,
            "candidate_calendar_setup_mean_gross_contribution_bps": None,
            "accepted_setup_mean_gross_contribution_bps": None,
            "rejected_setup_mean_gross_contribution_bps": None,
            "accepted_minus_rejected_mean_gross_contribution_bps": None,
            "accepted_positive_fraction": None,
            "rejected_positive_fraction": None,
        }
    accepted = frame.loc[frame["trade"].astype(bool)].copy()
    rejected = frame.loc[~frame["trade"].astype(bool)].copy()
    all_mean = _safe_mean(frame["gross_contribution_bps"])
    accepted_mean = _safe_mean(accepted["gross_contribution_bps"])
    rejected_mean = _safe_mean(rejected["gross_contribution_bps"])
    candidate_values = pd.to_numeric(frame["gross_contribution_bps"], errors="coerce").where(
        frame["trade"].astype(bool), 0.0
    )
    return {
        "setup_count": int(len(frame)),
        "accepted_setup_count": int(len(accepted)),
        "rejected_setup_count": int(len(rejected)),
        "all_primary_setup_mean_gross_contribution_bps": all_mean,
        "candidate_calendar_setup_mean_gross_contribution_bps": _safe_mean(candidate_values),
        "accepted_setup_mean_gross_contribution_bps": accepted_mean,
        "rejected_setup_mean_gross_contribution_bps": rejected_mean,
        "accepted_minus_rejected_mean_gross_contribution_bps": (
            float(accepted_mean - rejected_mean)
            if accepted_mean is not None and rejected_mean is not None
            else None
        ),
        "accepted_positive_fraction": _safe_fraction_positive(accepted["gross_contribution_bps"]),
        "rejected_positive_fraction": _safe_fraction_positive(rejected["gross_contribution_bps"]),
    }


def build_session_attribution(
    predictions: pd.DataFrame,
    *,
    opens: pd.DataFrame,
    hourly_frames: Mapping[str, pd.DataFrame],
    funding_frames: Mapping[str, pd.DataFrame],
    symbols: Sequence[str],
    prospective_start: str | pd.Timestamp,
    side_cost_bps: float,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """Describe where completed setup PnL accrued inside the UTC day.

    This is observational attribution only. It never changes the frozen signal,
    model prediction, TRADE/PASS decision, execution, or promotion state.
    """
    start = _as_utc(prospective_start)
    p = predictions.copy()
    if p.empty:
        return (
            {
                "status": "EXPLORATORY_POST_START_OBSERVATIONAL_ONLY",
                "version": SESSION_METRICS_VERSION,
                "decision_logic_unchanged": True,
                "retuning_or_promotion_use_allowed": False,
                "source_interval": "1h",
                "completed_setups_available": 0,
                "attributed_completed_setups": 0,
                "unattributed_completed_setups": 0,
                "named_sessions_overlap": True,
                "named_sessions_utc": {
                    k: _window_label(*v) for k, v in NAMED_SESSIONS_UTC.items()
                },
                "exclusive_buckets_utc": {
                    k: _window_label(*v) for k, v in EXCLUSIVE_BUCKETS_UTC.items()
                },
                "named_session_metrics": {},
                "exclusive_bucket_metrics": {},
                "reconciliation_with_standalone_label_passed": None,
                "max_abs_reconciliation_error_bps": None,
            },
            {},
        )

    p["start_timestamp"] = pd.to_datetime(p["start_timestamp"], utc=True)
    p["end_timestamp"] = pd.to_datetime(p["end_timestamp"], utc=True)
    p = p.loc[p["start_timestamp"] >= start].sort_values("start_timestamp").copy()

    open_frame = opens.copy()
    open_frame.index = pd.to_datetime(open_frame.index, utc=True)
    open_frame = open_frame.sort_index()
    hourly = {s: _utc_index(hourly_frames[s]) for s in symbols if s in hourly_frames}
    funding = {s: _utc_index(funding_frames[s]) for s in symbols if s in funding_frames}

    hourly_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []

    for row in p.itertuples(index=False):
        entry = _as_utc(row.start_timestamp)
        exit_ = _as_utc(row.end_timestamp)
        target = row.target.reindex(symbols, fill_value=0.0).astype(float)
        active_symbols = [s for s in symbols if abs(float(target.get(s, 0.0))) > 1e-15]
        missing: list[str] = []
        if entry not in open_frame.index or exit_ not in open_frame.index:
            missing.append("daily_open_boundary")
        for symbol in active_symbols:
            h = hourly.get(symbol)
            if h is None or "open" not in h.columns:
                missing.append(f"{symbol}:hourly_source")
                continue
            needed = pd.date_range(entry, exit_, freq="1h", inclusive="both")
            if not needed.isin(h.index).all():
                missing.append(f"{symbol}:hourly_boundary")
        if missing:
            coverage_rows.append(
                {
                    "start_timestamp": entry,
                    "end_timestamp": exit_,
                    "trade": bool(row.trade),
                    "attributed": False,
                    "reason": ";".join(sorted(set(missing))),
                }
            )
            continue

        setup_hour_rows: list[dict[str, Any]] = []
        for hour_start in pd.date_range(entry, exit_, freq="1h", inclusive="left"):
            hour_end = hour_start + pd.Timedelta(hours=1)
            price_bps = 0.0
            funding_bps = 0.0
            for symbol in active_symbols:
                w = float(target[symbol])
                entry_price = float(open_frame.at[entry, symbol])
                if not np.isfinite(entry_price) or entry_price <= 0.0:
                    raise ValueError(f"{symbol}: invalid daily entry open for session attribution")
                h = hourly[symbol]
                p0 = entry_price if hour_start == entry else float(h.at[hour_start, "open"])
                p1 = float(open_frame.at[exit_, symbol]) if hour_end == exit_ else float(h.at[hour_end, "open"])
                price_bps += w * ((p1 - p0) / entry_price) * 10_000.0

                f = funding.get(symbol)
                if f is not None and not f.empty and "funding_rate" in f.columns:
                    rates = pd.to_numeric(f["funding_rate"], errors="coerce").dropna()
                    mask = (
                        (rates.index >= hour_start)
                        & (rates.index < hour_end)
                        & (rates.index > entry)
                        & (rates.index < exit_)
                    )
                    if mask.any():
                        funding_bps += -w * float(rates.loc[mask].sum()) * 10_000.0

            setup_hour_rows.append(
                {
                    "signal_timestamp": _as_utc(row.signal_timestamp),
                    "start_timestamp": entry,
                    "end_timestamp": exit_,
                    "trade": bool(row.trade),
                    "predicted_standalone_net_bps": float(row.predicted_standalone_net_bps),
                    "standalone_label_bps": float(row.standalone_label_bps),
                    "hour_start_utc": hour_start,
                    "hour_end_utc": hour_end,
                    "hour_utc": int(hour_start.hour),
                    "price_contribution_bps": float(price_bps),
                    "funding_contribution_bps": float(funding_bps),
                    "gross_contribution_bps": float(price_bps + funding_bps),
                }
            )

        hourly_rows.extend(setup_hour_rows)
        coverage_rows.append(
            {
                "start_timestamp": entry,
                "end_timestamp": exit_,
                "trade": bool(row.trade),
                "attributed": True,
                "reason": "",
            }
        )
        setup_gross = float(sum(x["gross_contribution_bps"] for x in setup_hour_rows))
        round_trip_cost_bps = 2.0 * float(target.abs().sum()) * float(side_cost_bps)
        reconstructed_net_bps = setup_gross - round_trip_cost_bps
        error_bps = reconstructed_net_bps - float(row.standalone_label_bps)
        reconciliation_rows.append(
            {
                "start_timestamp": entry,
                "end_timestamp": exit_,
                "trade": bool(row.trade),
                "hourly_gross_attributed_bps": setup_gross,
                "standalone_round_trip_cost_bps": round_trip_cost_bps,
                "reconstructed_standalone_net_bps": reconstructed_net_bps,
                "reported_standalone_label_bps": float(row.standalone_label_bps),
                "reconciliation_error_bps": float(error_bps),
            }
        )

    hourly_table = pd.DataFrame(hourly_rows)
    coverage_table = pd.DataFrame(coverage_rows)
    reconciliation_table = pd.DataFrame(reconciliation_rows)

    named_rows: list[dict[str, Any]] = []
    exclusive_rows: list[dict[str, Any]] = []
    if not hourly_table.empty:
        group_keys = [
            "signal_timestamp",
            "start_timestamp",
            "end_timestamp",
            "trade",
            "predicted_standalone_net_bps",
            "standalone_label_bps",
        ]
        for name, (h0, h1) in NAMED_SESSIONS_UTC.items():
            mask = hourly_table["hour_utc"].map(lambda h: _hour_in_window(int(h), h0, h1))
            grouped = (
                hourly_table.loc[mask]
                .groupby(group_keys, as_index=False)["gross_contribution_bps"]
                .sum()
            )
            grouped["session"] = name
            named_rows.extend(grouped.to_dict("records"))
        for name, (h0, h1) in EXCLUSIVE_BUCKETS_UTC.items():
            mask = hourly_table["hour_utc"].map(lambda h: _hour_in_window(int(h), h0, h1))
            grouped = (
                hourly_table.loc[mask]
                .groupby(group_keys, as_index=False)["gross_contribution_bps"]
                .sum()
            )
            grouped["bucket"] = name
            exclusive_rows.extend(grouped.to_dict("records"))

    named_table = pd.DataFrame(named_rows)
    exclusive_table = pd.DataFrame(exclusive_rows)
    named_metrics: dict[str, Any] = {}
    for name, window in NAMED_SESSIONS_UTC.items():
        frame = named_table.loc[named_table["session"] == name].copy() if not named_table.empty else pd.DataFrame()
        metric = _summarize_setup_values(frame)
        metric["window_utc"] = _window_label(*window)
        named_metrics[name] = metric
    exclusive_metrics: dict[str, Any] = {}
    for name, window in EXCLUSIVE_BUCKETS_UTC.items():
        frame = (
            exclusive_table.loc[exclusive_table["bucket"] == name].copy()
            if not exclusive_table.empty
            else pd.DataFrame()
        )
        metric = _summarize_setup_values(frame)
        metric["window_utc"] = _window_label(*window)
        exclusive_metrics[name] = metric

    max_error = None
    reconciliation_passed: bool | None = None
    if not reconciliation_table.empty:
        errors = pd.to_numeric(reconciliation_table["reconciliation_error_bps"], errors="coerce").abs().dropna()
        max_error = float(errors.max()) if len(errors) else None
        reconciliation_passed = bool(max_error is None or max_error <= 1e-6)

    attributed = int(coverage_table["attributed"].sum()) if not coverage_table.empty else 0
    complete = attributed == int(len(p))
    report = {
        "status": (
            "EXPLORATORY_POST_START_OBSERVATIONAL_ONLY"
            if complete
            else "EXPLORATORY_SOURCE_INCOMPLETE"
        ),
        "version": SESSION_METRICS_VERSION,
        "introduced_after_prospective_start": True,
        "decision_logic_unchanged": True,
        "retuning_or_promotion_use_allowed": False,
        "source_interval": "1h",
        "attribution_basis": "static entry notional; hourly open-to-open price PnL plus actual funding; standalone transaction costs reconciled separately",
        "completed_setups_available": int(len(p)),
        "attributed_completed_setups": attributed,
        "unattributed_completed_setups": int(len(p) - attributed),
        "named_sessions_overlap": True,
        "named_sessions_utc": {k: _window_label(*v) for k, v in NAMED_SESSIONS_UTC.items()},
        "exclusive_buckets_utc": {k: _window_label(*v) for k, v in EXCLUSIVE_BUCKETS_UTC.items()},
        "named_session_metrics": named_metrics,
        "exclusive_bucket_metrics": exclusive_metrics,
        "reconciliation_with_standalone_label_passed": reconciliation_passed,
        "max_abs_reconciliation_error_bps": max_error,
    }
    tables = {
        "session_hourly_attribution": hourly_table,
        "session_named_setup_attribution": named_table,
        "session_exclusive_setup_attribution": exclusive_table,
        "session_attribution_coverage": coverage_table,
        "session_attribution_reconciliation": reconciliation_table,
    }
    return report, tables

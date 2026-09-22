from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

UTC = timezone.utc


class SessionMetricsError(ValueError):
    pass


@dataclass(frozen=True)
class SessionSpec:
    name: str
    timezone_name: str
    start_local: time
    end_local: time

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


DEFAULT_SESSIONS: tuple[SessionSpec, ...] = (
    SessionSpec("ASIA", "Asia/Tokyo", time(9, 0), time(18, 0)),
    SessionSpec("LONDON", "Europe/London", time(8, 0), time(17, 0)),
    SessionSpec("NEW_YORK", "America/New_York", time(8, 0), time(17, 0)),
)

_TIMESTAMP_FIELDS = (
    "signal_et",
    "signal_timestamp",
    "timestamp",
    "datetime",
    "time",
    "signal_exchange_ts_ms",
    "exchange_ts_ms",
    "signal_observed_at_ns",
    "observed_at_ns",
    "received_at_ns",
)

_RETURN_FIELDS = ("net_bps", "net_bps_2", "return_bps", "gross_bps")


def _in_local_window(local_dt: datetime, start: time, end: time) -> bool:
    local_time = local_dt.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def session_memberships(
    value: datetime,
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> tuple[str, ...]:
    if value.tzinfo is None:
        raise SessionMetricsError("timestamps must be timezone-aware")
    utc = value.astimezone(UTC)
    active = [
        spec.name
        for spec in sessions
        if _in_local_window(utc.astimezone(spec.tz), spec.start_local, spec.end_local)
    ]
    return tuple(active)


def session_regime(
    value: datetime,
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> str:
    active = session_memberships(value, sessions)
    return "+".join(active) if active else "OFF_SESSION"


def _minutes(value: time) -> float:
    return value.hour * 60.0 + value.minute + value.second / 60.0 + value.microsecond / 60_000_000.0


def session_phase_memberships(
    value: datetime,
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> tuple[str, ...]:
    """Return neutral within-session thirds for every active named session.

    Phases are OPENING, MID and LATE, each occupying one third of the declared
    local session window. This is descriptive metadata, not a trading filter.
    """
    if value.tzinfo is None:
        raise SessionMetricsError("timestamps must be timezone-aware")
    utc = value.astimezone(UTC)
    out: list[str] = []
    for spec in sessions:
        local = utc.astimezone(spec.tz)
        if not _in_local_window(local, spec.start_local, spec.end_local):
            continue
        start = _minutes(spec.start_local)
        end = _minutes(spec.end_local)
        now = _minutes(local.timetz().replace(tzinfo=None))
        duration = (end - start) % (24.0 * 60.0)
        if duration == 0:
            duration = 24.0 * 60.0
        elapsed = (now - start) % (24.0 * 60.0)
        progress = min(max(elapsed / duration, 0.0), 0.999999999)
        if progress < 1.0 / 3.0:
            phase = "OPENING"
        elif progress < 2.0 / 3.0:
            phase = "MID"
        else:
            phase = "LATE"
        out.append(f"{spec.name}_{phase}")
    return tuple(out)


def _parse_timestamp(value: Any, field: str | None = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SessionMetricsError("naive datetime is not allowed")
        return value.astimezone(UTC)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise SessionMetricsError("timestamp must be finite")
        unit = "s"
        if field and field.endswith("_ns"):
            unit = "ns"
        elif field and field.endswith("_ms"):
            unit = "ms"
        elif abs(numeric) >= 1e17:
            unit = "ns"
        elif abs(numeric) >= 1e11:
            unit = "ms"
        divisor = {"s": 1.0, "ms": 1_000.0, "ns": 1_000_000_000.0}[unit]
        return datetime.fromtimestamp(numeric / divisor, tz=UTC)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise SessionMetricsError("timestamp is empty")
        if text.isdigit():
            return _parse_timestamp(int(text), field)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise SessionMetricsError(f"invalid timestamp: {value}") from exc
        if parsed.tzinfo is None:
            raise SessionMetricsError(
                f"timestamp lacks timezone offset: {value}; use an offset or epoch timestamp"
            )
        return parsed.astimezone(UTC)

    raise SessionMetricsError(f"unsupported timestamp value: {value!r}")


def resolve_timestamp(
    row: Mapping[str, Any],
    preferred_field: str | None = None,
) -> tuple[datetime, str]:
    candidates = (preferred_field,) if preferred_field else _TIMESTAMP_FIELDS
    for field in candidates:
        if field and row.get(field) not in (None, ""):
            return _parse_timestamp(row[field], field), field
    raise SessionMetricsError("no supported timestamp field found")


def resolve_return_field(
    row: Mapping[str, Any],
    preferred_field: str | None = None,
) -> str:
    candidates = (preferred_field,) if preferred_field else _RETURN_FIELDS
    for field in candidates:
        if field and row.get(field) not in (None, ""):
            return field
    raise SessionMetricsError("no supported return field found")


def _float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SessionMetricsError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise SessionMetricsError(f"{field} must be finite")
    return result


def _profit_factor(values: Sequence[float]) -> float | str | None:
    profit = sum(v for v in values if v > 0)
    loss = -sum(v for v in values if v < 0)
    if loss > 0:
        return profit / loss
    if profit > 0:
        return "INF"
    return None


def _numeric_pf(value: float | str | None) -> float | None:
    if value == "INF":
        return math.inf
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _max_drawdown_bps(values: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return worst


def _summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "observations": 0,
            "net_total_bps": 0.0,
            "net_mean_bps": None,
            "net_median_bps": None,
            "net_stdev_bps": None,
            "net_win_rate": None,
            "average_win_bps": None,
            "average_loss_bps": None,
            "break_even_win_rate": None,
            "profit_factor": None,
            "max_drawdown_bps": 0.0,
            "largest_positive_trade_share": None,
            "top_three_positive_trade_share": None,
        }

    wins = [v for v in values if v > 0]
    losses = [v for v in values if v <= 0]
    avg_win = statistics.fmean(wins) if wins else None
    avg_loss = statistics.fmean(losses) if losses else None
    break_even = None
    if avg_win is not None and avg_loss is not None:
        denominator = avg_win + abs(avg_loss)
        if denominator > 0:
            break_even = abs(avg_loss) / denominator

    positive_total = sum(wins)
    ranked = sorted(wins, reverse=True)
    top1 = ranked[0] / positive_total if positive_total > 0 and ranked else None
    top3 = sum(ranked[:3]) / positive_total if positive_total > 0 else None

    return {
        "observations": len(values),
        "net_total_bps": sum(values),
        "net_mean_bps": statistics.fmean(values),
        "net_median_bps": statistics.median(values),
        "net_stdev_bps": statistics.stdev(values) if len(values) >= 2 else None,
        "net_win_rate": len(wins) / len(values),
        "average_win_bps": avg_win,
        "average_loss_bps": avg_loss,
        "break_even_win_rate": break_even,
        "profit_factor": _profit_factor(values),
        "max_drawdown_bps": _max_drawdown_bps(values),
        "largest_positive_trade_share": top1,
        "top_three_positive_trade_share": top3,
    }


def _optional_mean(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if value in (None, ""):
            continue
        try:
            values.append(_float(value, field))
        except SessionMetricsError:
            continue
    return statistics.fmean(values) if values else None


def _enrich_trade(
    row: Mapping[str, Any],
    *,
    timestamp_field: str | None,
    return_field: str | None,
    sessions: Sequence[SessionSpec],
) -> dict[str, Any]:
    timestamp, used_ts_field = resolve_timestamp(row, timestamp_field)
    used_return_field = resolve_return_field(row, return_field)
    net_bps = _float(row[used_return_field], used_return_field)
    memberships = session_memberships(timestamp, sessions)
    return {
        **dict(row),
        "_timestamp_utc": timestamp,
        "_timestamp_field": used_ts_field,
        "_return_field": used_return_field,
        "_net_bps": net_bps,
        "_memberships": memberships,
        "_phases": session_phase_memberships(timestamp, sessions),
        "_regime": "+".join(memberships) if memberships else "OFF_SESSION",
    }


def _metric_with_extras(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(row["_net_bps"]) for row in rows]
    out = _summary(values)
    out["average_mfe_bps"] = _optional_mean(rows, "mfe_bps")
    out["average_mae_bps"] = _optional_mean(rows, "mae_bps")
    out["average_gross_bps"] = _optional_mean(rows, "gross_bps")
    out["distinct_dates"] = len(
        {row["_timestamp_utc"].date().isoformat() for row in rows}
    )
    return out


def analyze_trade_sessions(
    rows: Iterable[Mapping[str, Any]],
    *,
    timestamp_field: str | None = None,
    return_field: str | None = None,
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> dict[str, Any]:
    enriched = [
        _enrich_trade(
            row,
            timestamp_field=timestamp_field,
            return_field=return_field,
            sessions=sessions,
        )
        for row in rows
    ]
    enriched.sort(key=lambda row: row["_timestamp_utc"])
    if not enriched:
        raise SessionMetricsError("no trade rows")

    baseline = _metric_with_extras(enriched)
    baseline_pf = _numeric_pf(baseline["profit_factor"])

    by_membership: list[dict[str, Any]] = []
    for spec in sessions:
        group = [row for row in enriched if spec.name in row["_memberships"]]
        metrics = _metric_with_extras(group)
        pf = _numeric_pf(metrics["profit_factor"])
        by_membership.append(
            {
                "session": spec.name,
                "timezone": spec.timezone_name,
                "local_window": f"{spec.start_local.strftime('%H:%M')}-{spec.end_local.strftime('%H:%M')}",
                **metrics,
                "mean_bps_delta_vs_all": (
                    metrics["net_mean_bps"] - baseline["net_mean_bps"]
                    if metrics["net_mean_bps"] is not None and baseline["net_mean_bps"] is not None
                    else None
                ),
                "win_rate_delta_vs_all": (
                    metrics["net_win_rate"] - baseline["net_win_rate"]
                    if metrics["net_win_rate"] is not None and baseline["net_win_rate"] is not None
                    else None
                ),
                "profit_factor_ratio_vs_all": (
                    pf / baseline_pf
                    if pf is not None
                    and baseline_pf is not None
                    and baseline_pf > 0
                    and math.isfinite(pf)
                    and math.isfinite(baseline_pf)
                    else None
                ),
                "sample_warning": metrics["observations"] < 20,
            }
        )

    regimes = sorted({str(row["_regime"]) for row in enriched})
    by_regime: list[dict[str, Any]] = []
    for regime in regimes:
        group = [row for row in enriched if row["_regime"] == regime]
        metrics = _metric_with_extras(group)
        by_regime.append(
            {
                "regime": regime,
                **metrics,
                "mean_bps_delta_vs_all": (
                    metrics["net_mean_bps"] - baseline["net_mean_bps"]
                    if metrics["net_mean_bps"] is not None and baseline["net_mean_bps"] is not None
                    else None
                ),
                "sample_warning": metrics["observations"] < 20,
            }
        )

    positive_total = sum(max(float(row["_net_bps"]), 0.0) for row in enriched)
    for row in by_membership:
        group = [x for x in enriched if row["session"] in x["_memberships"]]
        session_positive = sum(max(float(x["_net_bps"]), 0.0) for x in group)
        row["share_of_all_positive_pnl"] = (
            session_positive / positive_total if positive_total > 0 else None
        )

    return {
        "schema_version": 1,
        "analysis": "trading_session_metrics",
        "session_semantics": {
            "membership_is_multilabel": True,
            "overlaps_are_not_forced_into_one_session": True,
            "default_sessions": [
                {
                    "name": spec.name,
                    "timezone": spec.timezone_name,
                    "local_window": f"{spec.start_local.strftime('%H:%M')}-{spec.end_local.strftime('%H:%M')}",
                }
                for spec in sessions
            ],
        },
        "baseline": baseline,
        "by_session_membership": by_membership,
        "by_exclusive_regime": by_regime,
        "claims": {
            "descriptive_only": True,
            "session_filter_not_authorized_without_frozen_forward_test": True,
            "live_order_transmission_supported": False,
        },
    }


def analyze_bar_sessions(
    rows: Iterable[Mapping[str, Any]],
    *,
    timestamp_field: str | None = None,
    open_field: str = "open",
    high_field: str = "high",
    low_field: str = "low",
    close_field: str = "close",
    volume_field: str = "volume",
    sessions: Sequence[SessionSpec] = DEFAULT_SESSIONS,
) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    for source in rows:
        timestamp, _ = resolve_timestamp(source, timestamp_field)
        row = dict(source)
        row["_timestamp_utc"] = timestamp
        row["_memberships"] = session_memberships(timestamp, sessions)
        row["_regime"] = "+".join(row["_memberships"]) if row["_memberships"] else "OFF_SESSION"
        row["_open"] = _float(source[open_field], open_field)
        row["_high"] = _float(source[high_field], high_field)
        row["_low"] = _float(source[low_field], low_field)
        row["_close"] = _float(source[close_field], close_field)
        volume = source.get(volume_field)
        row["_volume"] = _float(volume, volume_field) if volume not in (None, "") else None
        enriched.append(row)
    enriched.sort(key=lambda row: row["_timestamp_utc"])
    if not enriched:
        raise SessionMetricsError("no bar rows")

    def summarize_bar_group(group: list[dict[str, Any]], session_name: str) -> dict[str, Any]:
        per_day: dict[str, list[dict[str, Any]]] = {}
        for row in group:
            if session_name == "REGIME":
                day_key = row["_timestamp_utc"].date().isoformat()
            else:
                spec = next(s for s in sessions if s.name == session_name)
                day_key = row["_timestamp_utc"].astimezone(spec.tz).date().isoformat()
            per_day.setdefault(day_key, []).append(row)

        session_days: list[dict[str, float]] = []
        for day_rows in per_day.values():
            day_rows.sort(key=lambda r: r["_timestamp_utc"])
            first = day_rows[0]
            last = day_rows[-1]
            if first["_open"] <= 0 or min(r["_low"] for r in day_rows) <= 0:
                continue
            returns = []
            for left, right in zip(day_rows, day_rows[1:]):
                if left["_close"] > 0 and right["_close"] > 0:
                    returns.append(math.log(right["_close"] / left["_close"]))
            ret = (last["_close"] / first["_open"] - 1.0) * 10000.0
            hi = max(r["_high"] for r in day_rows)
            lo = min(r["_low"] for r in day_rows)
            range_bps = (hi / lo - 1.0) * 10000.0
            realized = math.sqrt(sum(r * r for r in returns)) * 10000.0
            volumes = [r["_volume"] for r in day_rows if r["_volume"] is not None]
            session_days.append(
                {
                    "return_bps": ret,
                    "abs_return_bps": abs(ret),
                    "range_bps": range_bps,
                    "realized_vol_bps": realized,
                    "volume": sum(volumes) if volumes else 0.0,
                }
            )
        if not session_days:
            return {
                "session_days": 0,
                "average_return_bps": None,
                "median_return_bps": None,
                "positive_day_rate": None,
                "average_abs_return_bps": None,
                "average_range_bps": None,
                "average_realized_vol_bps": None,
                "average_volume": None,
            }
        return {
            "session_days": len(session_days),
            "average_return_bps": statistics.fmean(x["return_bps"] for x in session_days),
            "median_return_bps": statistics.median(x["return_bps"] for x in session_days),
            "positive_day_rate": sum(x["return_bps"] > 0 for x in session_days) / len(session_days),
            "average_abs_return_bps": statistics.fmean(x["abs_return_bps"] for x in session_days),
            "average_range_bps": statistics.fmean(x["range_bps"] for x in session_days),
            "average_realized_vol_bps": statistics.fmean(x["realized_vol_bps"] for x in session_days),
            "average_volume": statistics.fmean(x["volume"] for x in session_days),
        }

    by_membership = []
    for spec in sessions:
        group = [row for row in enriched if spec.name in row["_memberships"]]
        by_membership.append(
            {
                "session": spec.name,
                "timezone": spec.timezone_name,
                "local_window": f"{spec.start_local.strftime('%H:%M')}-{spec.end_local.strftime('%H:%M')}",
                **summarize_bar_group(group, spec.name),
            }
        )

    by_regime = []
    for regime in sorted({str(row["_regime"]) for row in enriched}):
        group = [row for row in enriched if row["_regime"] == regime]
        by_regime.append({"regime": regime, **summarize_bar_group(group, "REGIME")})

    return {
        "schema_version": 1,
        "analysis": "market_session_metrics",
        "by_session_membership": by_membership,
        "by_exclusive_regime": by_regime,
        "claims": {
            "descriptive_only": True,
            "not_a_strategy_edge_test": True,
        },
    }


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        with source.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SessionMetricsError(f"invalid JSON at line {line_no}") from exc
                if isinstance(value, Mapping):
                    rows.append(dict(value))
        return rows

    if suffix == ".json":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SessionMetricsError("invalid JSON input") from exc
        if isinstance(payload, list):
            return [dict(row) for row in payload if isinstance(row, Mapping)]
        if isinstance(payload, Mapping):
            for key in ("observations", "trades", "rows", "enriched_observations"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [dict(row) for row in value if isinstance(row, Mapping)]
            return [dict(payload)]

    raise SessionMetricsError(f"unsupported input format: {source.suffix}")

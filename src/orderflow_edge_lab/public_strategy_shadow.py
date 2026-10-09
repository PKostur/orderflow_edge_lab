"""Read-only, causal OHLCV shadow experiments inspired by public strategy patterns.

This module deliberately has no exchange client, network calls, orders, paper
account mutations, strategy promotion, or live execution path. All outcomes are
descriptive; external source authenticity and OOS freeze provenance are unverified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Mapping


class PublicShadowError(ValueError):
    """Fail-closed input, provenance or freeze contract violation."""


@dataclass(frozen=True)
class Bar:
    timestamp: datetime  # UTC candle OPEN, not candle close
    open: float
    high: float
    low: float
    close: float
    volume: float


FAMILIES = {
    "volume_impulse": {"volume_multiple", "min_range_bps", "min_close_location"},
    "failed_downside_break": {"min_close_location"},
    "rolling_vwap_reversion": {"min_displacement_bps"},
}
REQUIRED_COSTS = ("fee_bps_per_side", "spread_bps_round_trip", "slippage_bps_round_trip")


def utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise PublicShadowError("timestamp must be an ISO UTC string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicShadowError(f"invalid timestamp: {value}") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise PublicShadowError("timestamps must explicitly use UTC")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_spec(spec: Mapping[str, Any], *, prospective: bool) -> None:
    if spec.get("schema_version") != 1 or spec.get("trial_family") != "public-strategy-shadow-v1":
        raise PublicShadowError("unsupported experiment schema/trial family")
    if spec.get("market_type") != "spot" or spec.get("direction") != "long_only":
        raise PublicShadowError("this research-only evaluator supports spot, long-only")
    minutes = spec.get("bar_minutes")
    if type(minutes) is not int or minutes < 1 or 1440 % minutes:
        raise PublicShadowError("bar_minutes must divide one UTC day")
    symbols = spec.get("symbols")
    benchmark = spec.get("benchmark_symbol")
    if (not isinstance(symbols, list) or not symbols or len(symbols) != len(set(symbols))
            or not all(isinstance(s, str) and re.fullmatch(r"[A-Z0-9_]{3,30}", s) for s in symbols)
            or not isinstance(benchmark, str) or not re.fullmatch(r"[A-Z0-9_]{3,30}", benchmark)
            or benchmark in symbols):
        raise PublicShadowError("invalid or overlapping symbols/benchmark")
    costs = spec.get("costs_bps")
    if not isinstance(costs, dict) or set(costs) != set(REQUIRED_COSTS):
        raise PublicShadowError("fee, spread and slippage costs must be explicitly fixed")
    for name in REQUIRED_COSTS:
        value = costs[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise PublicShadowError(f"invalid cost {name}")
        if value < 0 or value > 500:
            raise PublicShadowError(f"out-of-range cost {name}")
    if costs["fee_bps_per_side"] <= 0 or sum(costs.values()) <= 0:
        raise PublicShadowError("positive transaction costs are mandatory")
    experiments = spec.get("experiments")
    if not isinstance(experiments, list) or len(experiments) != 3:
        raise PublicShadowError("exactly three preregisterable experiments required")
    seen = set()
    for e in experiments:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or e["id"] in seen:
            raise PublicShadowError("experiment IDs must be unique")
        seen.add(e["id"])
        family = e.get("family")
        params = e.get("parameters")
        if family not in FAMILIES or not isinstance(params, dict) or set(params) != FAMILIES[family]:
            raise PublicShadowError("unsupported family or missing/unregistered parameters")
        if type(e.get("lookback_bars")) is not int or not 2 <= e["lookback_bars"] <= 500:
            raise PublicShadowError("invalid lookback")
        if type(e.get("hold_bars")) is not int or not 1 <= e["hold_bars"] <= 30:
            raise PublicShadowError("invalid holding horizon")
        for key, value in params.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise PublicShadowError(f"invalid parameter {key}")
            if value <= 0:
                raise PublicShadowError(f"nonpositive parameter {key}")
        if params.get("min_close_location", 0) >= 1:
            raise PublicShadowError("close-location threshold must be below one")
    rule = spec.get("decision_rule")
    design = spec.get("design")
    if (not isinstance(rule, dict) or not all(k in rule for k in
            ("metric", "direction", "threshold", "inconclusive_when"))
            or not isinstance(design, dict) or not all(k in design for k in
            ("dependence_cluster", "design_effect_bps", "design_units"))
            or not spec.get("review_gates")):
        raise PublicShadowError("missing preregisterable decision rule, design or gates")
    gates = spec["review_gates"]
    if (not isinstance(gates, dict) or set(gates) !=
            {"min_completed", "min_calendar_weeks", "min_distinct_symbols"}
            or not all(type(x) is int and x > 0 for x in gates.values())):
        raise PublicShadowError("invalid minimum review gates")
    if prospective:
        if spec.get("status") != "FROZEN_BEFORE_PROSPECTIVE_START":
            raise PublicShadowError("prospective mode disabled for draft/unfrozen specifications")
        if not re.fullmatch(r"[a-f0-9]{40}", str(spec.get("freeze_commit", ""))):
            raise PublicShadowError("freeze_commit must be an immutable 40-character commit SHA")
        freeze = utc(spec.get("frozen_at_utc"))
        start = utc(spec.get("prospective_start_utc"))
        if start <= freeze:
            raise PublicShadowError("prospective start must be strictly after freeze")
    else:
        if spec.get("status") not in {"DRAFT_NOT_FROZEN", "FROZEN_BEFORE_PROSPECTIVE_START"}:
            raise PublicShadowError("unknown research status")


def read_bars(path: Path, minutes: int, as_of: datetime) -> list[Bar]:
    if not path.is_file():
        raise PublicShadowError(f"missing source file: {path}")
    step = timedelta(minutes=minutes)
    bars: list[Bar] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not set(("timestamp", "open", "high", "low", "close", "volume")).issubset(reader.fieldnames):
                raise PublicShadowError(f"{path}: required CSV columns missing")
            for row in reader:
                timestamp = utc(row["timestamp"])
                if int(timestamp.timestamp()) % (minutes * 60):
                    raise PublicShadowError(f"{path}: candle is not UTC interval-aligned")
                if timestamp + step > as_of:
                    raise PublicShadowError(f"{path}: contains a candle not closed by --as-of")
                try:
                    numbers = [float(row[k]) for k in ("open", "high", "low", "close", "volume")]
                except (ValueError, TypeError, KeyError) as exc:
                    raise PublicShadowError(f"{path}: invalid numeric candle") from exc
                o, h, l, c, v = numbers
                if (not all(math.isfinite(x) for x in numbers) or min(o, h, l, c) <= 0 or v < 0
                        or h < max(o, c, l) or l > min(o, c, h)):
                    raise PublicShadowError(f"{path}: invalid OHLCV range")
                if bars and timestamp != bars[-1].timestamp + step:
                    raise PublicShadowError(f"{path}: missing, duplicated or out-of-order candle")
                bars.append(Bar(timestamp, o, h, l, c, v))
    except (UnicodeError, csv.Error) as exc:
        raise PublicShadowError(f"{path}: invalid CSV encoding/format") from exc
    if not bars:
        raise PublicShadowError(f"{path}: no candles")
    return bars


def is_signal(bars: list[Bar], i: int, experiment: Mapping[str, Any]) -> bool:
    lookback = experiment["lookback_bars"]
    if i < lookback:
        return False
    current = bars[i]
    previous = bars[i - lookback:i]
    params = experiment["parameters"]
    family = experiment["family"]
    spread = current.high - current.low
    location = (current.close - current.low) / spread if spread > 0 else 0.0
    if family == "volume_impulse":
        avg_volume = mean(b.volume for b in previous)
        return (avg_volume > 0 and current.volume / avg_volume >= params["volume_multiple"]
                and spread / current.open * 10_000 >= params["min_range_bps"]
                and current.close > current.open and location >= params["min_close_location"])
    if family == "failed_downside_break":
        low = min(b.low for b in previous)
        return current.low < low < current.close and location >= params["min_close_location"]
    if family == "rolling_vwap_reversion":
        window = bars[i - lookback + 1:i + 1]
        total_volume = sum(b.volume for b in window)
        if total_volume <= 0:
            return False
        vwap = sum((b.high + b.low + b.close) / 3 * b.volume for b in window) / total_volume
        return (current.close > current.open and
                (vwap - current.close) / vwap * 10_000 >= params["min_displacement_bps"])
    raise PublicShadowError("unrecognized strategy family")


def _summarize(events: list[dict[str, Any]], gates: Mapping[str, int]) -> dict[str, Any]:
    completed = [e for e in events if e["status"] == "completed"]
    pending = len(events) - len(completed)
    by_week: dict[str, list[float]] = {}
    for event in completed:
        dt = utc(event["exit_time"])
        year, week, _ = dt.isocalendar()
        by_week.setdefault(f"{year}-W{week:02d}", []).append(event["excess_vs_btc_bps"])
    week_means = [mean(values) for _, values in sorted(by_week.items())]
    half_width = (2.394 * stdev(week_means) / math.sqrt(len(week_means))
                  if len(week_means) >= 2 else None)
    excess = mean(e["excess_vs_btc_bps"] for e in completed) if completed else None
    symbols = {e["symbol"] for e in completed}
    return {
        "completed": len(completed),
        "pending": pending,
        "distinct_symbols": len(symbols),
        "calendar_week_clusters": len(by_week),
        "positive_week_fraction": (sum(x > 0 for x in week_means) / len(week_means)
                                  if week_means else None),
        "mean_net_bps": mean(e["net_bps"] for e in completed) if completed else None,
        "mean_excess_vs_btc_bps": excess,
        "mean_double_cost_net_bps": (mean(e["double_cost_net_bps"] for e in completed)
                                     if completed else None),
        "descriptive_week_cluster_98pct_interval_bps": (
            [mean(week_means) - half_width, mean(week_means) + half_width]
            if half_width is not None else None
        ),
        "minimum_review_sample_reached": (
            len(completed) >= gates["min_completed"]
            and len(by_week) >= gates["min_calendar_weeks"]
            and len(symbols) >= gates["min_distinct_symbols"]
        ),
        "verdict": "DESCRIPTIVE_ONLY_NOT_VERIFIED_OOS",
    }


def build_report(spec: Mapping[str, Any], data_dir: Path, *, as_of: str, mode: str = "development") -> dict[str, Any]:
    if mode not in {"development", "prospective"}:
        raise PublicShadowError("mode must be development or prospective")
    prospective = mode == "prospective"
    validate_spec(spec, prospective=prospective)
    coverage = utc(as_of)
    if prospective and coverage > datetime.now(timezone.utc):
        raise PublicShadowError("prospective coverage cannot be in the future")
    minutes = spec["bar_minutes"]
    step = timedelta(minutes=minutes)
    names = [spec["benchmark_symbol"], *spec["symbols"]]
    frames = {name: read_bars(data_dir / f"{name}.csv", minutes, coverage) for name in names}
    hashes = {name: sha256_file(data_dir / f"{name}.csv") for name in names}
    benchmark = frames[spec["benchmark_symbol"]]
    stamps = [b.timestamp for b in benchmark]
    for name, bars in frames.items():
        if [b.timestamp for b in bars] != stamps:
            raise PublicShadowError(f"{name}: time grid differs from benchmark; no forward-fill allowed")
    if prospective and coverage - (stamps[-1] + step) > step:
        raise PublicShadowError("prospective source data is stale")
    start = utc(spec["prospective_start_utc"]) if prospective else None
    cost = spec["costs_bps"]
    round_trip = 2 * cost["fee_bps_per_side"] + cost["spread_bps_round_trip"] + cost["slippage_bps_round_trip"]
    config_hash = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"),
                                             allow_nan=False).encode("utf-8")).hexdigest()
    results: list[dict[str, Any]] = []
    for experiment in spec["experiments"]:
        events: list[dict[str, Any]] = []
        overlap_skipped = 0
        for name in spec["symbols"]:
            bars = frames[name]
            next_entry_allowed = 0
            for i in range(experiment["lookback_bars"], len(bars)):
                signal_time = bars[i].timestamp + step
                if start is not None and signal_time < start:
                    continue
                if not is_signal(bars, i, experiment):
                    continue
                entry_index = i + 1
                if entry_index < next_entry_allowed:
                    overlap_skipped += 1
                    continue
                exit_index = entry_index + experiment["hold_bars"]
                next_entry_allowed = exit_index
                event: dict[str, Any] = {
                    "symbol": name,
                    "signal_time": iso(signal_time),
                    "entry_time": iso(signal_time),
                    "planned_exit_time": iso(signal_time + step * experiment["hold_bars"]),
                    "status": "pending",
                }
                if exit_index < len(bars):
                    entry = bars[entry_index].open
                    exit_ = bars[exit_index].open
                    btc_entry = benchmark[entry_index].open
                    btc_exit = benchmark[exit_index].open
                    gross = (exit_ / entry - 1) * 10_000
                    btc_gross = (btc_exit / btc_entry - 1) * 10_000
                    event.update({
                        "status": "completed",
                        "exit_time": iso(bars[exit_index].timestamp),
                        "entry_open": entry,
                        "exit_open": exit_,
                        "gross_bps": gross,
                        "net_bps": gross - round_trip,
                        "btc_matched_net_bps": btc_gross - round_trip,
                        "excess_vs_btc_bps": gross - btc_gross,
                        "double_cost_net_bps": gross - 2 * round_trip,
                    })
                events.append(event)
        events.sort(key=lambda e: (e["signal_time"], e["symbol"]))
        results.append({
            "experiment_id": experiment["id"],
            "family": experiment["family"],
            "signals_count": len(events) + overlap_skipped,
            "overlap_skipped": overlap_skipped,
            "summary": _summarize(events, spec["review_gates"]),
            "events": events,
        })
    return {
        "schema_version": 1,
        "trial_family": spec["trial_family"],
        "mode": mode,
        "status": "DEVELOPMENT_SPENT_DATA" if not prospective else "OPERATOR_DECLARED_PROSPECTIVE_UNVERIFIED",
        "as_of_utc": iso(coverage),
        "last_closed_bar_end_utc": iso(stamps[-1] + step),
        "specification_sha256": config_hash,
        "source_sha256": hashes,
        "source_authenticity_verified": False,
        "freeze_provenance_independently_verified": False,
        "verified_out_of_sample_evidence": False,
        "deployment_eligible": False,
        "order_transmission_supported": False,
        "round_trip_cost_bps": round_trip,
        "benchmark_symbol": spec["benchmark_symbol"],
        "experiments": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, research-only public-strategy shadow evaluator")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--as-of", required=True, help="UTC audited closed-bar coverage")
    parser.add_argument("--mode", choices=("development", "prospective"), default="development")
    parser.add_argument("--output", type=Path, required=True, help="exclusive-create JSON; never overwrite")
    args = parser.parse_args(argv)
    try:
        spec = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            raise PublicShadowError("config must be a JSON object")
        report = build_report(spec, args.data_dir, as_of=args.as_of, mode=args.mode)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    except (PublicShadowError, OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "output": str(args.output),
        "mode": args.mode,
        "specification_sha256": report["specification_sha256"],
        "completed": {e["experiment_id"]: e["summary"]["completed"] for e in report["experiments"]},
        "verified_out_of_sample_evidence": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Independent streaming replay and feasibility audit of PSV1 failed downside.

Shared CSV validation is reused; signal and execution logic are independently
implemented here. This is spent-data engineering evidence, never a future watch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from statistics import NormalDist, mean

from .public_strategy_shadow import Bar, iso, read_bars, sha256_file, utc

LOOKBACK = 30
HOLD = 2
CLOSE_LOCATION = 0.70
COST = 20.0
STEP = timedelta(hours=8)


def replay(symbol: str, bars: list[Bar], btc: list[Bar]) -> dict:
    if len(bars) != len(btc) or any(a.timestamp != b.timestamp for a, b in zip(bars, btc)):
        raise ValueError("independent replay requires identical UTC grids")
    history: deque[float] = deque(maxlen=LOOKBACK)
    events = []
    scheduled = {}
    exits = {}
    signals = skipped = 0
    allowed = 0
    for i, candle in enumerate(bars):
        # Process real opening marks before observing this bar's closing signal.
        if i in exits:
            event, alt_entry, btc_entry = exits.pop(i)
            gross = (candle.open / alt_entry - 1) * 10_000
            btc_gross = (btc[i].open / btc_entry - 1) * 10_000
            event.update(status="completed", exit_time=iso(candle.timestamp),
                         entry_open=alt_entry, exit_open=candle.open,
                         gross_bps=gross, net_bps=gross - COST,
                         btc_matched_net_bps=btc_gross - COST,
                         excess_vs_btc_bps=gross - btc_gross,
                         double_cost_net_bps=gross - 2 * COST)
        if i in scheduled:
            event = scheduled.pop(i)
            exits[i + HOLD] = (event, candle.open, btc[i].open)
        spread = candle.high - candle.low
        location = (candle.close - candle.low) / spread if spread > 0 else 0.0
        eligible = (len(history) == LOOKBACK and candle.low < min(history) < candle.close
                    and location >= CLOSE_LOCATION)
        if eligible:
            signals += 1
            if i + 1 < allowed:
                skipped += 1
            else:
                entry_time = candle.timestamp + STEP
                event = {"symbol": symbol, "signal_time": iso(entry_time),
                         "entry_time": iso(entry_time), "planned_exit_time": iso(entry_time + STEP * HOLD),
                         "status": "pending"}
                events.append(event)
                scheduled[i + 1] = event
                allowed = i + 1 + HOLD
        history.append(candle.low)
    return {"signals_count": signals, "overlap_skipped": skipped, "events": events}


def parity_audit(exact: dict, data_dir: Path) -> dict:
    expected = next(x for x in exact["experiments"] if x["experiment_id"] == "PSV1-FAILED-DOWNSIDE")
    frames = {s: read_bars(data_dir / f"{s}.csv", 480, utc(exact["as_of_utc"]))
              for s in exact["source_sha256"]}
    for symbol in frames:
        if sha256_file(data_dir / f"{symbol}.csv") != exact["source_sha256"][symbol]:
            raise ValueError("spent source hash mismatch")
    results = [replay(s, frames[s], frames["BTC_USDT"])
               for s in sorted(frames) if s != "BTC_USDT"]
    events = sorted([e for r in results for e in r["events"]], key=lambda e: (e["signal_time"], e["symbol"]))
    if sum(r["signals_count"] for r in results) != expected["signals_count"]:
        raise ValueError("signal count parity failed")
    if sum(r["overlap_skipped"] for r in results) != expected["overlap_skipped"]:
        raise ValueError("overlap parity failed")
    if len(events) != len(expected["events"]):
        raise ValueError("event count parity failed")
    for actual, prior in zip(events, expected["events"]):
        if actual.keys() != prior.keys():
            raise ValueError("ledger field parity failed")
        for key in prior:
            same = (math.isclose(actual[key], prior[key], rel_tol=0, abs_tol=1e-9)
                    if isinstance(prior[key], (int, float)) else actual[key] == prior[key])
            if not same:
                raise ValueError(f"ledger parity failed: {actual['symbol']} {actual['signal_time']} {key}")
    return {"study_id": "PSR1-FAILED-DOWNSIDE-FEASIBILITY", "status": "EXACT_PARITY",
            "engineering_only": True, "verified_out_of_sample_evidence": False,
            "shared_component": "strict CSV and UTC validation only",
            "independent_component": "30-low streaming deque; opening event scheduling; independent ledger and cost computation",
            "signals_count": expected["signals_count"], "overlap_skipped": expected["overlap_skipped"],
            "completed": sum(e["status"] == "completed" for e in events),
            "source_sha256": exact["source_sha256"], "events": events}


def feasibility(events: list[dict], design: dict) -> dict:
    rows = [e for e in events if e["status"] == "completed"]
    estimate = mean(e["excess_vs_btc_bps"] for e in rows)
    scores = defaultdict(float)
    for event in rows:
        year, week, _ = utc(event["exit_time"]).isocalendar()
        scores[f"{year}-W{week:02d}"] += event["excess_vs_btc_bps"] - estimate
    groups = len(scores)
    if groups < 2:
        raise ValueError("at least two weeks required for feasibility variance")
    standard_error = math.sqrt(groups / (groups - 1) * sum(v * v for v in scores.values())) / len(rows)
    alpha = design["family_alpha"] / design["multiplicity_denominator"]
    z_alpha = NormalDist().inv_cdf(1 - alpha)
    z_power = NormalDist().inv_cdf(design["target_power"])
    hurdle = design["economic_hurdle_excess_bps"]
    calendar_weeks = design["spent_grid_bars"] * 8 / (24 * 7)
    fraction = groups / calendar_weeks
    cells = []
    for truth in design["true_mean_scenarios_bps"]:
        delta = truth - hurdle
        active_weeks = math.ceil(groups * ((z_alpha + z_power) * standard_error / delta) ** 2)
        cells.append({"true_mean_excess_bps": truth, "distance_above_hurdle_bps": delta,
                      "required_active_weeks_optimistic": active_weeks,
                      "required_calendar_years_at_development_rate": active_weeks / fraction / (365.25 / 7)})
    horizons = []
    for years in design["calendar_year_scenarios"]:
        expected_groups = years * (365.25 / 7) * fraction
        horizons.append({"calendar_years": years, "expected_active_weeks_at_development_rate": expected_groups,
                         "expected_trades_at_development_rate": years * len(rows) / (calendar_weeks * 7 / 365.25),
                         "optimistic_80pct_detectable_true_excess_bps": hurdle + (z_alpha + z_power) * standard_error * math.sqrt(groups / expected_groups)})
    return {"study_id": design["study_id"], "status": "PROSPECTIVE_FREEZE_NOT_JUSTIFIED",
            "historical_mean_excess_bps": estimate, "cluster_ratio_mean_standard_error_bps": standard_error,
            "trades": len(rows), "active_week_clusters": groups, "grid_calendar_weeks": calendar_weeks,
            "active_week_fraction": fraction, "family_alpha": design["family_alpha"],
            "multiplicity_denominator": design["multiplicity_denominator"], "one_sided_alpha": alpha,
            "economic_hurdle_bps": hurdle, "target_power": design["target_power"],
            "power_scenarios": cells, "fixed_horizon_scenarios": horizons,
            "assumptions": ["Normal approximation and stationarity are optimistic, not validated power.",
                            "Independent future weekly clusters and historical event rate are assumed.",
                            "Shared market history on another venue is venue robustness, not future OOS.",
                            "Additional source survey and hypotheses mean denominator 9 is a disclosed minimum, not complete calibrated selection correction."],
            "blocking_gates": ["historical cluster uncertainty is large relative to the +5 bps hurdle",
                               "independent venue source probe returned HTTP 403",
                               "venue/account fee tier and historic executable spread/slippage remain uncalibrated"],
            "prospective_start_utc": None, "candidate_frozen": False, "deployment_eligible": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    exact = json.loads(args.exact_report.read_text(encoding="utf-8"))
    design = json.loads(args.design.read_text(encoding="utf-8"))
    audit = parity_audit(exact, args.data_dir)
    power = feasibility(audit["events"], design)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("independent_replay.json", audit), ("feasibility.json", power)):
        value["design_sha256"] = hashlib.sha256(args.design.read_bytes()).hexdigest()
        with (args.output_dir / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"parity": audit["status"], "completed": audit["completed"],
                      "feasibility": power["status"], "standard_error_bps": power["cluster_ratio_mean_standard_error_bps"]}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Frozen FX Asian-range breakout v1 evaluator.

Input: one CSV per pair named EURUSD.csv, GBPUSD.csv, USDJPY.csv, AUDUSD.csv
with columns: timestamp,open,high,low,close. Timestamp must be ISO-8601 UTC.

This script implements only the frozen protocol in
research/fx_asian_range_breakout_v1/FREEZE.json.
"""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PAIRS = ("EURUSD","GBPUSD","USDJPY","AUDUSD")
RANGE_HOURS = (0,1,2,3,4,5)
SEARCH_HOURS = (6,7,8,9)

def parse_ts(s: str) -> datetime:
    s = s.replace("Z","+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def load_pair(path: Path):
    out = defaultdict(dict)
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            dt = parse_ts(r["timestamp"])
            if dt.minute or dt.second or dt.microsecond:
                raise ValueError(f"non-hourly timestamp: {dt}")
            out[dt.date()][dt.hour] = {
                "o": float(r["open"]), "h": float(r["high"]),
                "l": float(r["low"]), "c": float(r["close"])
            }
    return out

def evaluate_pair(days, start, end):
    signals = []
    d0 = datetime.fromisoformat(start).date()
    d1 = datetime.fromisoformat(end).date()
    for day, hours in sorted(days.items()):
        if day < d0 or day > d1 or day.weekday() >= 5:
            continue
        if any(h not in hours for h in RANGE_HOURS):
            continue
        hi = max(hours[h]["h"] for h in RANGE_HOURS)
        lo = min(hours[h]["l"] for h in RANGE_HOURS)
        direction = None
        signal_hour = None
        invalid = False
        for h in SEARCH_HOURS:
            if h not in hours:
                invalid = True
                break
            c = hours[h]["c"]
            if c > hi:
                direction, signal_hour = 1, h
                break
            if c < lo:
                direction, signal_hour = -1, h
                break
        if invalid or direction is None:
            continue
        entry_h = signal_hour + 1
        if entry_h not in hours or 16 not in hours:
            continue
        entry = hours[entry_h]["o"]
        exit_ = hours[16]["o"]
        gross = direction * (exit_ / entry - 1.0) * 10000.0
        signals.append({
            "date": day.isoformat(),
            "direction": direction,
            "signal_hour": signal_hour,
            "entry_hour": entry_h,
            "gross_bps": gross,
            "net2_bps": gross - 2.0,
            "net4_bps": gross - 4.0,
            "reversed_net2_bps": -gross - 2.0,
        })
    return signals

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", type=Path)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()
    all_rows = []
    per_pair = {}
    for pair in PAIRS:
        rows = evaluate_pair(load_pair(args.input_dir / f"{pair}.csv"), args.start, args.end)
        for r in rows:
            r["pair"] = pair
        all_rows.extend(rows)
        per_pair[pair] = {
            "signals": len(rows),
            "mean_net2_bps": sum(x["net2_bps"] for x in rows)/len(rows) if rows else None,
            "mean_net4_bps": sum(x["net4_bps"] for x in rows)/len(rows) if rows else None,
            "total_net2_bps": sum(x["net2_bps"] for x in rows),
        }
    n = len(all_rows)
    result = {
        "signals": n,
        "distinct_signal_days": len({x["date"] for x in all_rows}),
        "pooled_mean_net2_bps": sum(x["net2_bps"] for x in all_rows)/n if n else None,
        "pooled_mean_net4_bps": sum(x["net4_bps"] for x in all_rows)/n if n else None,
        "reversed_mean_net2_bps": sum(x["reversed_net2_bps"] for x in all_rows)/n if n else None,
        "per_pair": per_pair,
    }
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()

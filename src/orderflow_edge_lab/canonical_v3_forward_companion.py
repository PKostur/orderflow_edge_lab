"""Forward companion: post-start trades scored under canonical accounting v2 and v3.

Pre-registered before its prospective start. It changes no strategy, signal,
cost or frozen protocol; it only reports the same forward trades under both
accounting versions, descriptively.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy, run_canonical_backtest

WATCH_ID = "universal-canonical-v3-forward-companion-v1"


class CompanionError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def completed_frame(frame: pd.DataFrame, *, as_of: Any, minimum: int) -> pd.DataFrame:
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise CompanionError("duplicate timestamps")
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.loc[out.index + pd.Timedelta(hours=8) <= _utc(as_of)]
    values = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise CompanionError("invalid OHLC")
    if len(out) < minimum:
        raise CompanionError(f"fewer than {minimum} completed bars")
    return out


def _metrics(values: Sequence[float]) -> dict[str, Any]:
    wins = sum(v for v in values if v > 0.0)
    losses = -sum(v for v in values if v < 0.0)
    return {
        "expectancy_bps": float(np.mean(values)) if values else None,
        "median_bps": float(np.median(values)) if values else None,
        "win_rate": sum(v > 0.0 for v in values) / len(values) if values else None,
        "profit_factor": wins / losses if losses > 0.0 else None,
        "sum_bps": float(np.sum(values)) if values else 0.0,
    }


def build_report(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], *, as_of: Any) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise CompanionError("wrong watch config")
    start = _utc(config["prospective_start_utc"])
    as_of_ts = _utc(as_of)
    source = config["source"]
    minimum = int(source["minimum_completed_bars"])
    clean = {s: completed_frame(frames[s], as_of=as_of_ts, minimum=minimum) for s in source["symbols"]}
    execution = ExecutionModel(
        round_trip_cost_bps=float(config["economics"]["round_trip_cost_bps"]),
        max_abs_position=float(config["economics"]["max_abs_position"]),
    )
    strategies = []
    for spec in config["strategies"]:
        strategy = legacy_strategy(str(spec["family"]))
        completed: list[dict[str, Any]] = []
        open_count = 0
        for symbol in source["symbols"]:
            v2 = run_canonical_backtest(clean[symbol], strategy, dict(spec["parameters"]), execution)["trades_ledger"]
            v3 = run_canonical_backtest_v3(clean[symbol], strategy, dict(spec["parameters"]), execution)["trades_ledger"]
            if [(t["entry"], t["side"]) for t in v2] != [(t["entry"], t["side"]) for t in v3]:
                raise CompanionError(f"{spec['audit_id']}/{symbol}: v2 and v3 episodes differ")
            for a, b in zip(v2, v3):
                if _utc(a["entry"]) < start:
                    continue
                if b["terminal_liquidation"]:
                    open_count += 1
                    continue
                completed.append({
                    "symbol": symbol, "entry": _utc(a["entry"]).isoformat(), "exit": str(a["exit"]),
                    "side": int(a["side"]), "v2_net_bps": float(a["net_bps"]), "v3_net_bps": float(b["net_bps"]),
                    "v2_gross_bps": float(a["gross_bps"]), "v3_gross_bps": float(b["gross_bps"]),
                })
        by_direction = {}
        for direction, side in (("ALL", None), ("LONG", 1), ("SHORT", -1)):
            rows = [r for r in completed if side is None or r["side"] == side]
            by_direction[direction] = {
                "n": len(rows),
                "v2": _metrics([r["v2_net_bps"] for r in rows]),
                "v3": _metrics([r["v3_net_bps"] for r in rows]),
            }
        strategies.append({
            "audit_id": str(spec["audit_id"]),
            "completed_trade_count": len(completed),
            "open_episode_count": open_count,
            "by_direction": by_direction,
            "completed_trades": completed,
        })
    days = max(0, int((as_of_ts - start).total_seconds() // 86400)) if as_of_ts >= start else 0
    return {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if as_of_ts < start else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "calendar_days_elapsed": days,
        "review_window_open": days >= int(config["reporting"]["review_after_calendar_days"]),
        "strategies": strategies,
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    parser = argparse.ArgumentParser(description="Run the canonical v3 forward companion watch.")
    parser.add_argument("--config", default="config/universal_canonical_v3_forward_companion_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    source = config["source"]
    frames = {
        s: fetch_mexc_futures_klines(s, source["interval"], source["warmup_start_utc"], as_of.isoformat())
        for s in source["symbols"]
    }
    report = build_report(config, frames, as_of=as_of)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "trades": {s["audit_id"]: s["completed_trade_count"] for s in report["strategies"]}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

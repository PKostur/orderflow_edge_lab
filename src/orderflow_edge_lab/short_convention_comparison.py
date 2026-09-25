"""Descriptive comparison of short-side accounting conventions.

The canonical v2 ledger compounds ``prod(1 + pos_t * r_t)``.  For a +/-1 long
that equals a fixed-quantity position; for a +/-1 short it is a constant-notional
short rebalanced every bar, with no charge for the implied turnover.  A
fixed-contract futures short earns ``1 - exit/entry``.  This module re-scores the
same frozen trades under both conventions.  It changes no trade, signal, cost or
canonical accounting rule and authorizes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import _utc
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    legacy_strategy,
    run_canonical_backtest,
)
from orderflow_edge_lab.universal_existing_validation import load_protocol, load_snapshot

ANALYSIS = "short_convention_comparison_v1"


class ShortConventionError(ValueError):
    pass


def static_net_bps(static_gross_bps: float, round_trip_cost_bps: float) -> float:
    side_cost = round_trip_cost_bps / 2.0 / 10_000.0
    return ((1.0 + static_gross_bps / 10_000.0) * (1.0 - side_cost) ** 2 - 1.0) * 10_000.0


def trade_pair(trade: Mapping[str, Any], frame: pd.DataFrame, *, cost_bps: float) -> dict[str, Any]:
    if abs(float(trade.get("entry_position", trade["side"]))) != 1.0:
        raise ShortConventionError("only unit-position episodes have a defined fixed-quantity equivalent")
    side = int(trade["side"])
    opens = frame["open"].astype(float)
    entry = float(opens.loc[_utc(trade["entry"])])
    exit_ = float(opens.loc[_utc(trade["exit"])])
    static_gross = side * (exit_ / entry - 1.0) * 10_000.0
    return {
        "side_label": "LONG" if side > 0 else "SHORT",
        "entry": str(trade["entry"]),
        "ledger_gross_bps": float(trade["gross_bps"]),
        "ledger_net_bps": float(trade["net_bps"]),
        "static_gross_bps": static_gross,
        "static_net_bps": static_net_bps(static_gross, cost_bps),
    }


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


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for direction in ("ALL", "LONG", "SHORT"):
        subset = [r for r in rows if direction == "ALL" or r["side_label"] == direction]
        out[direction] = {
            "n": len(subset),
            "ledger": _metrics([float(r["ledger_net_bps"]) for r in subset]),
            "static": _metrics([float(r["static_net_bps"]) for r in subset]),
        }
    return out


def build_report(protocol_path: str | Path, data_dir: str | Path) -> dict[str, Any]:
    protocol = load_protocol(protocol_path)
    frames, snapshot = load_snapshot(protocol, data_dir)
    cost_reports = []
    for cost in [float(v) for v in protocol["costs_bps"]]:
        strategies = []
        for spec in protocol["strategies"]:
            strategy = legacy_strategy(str(spec["family"]))
            rows = []
            censored = 0
            for symbol in sorted(frames):
                ledger = run_canonical_backtest(
                    frames[symbol], strategy, dict(spec["parameters"]),
                    ExecutionModel(round_trip_cost_bps=cost),
                )["trades_ledger"]
                for trade in ledger or []:
                    if trade.get("terminal_liquidation"):
                        censored += 1
                        continue
                    rows.append(trade_pair(trade, frames[symbol], cost_bps=cost))
            strategies.append({
                "audit_id": str(spec["audit_id"]),
                "family": str(spec["family"]),
                "right_censored_open_episodes": censored,
                "by_direction": summarize(rows),
            })
        cost_reports.append({"cost_bps": cost, "strategies": strategies})
    return {
        "schema_version": 1,
        "analysis": ANALYSIS,
        "status": "descriptive_accounting_diagnostic",
        "source_protocol": str(protocol["protocol_name"]),
        "source_window": {k: protocol["data"][k] for k in ("start", "end_exclusive", "interval")},
        "conventions": {
            "ledger": "canonical v2: prod(1 + pos_t * r_t); +/-1 short is constant-notional, rebalanced each bar, rebalancing turnover uncharged",
            "static": "fixed quantity: side * (exit_open / entry_open - 1), entry and exit side costs charged",
        },
        "disclosure": "The ledger-minus-static short gap distribution was viewed in payoff geometry v1.1 before this diagnostic was written. No threshold or strategy definition is derived from it.",
        "cost_cases": cost_reports,
        "data_snapshot": snapshot,
        "claims": {
            "canonical_accounting_modified": False,
            "strategy_definitions_modified": False,
            "verified_out_of_sample_evidence": False,
            "strategy_promotion_authorized": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Compare short accounting conventions on frozen trades.")
    parser.add_argument("--protocol", default="config/universal_existing_strategy_backtests_v1.json")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = build_report(args.protocol, args.data_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

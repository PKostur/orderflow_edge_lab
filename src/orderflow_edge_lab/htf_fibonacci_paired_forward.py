from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.htf_fibonacci_forward_shadow import build_forward_report as build_fib_report
from orderflow_edge_lab.htf_trend_forward_shadow import (
    HtfTrendForwardError,
    build_forward_report as build_baseline_report,
    verify_candidate_spec,
)


def _trade_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = np.asarray([float(row["net_return"]) for row in rows], dtype=float)
    if len(returns) == 0:
        return {
            "completed_trades": 0,
            "expectancy_bps": None,
            "profit_factor": None,
            "profit_factor_infinite": false,
            "win_rate": None,
        }
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    infinite_pf = losses <= 0 and gains > 0
    pf = gains / losses if losses > 0 else None
    return {
        "completed_trades": int(len(returns)),
        "expectancy_bps": float(returns.mean() * 10_000.0),
        "profit_factor": float(pf) if pf is not None else None,
        "profit_factor_infinite": bool(infinite_pf),
        "win_rate": float(np.mean(returns > 0)),
    }


def _entries(report: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for row in list(report.get("completed_trades", [])) + list(report.get("open_positions", [])):
        out.add((str(row["symbol"]), str(row["entry_time"]), str(row["side"])))
    return out


def _concentration(report: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(report.get("completed_trades", []))
    if not rows:
        return {
            "completed_trades": 0,
            "distinct_symbols": 0,
            "max_symbol_share": None,
            "symbol_counts": {},
            "distinct_iso_weeks": 0,
            "week_counts": {},
        }
    symbols = Counter(str(row["symbol"]) for row in rows)
    weeks = Counter(
        pd.Timestamp(row["entry_time"]).strftime("%G-W%V") for row in rows
    )
    total = float(len(rows))
    return {
        "completed_trades": int(len(rows)),
        "distinct_symbols": int(len(symbols)),
        "max_symbol_share": float(max(symbols.values()) / total),
        "symbol_counts": dict(sorted(symbols.items())),
        "distinct_iso_weeks": int(len(weeks)),
        "week_counts": dict(sorted(weeks.items())),
    }


def _paired_intervals(
    baseline: Mapping[str, Any], fib: Mapping[str, Any]
) -> dict[str, Any]:
    def keyed(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
        return {
            (str(row["start"]), str(row["end"])): row
            for row in report.get("portfolio_intervals", [])
        }

    base_rows = keyed(baseline)
    fib_rows = keyed(fib)
    common = sorted(set(base_rows) & set(fib_rows))
    deltas = np.asarray(
        [
            float(fib_rows[key]["net_return"])
            - float(base_rows[key]["net_return"])
            for key in common
        ],
        dtype=float,
    )
    return {
        "common_intervals": int(len(common)),
        "baseline_only_intervals": int(len(set(base_rows) - set(fib_rows))),
        "fib_only_intervals": int(len(set(fib_rows) - set(base_rows))),
        "mean_fib_minus_baseline_interval_return_bps": (
            float(deltas.mean() * 10_000.0) if len(deltas) else None
        ),
        "positive_delta_interval_fraction": (
            float(np.mean(deltas > 0)) if len(deltas) else None
        ),
    }


def _validate_pair(
    baseline_candidate: Mapping[str, Any], fib_candidate: Mapping[str, Any]
) -> None:
    if not verify_candidate_spec(baseline_candidate):
        raise HtfTrendForwardError("paired baseline candidate hash is invalid")
    if not verify_candidate_spec(fib_candidate):
        raise HtfTrendForwardError("paired Fibonacci candidate hash is invalid")
    if baseline_candidate["forward_signal_start_utc"] != fib_candidate["forward_signal_start_utc"]:
        raise HtfTrendForwardError("paired candidates do not share the forward boundary")
    if baseline_candidate["specification"] != fib_candidate["specification"]:
        raise HtfTrendForwardError("paired candidates do not share identical strategy economics")
    if baseline_candidate["forward_protocol"]["position_state_at_boundary"] != "flat":
        raise HtfTrendForwardError("paired baseline must reset flat at the boundary")
    if fib_candidate["forward_protocol"]["position_state_at_boundary"] != "flat":
        raise HtfTrendForwardError("paired Fibonacci arm must reset flat at the boundary")


def build_paired_report(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    baseline_candidate: Mapping[str, Any],
    fib_candidate: Mapping[str, Any],
    *,
    as_of_utc: str | pd.Timestamp,
    baseline_candidate_file_sha256: str | None = None,
    fib_candidate_file_sha256: str | None = None,
    source_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _validate_pair(baseline_candidate, fib_candidate)
    baseline = build_baseline_report(
        frames,
        funding,
        baseline_candidate,
        as_of_utc=as_of_utc,
        candidate_file_sha256=baseline_candidate_file_sha256,
        source_sha256=source_sha256,
    )
    fib = build_fib_report(
        frames,
        funding,
        fib_candidate,
        as_of_utc=as_of_utc,
        candidate_file_sha256=fib_candidate_file_sha256,
        source_sha256=source_sha256,
    )

    baseline_entries = _entries(baseline)
    fib_entries = _entries(fib)
    unexpected_fib_entries = sorted(fib_entries - baseline_entries)
    if unexpected_fib_entries:
        raise HtfTrendForwardError(
            f"Fibonacci arm contains entries that are not baseline entry transitions: {unexpected_fib_entries[:3]}"
        )

    baseline_trade_stats = _trade_stats(baseline["completed_trades"])
    fib_trade_stats = _trade_stats(fib["completed_trades"])
    minimum = int(
        fib_candidate["forward_protocol"]["minimum_completed_forward_trades_for_edge_review"]
    )
    reviewable = (
        int(fib_trade_stats["completed_trades"]) >= minimum
        and int(baseline_trade_stats["completed_trades"]) >= minimum
    )

    base_metrics = baseline["metrics"]
    fib_metrics = fib["metrics"]
    return {
        "schema_version": 1,
        "experiment": "htf-fibonacci-paired-forward-v1",
        "as_of_utc": fib["as_of_utc"],
        "forward_signal_start_utc": fib["forward_signal_start_utc"],
        "baseline_candidate_id": baseline_candidate["candidate_id"],
        "baseline_candidate_spec_sha256": baseline_candidate["spec_sha256"],
        "fibonacci_candidate_id": fib_candidate["candidate_id"],
        "fibonacci_candidate_spec_sha256": fib_candidate["spec_sha256"],
        "source_sha256": dict(source_sha256 or {}),
        "status": "reviewable_trade_count_reached" if reviewable else fib["status"],
        "entry_subset_verified": True,
        "minimum_completed_trades_per_arm_for_edge_review": minimum,
        "paired_reviewable": bool(reviewable),
        "baseline": {
            "metrics": base_metrics,
            "trade_stats": baseline_trade_stats,
            "current_weights": baseline["current_weights"],
            "completed_trades": baseline["completed_trades"],
            "open_positions": baseline["open_positions"],
        },
        "fibonacci": {
            "metrics": fib_metrics,
            "trade_stats": fib_trade_stats,
            "current_weights": fib["current_weights"],
            "completed_trades": fib["completed_trades"],
            "open_positions": fib["open_positions"],
            "concentration": _concentration(fib),
        },
        "paired_deltas": {
            "net_return": float(fib_metrics["net_return"] - base_metrics["net_return"]),
            "net_pnl_per_1000_usdt": float(
                fib_metrics["net_pnl_per_1000_usdt"]
                - base_metrics["net_pnl_per_1000_usdt"]
            ),
            "max_drawdown": float(
                fib_metrics["max_drawdown"] - base_metrics["max_drawdown"]
            ),
            "trade_expectancy_bps": (
                float(
                    fib_trade_stats["expectancy_bps"]
                    - baseline_trade_stats["expectancy_bps"]
                )
                if fib_trade_stats["expectancy_bps"] is not None
                and baseline_trade_stats["expectancy_bps"] is not None
                else None
            ),
        },
        "paired_interval_diagnostics": _paired_intervals(baseline, fib),
        "claims": {
            "contemporaneous_control_frozen_before_first_executable_signal": True,
            "same_strategy_economics_except_fibonacci_entry_gate": True,
            "paper_shadow_only": True,
            "paired_reviewable": bool(reviewable),
            "pnl_used_to_retune_or_select_parameters": False,
            "verified_profitable_edge": False,
            "live_order_transmission_supported": False,
        },
    }

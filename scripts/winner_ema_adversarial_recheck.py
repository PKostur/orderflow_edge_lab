from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import evaluate_variant_across_symbols, generate_target_position


PRIMARY = {"fast": 24, "slow": 96, "atr_period": 14, "min_atr_spread": 0.25}
NEIGHBORHOOD = [
    {"fast": fast, "slow": 96, "atr_period": 14, "min_atr_spread": threshold}
    for fast in (6, 12, 24)
    for threshold in (0.0, 0.25)
]
COST_CASES = (12.0, 20.0, 40.0)


def load_frames(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    root = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(root.glob("*_8h.csv")):
        symbol = path.name.removesuffix("_8h.csv")
        frame = pd.read_csv(path, parse_dates=["timestamp"])
        if "timestamp" not in frame.columns:
            raise ValueError(f"{path}: missing timestamp")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp").sort_index()
        if frame.index.has_duplicates:
            raise ValueError(f"{symbol}: duplicate timestamps")
        frames[symbol] = frame
    if len(frames) < 8:
        raise ValueError(f"require at least eight symbols, found {len(frames)}")
    return frames


def align_shared_history(frames: Mapping[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    if not frames:
        raise ValueError("no frames")
    starts = {symbol: frame.index.min() for symbol, frame in frames.items() if len(frame)}
    ends = {symbol: frame.index.max() for symbol, frame in frames.items() if len(frame)}
    if len(starts) != len(frames):
        raise ValueError("empty frame in research panel")
    shared_start = max(starts.values())
    shared_end = min(ends.values())
    if shared_end <= shared_start:
        raise ValueError("no shared history window")
    aligned = {
        symbol: frame[(frame.index >= shared_start) & (frame.index <= shared_end)].copy()
        for symbol, frame in frames.items()
    }
    too_short = {symbol: len(frame) for symbol, frame in aligned.items() if len(frame) < 200}
    if too_short:
        raise ValueError(f"shared window too short: {too_short}")
    return aligned, {
        "shared_start": shared_start.isoformat(),
        "shared_end": shared_end.isoformat(),
        "symbols": sorted(aligned),
        "rows_by_symbol": {symbol: len(frame) for symbol, frame in sorted(aligned.items())},
        "original_start_by_symbol": {symbol: ts.isoformat() for symbol, ts in sorted(starts.items())},
        "original_end_by_symbol": {symbol: ts.isoformat() for symbol, ts in sorted(ends.items())},
    }


def _portfolio_series(
    frames: Mapping[str, pd.DataFrame],
    params: Mapping[str, Any],
    *,
    round_trip_cost_bps: float,
) -> pd.DataFrame:
    symbols = sorted(frames)
    common_index = frames[symbols[0]].index
    for symbol in symbols[1:]:
        common_index = common_index.intersection(frames[symbol].index)
    common_index = common_index.sort_values()
    if len(common_index) < 200:
        raise ValueError("insufficient common bars for portfolio simulation")

    opens = pd.DataFrame(index=common_index, columns=symbols, dtype=float)
    positions = pd.DataFrame(index=common_index, columns=symbols, dtype=float)
    for symbol in symbols:
        frame = frames[symbol].reindex(common_index)
        opens[symbol] = pd.to_numeric(frame["open"], errors="coerce")
        target = generate_target_position(frame, "ema_tsmom", params).reindex(common_index).fillna(0.0).clip(-1.0, 1.0)
        positions[symbol] = target.shift(1).fillna(0.0)

    active = (positions != 0.0).sum(axis=1)
    weights = positions.div(active.replace(0, np.nan), axis=0).fillna(0.0)
    next_open = opens.shift(-1)
    asset_return = next_open / opens - 1.0
    gross = (weights * asset_return).sum(axis=1)
    turnover = weights.diff().fillna(weights).abs().sum(axis=1)
    side_cost = float(round_trip_cost_bps) / 2.0 / 10_000.0
    net = gross - turnover * side_cost
    out = pd.DataFrame({"gross": gross, "turnover": turnover, "net": net}, index=common_index)
    return out.iloc[:-1].copy()


def _series_stats(net: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(net, errors="coerce").dropna()
    if values.empty:
        return {"bars": 0, "net_return": None, "max_drawdown": None, "sharpe": None, "mean_bar_bps": None}
    equity = (1.0 + values).cumprod()
    peaks = equity.cummax()
    drawdown = equity / peaks - 1.0
    mean = float(values.mean())
    std = float(values.std(ddof=0))
    bars_per_year = 365.25 * 3.0
    sharpe = mean / std * math.sqrt(bars_per_year) if std > 0 else None
    return {
        "bars": len(values),
        "net_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float(drawdown.min()),
        "sharpe": float(sharpe) if sharpe is not None and math.isfinite(sharpe) else None,
        "mean_bar_bps": mean * 10_000.0,
        "positive_bar_fraction": float((values > 0).mean()),
    }


def _portfolio_fold_stats(series: pd.DataFrame, fold_days: int = 120) -> list[dict[str, Any]]:
    start = series.index.min().normalize()
    end = series.index.max()
    cursor = start
    delta = pd.Timedelta(days=int(fold_days))
    rows: list[dict[str, Any]] = []
    while cursor <= end:
        nxt = cursor + delta
        member = series[(series.index >= cursor) & (series.index < nxt)]
        if len(member):
            rows.append({"fold_start": cursor.isoformat(), "fold_end": nxt.isoformat(), **_series_stats(member["net"])})
        cursor = nxt
    return rows


def _cluster_diagnostic(frames: Mapping[str, pd.DataFrame], params: Mapping[str, Any], cost: float) -> dict[str, Any]:
    report = evaluate_variant_across_symbols(
        frames,
        "ema_tsmom",
        params,
        fold_days=120,
        round_trip_cost_bps=float(cost),
    )
    clusters = report["per_time_fold_cluster"]
    starts = [pd.Timestamp(row["fold_start"]) for row in clusters]
    non_overlapping = all((b - a) >= pd.Timedelta(days=120) for a, b in zip(starts, starts[1:]))
    return {
        "parameters": dict(params),
        "round_trip_cost_bps": float(cost),
        "dependence_cluster": report["dependence_cluster"],
        "independent_fold_observations": report["fold_observations"],
        "positive_fold_fraction": report["positive_fold_fraction"],
        "median_fold_expectancy_bps": report["median_fold_expectancy_bps"],
        "median_fold_profit_factor": report["median_fold_profit_factor"],
        "total_trades_across_folds": report["total_trades_across_folds"],
        "fold_windows_non_overlapping": bool(non_overlapping),
        "per_time_fold_cluster": clusters,
    }


def build_report(frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    aligned, lineage = align_shared_history(frames)
    neighborhood: list[dict[str, Any]] = []
    for params in NEIGHBORHOOD:
        for cost in COST_CASES:
            cluster = _cluster_diagnostic(aligned, params, cost)
            portfolio = _series_stats(_portfolio_series(aligned, params, round_trip_cost_bps=cost)["net"])
            neighborhood.append({**cluster, "equal_weight_portfolio": portfolio})

    primary_portfolio = _portfolio_series(aligned, PRIMARY, round_trip_cost_bps=20.0)
    primary_folds = _portfolio_fold_stats(primary_portfolio, fold_days=120)
    leave_one_out = []
    for excluded in sorted(aligned):
        subset = {symbol: frame for symbol, frame in aligned.items() if symbol != excluded}
        leave_one_out.append({
            "excluded_symbol": excluded,
            **_series_stats(_portfolio_series(subset, PRIMARY, round_trip_cost_bps=20.0)["net"]),
        })

    primary_cluster = next(
        row for row in neighborhood
        if row["parameters"] == PRIMARY and row["round_trip_cost_bps"] == 20.0
    )
    diagnostic_pass = bool(
        primary_cluster["independent_fold_observations"] >= 5
        and primary_cluster["positive_fold_fraction"] is not None
        and primary_cluster["positive_fold_fraction"] >= 0.60
        and primary_cluster["median_fold_expectancy_bps"] is not None
        and primary_cluster["median_fold_expectancy_bps"] > 0
        and primary_cluster["median_fold_profit_factor"] is not None
        and primary_cluster["median_fold_profit_factor"] > 1.20
        and primary_cluster["fold_windows_non_overlapping"]
        and all(row["net_return"] is not None and row["net_return"] > 0 for row in leave_one_out)
    )

    return {
        "schema_version": 1,
        "experiment": "winner_ema_adversarial_recheck_v1",
        "purpose": "Correct overlapping dependence-fold accounting and adversarially recheck the already-frozen EMA24/96 ATR0.25 development candidate plus its parameter neighborhood.",
        "lineage": lineage,
        "primary_candidate": PRIMARY,
        "neighborhood": neighborhood,
        "primary_portfolio_120d_folds": primary_folds,
        "primary_leave_one_symbol_out": leave_one_out,
        "diagnostic_screen_passed": diagnostic_pass,
        "limitations": {
            "historical_funding_included": False,
            "portfolio_spread_slippage_latency_beyond_round_trip_cost_included": False,
            "multiple_testing_is_eliminated": False,
            "this_recheck_is_untouched_oos": False,
            "reason": "The development outcomes were already inspected before this correction; the recheck can invalidate or support robustness but cannot create a new OOS claim."
        },
        "claims": {
            "development_robustness_diagnostic_only": True,
            "candidate_parameters_changed": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "standalone_strategy_promotable": False,
            "live_order_transmission_supported": False
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Adversarial shared-window recheck of the frozen 8h EMA trend candidate and parameter neighborhood.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report(load_frames(args.data_dir))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    primary = next(
        row for row in report["neighborhood"]
        if row["parameters"] == PRIMARY and row["round_trip_cost_bps"] == 20.0
    )
    print(json.dumps({
        "output": str(output),
        "shared_start": report["lineage"]["shared_start"],
        "shared_end": report["lineage"]["shared_end"],
        "independent_folds": primary["independent_fold_observations"],
        "positive_fold_fraction": primary["positive_fold_fraction"],
        "median_fold_expectancy_bps": primary["median_fold_expectancy_bps"],
        "median_fold_profit_factor": primary["median_fold_profit_factor"],
        "portfolio_net_return": primary["equal_weight_portfolio"]["net_return"],
        "portfolio_max_drawdown": primary["equal_weight_portfolio"]["max_drawdown"],
        "diagnostic_screen_passed": report["diagnostic_screen_passed"],
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

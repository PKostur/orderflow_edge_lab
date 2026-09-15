from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

DEFAULT_SYMBOLS = [
    "BTC_USDT",
    "ETH_USDT",
    "SOL_USDT",
    "XRP_USDT",
    "DOGE_USDT",
    "LINK_USDT",
    "SUI_USDT",
    "ENA_USDT",
]
DEFAULT_INTERVALS = ["5m", "15m", "1h"]
BASE_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
VARIANTS = ["original_lookahead", "confirmed_htf", "same_tf"]
DEFAULT_COSTS_BPS = [0.0, 12.0, 16.0, 20.0]
DEFAULT_WARMUP_DAYS = 7


def _as_utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def smma(series: pd.Series, length: int) -> pd.Series:
    """TradingView-style SMMA/RMA seeded with an SMA."""
    values = series.astype(float).to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < length:
        return pd.Series(out, index=series.index, dtype=float)
    out[length - 1] = float(np.mean(values[:length]))
    alpha = 1.0 / float(length)
    for i in range(length, len(values)):
        out[i] = out[i - 1] + alpha * (values[i] - out[i - 1])
    return pd.Series(out, index=series.index, dtype=float)


def _htf_frame(frame: pd.DataFrame, base_minutes: int, multiplier: int) -> pd.DataFrame:
    freq = f"{base_minutes * multiplier}min"
    return (
        frame.resample(freq, origin="epoch", label="left", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["open", "close"])
    )


def occ_lines(
    frame: pd.DataFrame,
    *,
    base_minutes: int,
    length: int,
    multiplier: int,
    variant: str,
) -> tuple[pd.Series, pd.Series]:
    if variant == "same_tf":
        return smma(frame["open"], length), smma(frame["close"], length)

    htf = _htf_frame(frame, base_minutes, multiplier)
    open_htf = smma(htf["open"], length)
    close_htf = smma(htf["close"], length)
    freq = f"{base_minutes * multiplier}min"
    bins = frame.index.floor(freq)

    if variant == "original_lookahead":
        # Diagnostic reproduction of historical security(..., lookahead_on):
        # every lower-timeframe bar inside the current HTF bucket receives
        # the final value of that same HTF candle.
        source_bins = bins
    elif variant == "confirmed_htf":
        # Causal equivalent: only the last fully completed HTF candle is known.
        source_bins = bins - pd.Timedelta(base_minutes * multiplier, unit="min")
    else:
        raise ValueError(f"unsupported OCC variant: {variant}")

    open_map = open_htf.to_dict()
    close_map = close_htf.to_dict()
    open_line = pd.Series(source_bins.map(open_map), index=frame.index, dtype=float)
    close_line = pd.Series(source_bins.map(close_map), index=frame.index, dtype=float)
    return open_line, close_line


def _efficiency_regime(frame: pd.DataFrame, lookback: int = 48) -> pd.Series:
    close = frame["close"].astype(float)
    displacement = (close - close.shift(lookback)).abs()
    path = close.diff().abs().rolling(lookback).sum()
    efficiency = displacement / path.replace(0.0, np.nan)
    out = pd.Series("mixed", index=frame.index, dtype=object)
    out.loc[efficiency <= 0.15] = "range"
    out.loc[efficiency >= 0.35] = "trend"
    out.loc[efficiency.isna()] = "warmup"
    return out


def build_trades(
    frame: pd.DataFrame,
    open_line: pd.Series,
    close_line: pd.Series,
    *,
    symbol: str,
    interval: str,
    variant: str,
) -> pd.DataFrame:
    above = close_line > open_line
    below = close_line < open_line
    long_signal = above & (~above.shift(1, fill_value=False))
    short_signal = below & (~below.shift(1, fill_value=False))

    direction = pd.Series(0, index=frame.index, dtype=int)
    direction.loc[long_signal] = 1
    direction.loc[short_signal] = -1

    # Pine strategy.entry() market orders historically fill on the next bar.
    fills: list[tuple[pd.Timestamp, int, float]] = []
    idx = frame.index
    opens = frame["open"].astype(float)
    for pos, _ts in enumerate(idx[:-1]):
        side = int(direction.iloc[pos])
        if side == 0:
            continue
        fill_ts = idx[pos + 1]
        fills.append((fill_ts, side, float(opens.iloc[pos + 1])))

    regimes = _efficiency_regime(frame)
    trades: list[dict[str, object]] = []
    current_side = 0
    entry_ts: pd.Timestamp | None = None
    entry_price = math.nan

    for fill_ts, new_side, fill_price in fills:
        if current_side == 0:
            current_side = new_side
            entry_ts = fill_ts
            entry_price = fill_price
            continue
        if new_side == current_side:
            continue

        gross_return = current_side * (fill_price / entry_price - 1.0)
        trades.append(
            {
                "symbol": symbol,
                "interval": interval,
                "variant": variant,
                "side": "long" if current_side > 0 else "short",
                "entry_time": entry_ts,
                "exit_time": fill_ts,
                "entry_price": entry_price,
                "exit_price": fill_price,
                "gross_return": gross_return,
                "gross_bps": gross_return * 10000.0,
                "entry_regime": str(regimes.get(entry_ts, "unknown")),
            }
        )
        current_side = new_side
        entry_ts = fill_ts
        entry_price = fill_price

    return pd.DataFrame(trades)


def _profit_factor(returns: pd.Series) -> float:
    wins = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    if losses == 0.0:
        return math.inf if wins > 0.0 else math.nan
    return wins / losses


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return math.nan
    equity = (1.0 + returns).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def summarize(trades: pd.DataFrame, cost_bps: float) -> dict[str, object]:
    if trades.empty:
        return {
            "round_trip_cost_bps": cost_bps,
            "trades": 0,
            "gross_expectancy_bps": math.nan,
            "net_expectancy_bps": math.nan,
            "net_win_rate": math.nan,
            "net_profit_factor": math.nan,
            "net_compounded_return": math.nan,
            "net_max_drawdown": math.nan,
        }
    gross = trades["gross_return"].astype(float)
    net = gross - cost_bps / 10000.0
    return {
        "round_trip_cost_bps": cost_bps,
        "trades": int(len(trades)),
        "gross_expectancy_bps": float(gross.mean() * 10000.0),
        "net_expectancy_bps": float(net.mean() * 10000.0),
        "net_win_rate": float((net > 0.0).mean()),
        "net_profit_factor": float(_profit_factor(net)),
        "net_compounded_return": float((1.0 + net).prod() - 1.0),
        "net_max_drawdown": float(_max_drawdown(net)),
    }


def summarize_regimes(trades: pd.DataFrame, cost_bps: float) -> list[dict[str, object]]:
    if trades.empty:
        return []
    rows: list[dict[str, object]] = []
    for regime, group in trades.groupby("entry_regime", dropna=False):
        stats = summarize(group, cost_bps)
        stats["entry_regime"] = str(regime)
        rows.append(stats)
    return rows


def _fetch_one(symbol: str, interval: str, start: str, end: str) -> tuple[str, str, pd.DataFrame]:
    frame = fetch_mexc_futures_klines(symbol, interval, start, end)
    return symbol, interval, frame


def run_study(
    *,
    start: str,
    end: str,
    symbols: list[str],
    intervals: list[str],
    output_dir: Path,
    length: int = 8,
    multiplier: int = 3,
    costs_bps: list[float] | None = None,
    max_workers: int = 8,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
) -> dict[str, object]:
    costs = costs_bps or DEFAULT_COSTS_BPS
    output_dir.mkdir(parents=True, exist_ok=True)

    score_start = _as_utc(start)
    score_end = _as_utc(end)
    fetch_start = score_start - pd.Timedelta(days=warmup_days)
    fetch_start_arg = fetch_start.isoformat()

    data: dict[tuple[str, str], pd.DataFrame] = {}
    fetch_errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_one, symbol, interval, fetch_start_arg, end): (symbol, interval)
            for interval in intervals
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol, interval = futures[future]
            try:
                got_symbol, got_interval, frame = future.result()
                data[(got_symbol, got_interval)] = frame
            except Exception as exc:
                fetch_errors.append({"symbol": symbol, "interval": interval, "error": repr(exc)})

    all_trades: list[pd.DataFrame] = []
    summary_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []

    for interval in intervals:
        base_minutes = BASE_MINUTES[interval]
        for symbol in symbols:
            frame = data.get((symbol, interval))
            if frame is None:
                continue
            for variant in VARIANTS:
                open_line, close_line = occ_lines(
                    frame,
                    base_minutes=base_minutes,
                    length=length,
                    multiplier=multiplier,
                    variant=variant,
                )
                trades = build_trades(
                    frame,
                    open_line,
                    close_line,
                    symbol=symbol,
                    interval=interval,
                    variant=variant,
                )
                if not trades.empty:
                    trades = trades[
                        (pd.to_datetime(trades["entry_time"], utc=True) >= score_start)
                        & (pd.to_datetime(trades["exit_time"], utc=True) < score_end)
                    ].copy()
                if not trades.empty:
                    all_trades.append(trades)
                for cost in costs:
                    stats = summarize(trades, float(cost))
                    stats.update({"symbol": symbol, "interval": interval, "variant": variant})
                    summary_rows.append(stats)
                    for row in summarize_regimes(trades, float(cost)):
                        row.update({"symbol": symbol, "interval": interval, "variant": variant})
                        regime_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    regimes = pd.DataFrame(regime_rows)
    trades_all = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()

    paired_rows: list[dict[str, object]] = []
    if not summary.empty:
        for cost in costs:
            sub = summary[summary["round_trip_cost_bps"] == float(cost)]
            for (symbol, interval), group in sub.groupby(["symbol", "interval"]):
                by_variant = group.set_index("variant")
                if "original_lookahead" not in by_variant.index or "confirmed_htf" not in by_variant.index:
                    continue
                original = by_variant.loc["original_lookahead"]
                confirmed = by_variant.loc["confirmed_htf"]
                paired_rows.append(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "round_trip_cost_bps": float(cost),
                        "original_net_expectancy_bps": float(original["net_expectancy_bps"]),
                        "confirmed_net_expectancy_bps": float(confirmed["net_expectancy_bps"]),
                        "lookahead_expectancy_uplift_bps": float(
                            original["net_expectancy_bps"] - confirmed["net_expectancy_bps"]
                        ),
                        "original_profit_factor": float(original["net_profit_factor"]),
                        "confirmed_profit_factor": float(confirmed["net_profit_factor"]),
                        "original_trades": int(original["trades"]),
                        "confirmed_trades": int(confirmed["trades"]),
                    }
                )
    paired = pd.DataFrame(paired_rows)

    summary.to_csv(output_dir / "summary.csv", index=False)
    regimes.to_csv(output_dir / "regime_summary.csv", index=False)
    paired.to_csv(output_dir / "lookahead_impact.csv", index=False)
    if not trades_all.empty:
        trades_all.to_csv(output_dir / "trades.csv", index=False)

    protocol = {
        "study": "OCC Strategy R5.1 external outlier diagnostic",
        "status": "external_outlier_only_not_candidate",
        "candidate_registry_mutated": False,
        "parameter_search_performed": False,
        "engineering_note": "Indicators initialize on prehistory; only the frozen scoring window contributes trades.",
        "frozen_parameters": {
            "ma_type": "SMMA",
            "length": length,
            "alternate_resolution_multiplier": multiplier,
            "direction": "both",
            "stop_loss": "disabled",
            "take_profit": "disabled",
        },
        "variants": {
            "original_lookahead": "historical lookahead_on diagnostic control",
            "confirmed_htf": "causal confirmed higher-timeframe implementation",
            "same_tf": "same-timeframe OCC control",
        },
        "data": {
            "source": "MEXC public futures klines",
            "warmup_start": fetch_start_arg,
            "warmup_days": warmup_days,
            "score_start": score_start.isoformat(),
            "end_exclusive": score_end.isoformat(),
            "symbols": symbols,
            "intervals": intervals,
        },
        "round_trip_cost_bps": costs,
        "fetch_errors": fetch_errors,
    }
    (output_dir / "protocol_and_manifest.json").write_text(
        json.dumps(protocol, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    aggregate: dict[str, object] = {}
    if not summary.empty:
        for cost in costs:
            s = summary[summary["round_trip_cost_bps"] == float(cost)]
            by_cost: dict[str, object] = {}
            for variant in VARIANTS:
                g = s[s["variant"] == variant]
                by_cost[variant] = {
                    "cells": int(len(g)),
                    "total_trades": int(g["trades"].sum()),
                    "median_net_expectancy_bps": float(g["net_expectancy_bps"].median()),
                    "median_profit_factor": float(
                        g["net_profit_factor"].replace([np.inf, -np.inf], np.nan).median()
                    ),
                    "positive_expectancy_cell_fraction": float((g["net_expectancy_bps"] > 0.0).mean()),
                }
            aggregate[str(cost)] = by_cost

    lookahead_impact: dict[str, object] = {}
    for cost in costs:
        group = paired.loc[paired["round_trip_cost_bps"] == float(cost)] if not paired.empty else paired
        lookahead_impact[str(cost)] = {
            "median_expectancy_uplift_bps": float(group["lookahead_expectancy_uplift_bps"].median())
            if not group.empty
            else math.nan
        }

    report = {
        "protocol": protocol,
        "aggregate": aggregate,
        "lookahead_impact": lookahead_impact,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="External OCC Strategy R5.1 outlier diagnostic")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-09-12")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--intervals", nargs="+", default=DEFAULT_INTERVALS)
    parser.add_argument("--output-dir", default="artifacts/occ_r51_outlier")
    parser.add_argument("--length", type=int, default=8)
    parser.add_argument("--multiplier", type=int, default=3)
    parser.add_argument("--costs-bps", nargs="+", type=float, default=DEFAULT_COSTS_BPS)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--warmup-days", type=int, default=DEFAULT_WARMUP_DAYS)
    args = parser.parse_args()
    run_study(
        start=args.start,
        end=args.end,
        symbols=list(args.symbols),
        intervals=list(args.intervals),
        output_dir=Path(args.output_dir),
        length=args.length,
        multiplier=args.multiplier,
        costs_bps=list(args.costs_bps),
        max_workers=args.max_workers,
        warmup_days=args.warmup_days,
    )


if __name__ == "__main__":
    main()
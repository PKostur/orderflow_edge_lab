from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.ena_mean_reversion_risk import RiskExperimentConfig, simulate_overlay
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.strategy_tournament import generate_target_position

UTC = "UTC"


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(UTC) if ts.tzinfo is None else ts.tz_convert(UTC)


def _iso(value: pd.Timestamp) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _retry(call: Callable[[], Any], attempts: int = 3, pause: float = 2.0) -> Any:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            last = exc
            if attempt == attempts:
                raise
            time.sleep(pause * attempt)
    raise RuntimeError("retry exhausted") from last


def _fetch_prices(symbols: list[str], interval: str, start: str, end: str, workers: int) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> tuple[str, pd.DataFrame]:
        frame = _retry(lambda: fetch_mexc_futures_klines(symbol, interval, start, end))
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, frame = future.result()
            out[symbol] = frame
    return out


def _fetch_funding(symbols: list[str], start: str, end: str, workers: int) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> tuple[str, pd.DataFrame]:
        frame = _retry(lambda: fetch_mexc_funding_history(symbol, start, end), attempts=3, pause=3.0)
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, frame = future.result()
            out[symbol] = frame
    return out


def _coverage(frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    return {
        symbol: {
            "rows": int(len(frame)),
            "first": frame.index.min().isoformat() if len(frame) else None,
            "last": frame.index.max().isoformat() if len(frame) else None,
        }
        for symbol, frame in sorted(frames.items())
    }


def _common_index(frames: Mapping[str, pd.DataFrame], symbols: list[str]) -> pd.DatetimeIndex:
    common: pd.DatetimeIndex | None = None
    for symbol in symbols:
        idx = frames[symbol].index
        common = idx if common is None else common.intersection(idx)
    if common is None:
        return pd.DatetimeIndex([], tz=UTC)
    return common.sort_values()


def _funding_between(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    series = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0)
    return float(series[(series.index > start) & (series.index <= end)].sum())


def _stats(returns: pd.Series | list[float]) -> dict[str, Any]:
    arr = np.asarray(list(returns), dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return {
            "observations": 0,
            "mean_return_bps": None,
            "profit_factor": None,
            "positive_fraction": None,
            "compounded_return": None,
            "max_drawdown": None,
        }
    gains = float(arr[arr > 0].sum())
    losses = float(-arr[arr < 0].sum())
    if losses > 0:
        pf: float | str | None = gains / losses
    elif gains > 0:
        pf = "INF"
    else:
        pf = None
    equity = np.cumprod(1.0 + arr)
    peaks = np.maximum.accumulate(equity)
    return {
        "observations": int(len(arr)),
        "mean_return_bps": float(arr.mean() * 10_000.0),
        "profit_factor": pf,
        "positive_fraction": float(np.mean(arr > 0)),
        "compounded_return": float(equity[-1] - 1.0),
        "max_drawdown": float(np.min(equity / peaks - 1.0)),
    }


def _fold_stats(returns: pd.Series, fold_days: int) -> list[dict[str, Any]]:
    if returns.empty:
        return []
    start = returns.index.min().floor("d")
    end = returns.index.max().ceil("d") + pd.Timedelta(days=1)
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        right = cursor + pd.Timedelta(days=int(fold_days))
        subset = returns[(returns.index >= cursor) & (returns.index < right)]
        if len(subset):
            rows.append({
                "start_utc": _iso(cursor),
                "end_exclusive_utc": _iso(right),
                "stats": _stats(subset),
            })
        cursor = right
    return rows


def _portfolio_from_positions(
    prices: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    positions: pd.DataFrame,
    cost_bps: float,
) -> pd.Series:
    symbols = list(positions.columns)
    common = positions.index
    side_cost = float(cost_bps) / 2.0 / 10_000.0
    previous = pd.Series(0.0, index=symbols, dtype=float)
    values: list[float] = []
    times: list[pd.Timestamp] = []
    for i, ts in enumerate(common[:-1]):
        end = common[i + 1]
        raw = positions.loc[ts].fillna(0.0).astype(float)
        gross_abs = float(raw.abs().sum())
        weights = raw / gross_abs if gross_abs > 1.0 else raw
        turnover = float((weights - previous).abs().sum())
        gross = 0.0
        funding_ret = 0.0
        for symbol in symbols:
            w = float(weights[symbol])
            if abs(w) < 1e-15:
                continue
            frame = prices[symbol]
            if ts not in frame.index or end not in frame.index:
                continue
            entry = float(frame.loc[ts, "open"])
            exit_ = float(frame.loc[end, "open"])
            gross += w * (exit_ / entry - 1.0)
            funding_ret += -w * _funding_between(funding.get(symbol, pd.DataFrame()), ts, end)
        net = gross + funding_ret - turnover * side_cost
        values.append(float(net))
        times.append(ts)
        previous = weights
    return pd.Series(values, index=pd.DatetimeIndex(times), dtype=float)


def _lagged_reversal(
    frames: Mapping[str, pd.DataFrame], symbols: list[str], costs: list[float], fold_days: int
) -> list[dict[str, Any]]:
    common = _common_index(frames, symbols)
    closes = pd.DataFrame({s: frames[s].loc[common, "close"].astype(float) for s in symbols}, index=common)
    opens = pd.DataFrame({s: frames[s].loc[common, "open"].astype(float) for s in symbols}, index=common)
    last_bar_sign = np.sign(closes.pct_change()).replace(0.0, np.nan).ffill().fillna(0.0)
    rows: list[dict[str, Any]] = []
    for direction_name, multiplier in (("reversal", -1.0), ("continuation_control", 1.0)):
        position = last_bar_sign.shift(1).fillna(0.0) * multiplier
        raw_portfolio = position.div(position.abs().sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
        gross = raw_portfolio * (opens.shift(-1) / opens - 1.0)
        gross_portfolio = gross.sum(axis=1).iloc[:-1]
        turnover = raw_portfolio.diff().abs().sum(axis=1).fillna(raw_portfolio.abs().sum(axis=1))
        for cost in costs:
            net = (gross_portfolio - turnover.iloc[:-1] * (float(cost) / 2.0 / 10_000.0)).dropna()
            per_symbol = {}
            for symbol in symbols:
                pos = position[symbol]
                sym_gross = pos * (opens[symbol].shift(-1) / opens[symbol] - 1.0)
                sym_turn = pos.diff().abs().fillna(pos.abs())
                sym_net = (sym_gross - sym_turn * (float(cost) / 2.0 / 10_000.0)).iloc[:-1].dropna()
                per_symbol[symbol] = _stats(sym_net)
            rows.append({
                "methodology": "lagged_one_bar_reversal",
                "variant": direction_name,
                "interval": "15m",
                "cost_bps": float(cost),
                "portfolio_stats": _stats(net),
                "folds": _fold_stats(net, fold_days),
                "per_symbol": per_symbol,
                "market_state_claim": "tests short-horizon reversal versus continuation; not a state-conditioned strategy",
            })
    return rows


def _funding_signal_matrix(
    funding: Mapping[str, pd.DataFrame], common: pd.DatetimeIndex, symbols: list[str]
) -> pd.DataFrame:
    panel = pd.DataFrame(index=common, columns=symbols, dtype=float)
    for symbol in symbols:
        if funding[symbol].empty:
            continue
        series = pd.to_numeric(funding[symbol]["funding_rate"], errors="coerce")
        panel[symbol] = series.reindex(common)
    return panel


def _funding_carry(
    prices: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    symbols: list[str],
    costs: list[float],
    n_each_side_values: list[int],
    fold_days: int,
) -> list[dict[str, Any]]:
    common = _common_index(prices, symbols)
    rates = _funding_signal_matrix(funding, common, symbols)
    rows: list[dict[str, Any]] = []
    for n_side in n_each_side_values:
        if n_side * 2 > len(symbols):
            continue
        for variant, reverse in (("carry", False), ("reversed_carry_control", True)):
            positions = pd.DataFrame(0.0, index=common, columns=symbols)
            for i in range(1, len(common)):
                signal_ts = common[i - 1]
                exec_ts = common[i]
                row = rates.loc[signal_ts].dropna().sort_values()
                if len(row) < max(4, 2 * n_side):
                    continue
                negative = list(row.index[:n_side])
                positive = list(row.index[-n_side:])
                if reverse:
                    longs, shorts = positive, negative
                else:
                    longs, shorts = negative, positive
                positions.loc[exec_ts, longs] = 0.5 / len(longs)
                positions.loc[exec_ts, shorts] = -0.5 / len(shorts)
            for cost in costs:
                net = _portfolio_from_positions(prices, funding, positions, cost)
                rows.append({
                    "methodology": "lagged_cross_sectional_funding_carry",
                    "variant": variant,
                    "n_each_side": int(n_side),
                    "interval": "8h",
                    "cost_bps": float(cost),
                    "portfolio_stats": _stats(net),
                    "folds": _fold_stats(net, fold_days),
                    "causality": "realized funding at t is observed, portfolio executes at the next 8h open and earns only later funding cashflows",
                })
    return rows


def _htf_trend_neighborhood(
    prices: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    symbols: list[str],
    variants: list[Mapping[str, Any]],
    costs: list[float],
    fold_days: int,
) -> list[dict[str, Any]]:
    common = _common_index(prices, symbols)
    rows: list[dict[str, Any]] = []
    for params in variants:
        positions = pd.DataFrame(0.0, index=common, columns=symbols)
        for symbol in symbols:
            target = generate_target_position(prices[symbol].loc[common], "ema_tsmom", params)
            positions[symbol] = target.shift(1).reindex(common).fillna(0.0)
        active = positions.abs().sum(axis=1).replace(0.0, np.nan)
        positions = positions.div(active, axis=0).fillna(0.0)
        for cost in costs:
            net = _portfolio_from_positions(prices, funding, positions, cost)
            rows.append({
                "methodology": "ema_tsmom_neighborhood",
                "params": dict(params),
                "interval": "8h",
                "cost_bps": float(cost),
                "portfolio_stats": _stats(net),
                "folds": _fold_stats(net, fold_days),
                "selection_rule": "all predeclared neighbors retained; no best-PF selection",
            })
    return rows


def _cross_sectional_positions(
    prices: Mapping[str, pd.DataFrame],
    symbols: list[str],
    lookback_days: int,
    holding_days: int,
    quantile_fraction: float,
) -> pd.DataFrame:
    common = _common_index(prices, symbols)
    closes = pd.DataFrame({s: prices[s].loc[common, "close"].astype(float) for s in symbols}, index=common)
    positions = pd.DataFrame(0.0, index=common, columns=symbols)
    n_select = max(1, int(math.floor(len(symbols) * quantile_fraction)))
    current = pd.Series(0.0, index=symbols, dtype=float)
    last_rebalance_i: int | None = None
    for i in range(len(common)):
        if i < lookback_days:
            positions.iloc[i] = current
            continue
        if last_rebalance_i is None or i - last_rebalance_i >= holding_days:
            scores = closes.iloc[i - 1] / closes.iloc[i - 1 - lookback_days] - 1.0
            ranked = scores.dropna().sort_values()
            if len(ranked) >= 2 * n_select:
                current = pd.Series(0.0, index=symbols, dtype=float)
                current.loc[list(ranked.index[-n_select:])] = 0.5 / n_select
                current.loc[list(ranked.index[:n_select])] = -0.5 / n_select
                last_rebalance_i = i
        positions.iloc[i] = current
    return positions


def _cross_sectional_neighborhood(
    prices: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    symbols: list[str],
    variants: list[Mapping[str, Any]],
    costs: list[float],
    fold_days: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for params in variants:
        positions = _cross_sectional_positions(
            prices,
            symbols,
            int(params["lookback_days"]),
            int(params["holding_days"]),
            float(params.get("quantile_fraction", 0.25)),
        )
        for cost in costs:
            net = _portfolio_from_positions(prices, funding, positions, cost)
            rows.append({
                "methodology": "cross_sectional_momentum_neighborhood",
                "params": dict(params),
                "interval": "1d",
                "cost_bps": float(cost),
                "portfolio_stats": _stats(net),
                "folds": _fold_stats(net, fold_days),
                "selection_rule": "all predeclared neighbors retained; fixed current liquid panel has survivorship bias",
            })
    return rows


def _ena_stop_neighborhood(
    frame: pd.DataFrame,
    stop_values: list[float],
    costs: list[float],
    fold_days: int,
) -> list[dict[str, Any]]:
    base = RiskExperimentConfig(
        period=40,
        std=2.0,
        rsi_period=14,
        rsi_low=25.0,
        rsi_high=75.0,
        max_hold=20,
        atr_period=14,
        round_trip_cost_bps=20.0,
    )
    rows: list[dict[str, Any]] = []
    for stop in stop_values:
        for cost in costs:
            cfg = replace(base, round_trip_cost_bps=float(cost))
            trades = simulate_overlay(frame, cfg, stop_atr_multiple=float(stop), target_r_multiple=None)
            returns = [float(row["net_return"]) for row in trades]
            if trades:
                by_time = pd.Series(
                    returns,
                    index=pd.DatetimeIndex([pd.Timestamp(row["entry_time"]) for row in trades]),
                    dtype=float,
                )
            else:
                by_time = pd.Series(dtype=float)
            rows.append({
                "methodology": "ena_frozen_signal_stop_neighborhood",
                "signal": {"bb_period": 40, "bb_std": 2.0, "rsi": [25.0, 75.0], "max_hold": 20},
                "stop_atr_multiple": float(stop),
                "cost_bps": float(cost),
                "trade_stats": _stats(returns),
                "folds": _fold_stats(by_time, fold_days),
                "selection_rule": "risk-neighborhood diagnostic only; frozen forward stop remains 1.5 ATR",
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the predeclared retrospective methodology expansion v1.")
    parser.add_argument("--config", default="config/methodology_expansion_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()

    config_path = Path(args.config)
    raw = config_path.read_bytes()
    cfg = json.loads(raw.decode("utf-8"))
    if cfg.get("protocol_name") != "methodology-expansion-v1":
        raise SystemExit("unexpected methodology protocol")
    protocol_sha = sha256(raw).hexdigest()
    symbols = [str(v) for v in cfg["data"]["symbols"]]
    end = str(cfg["data"]["end_exclusive"])

    price_start = str(cfg["data"]["price_only_start"])
    funding_start = str(cfg["data"]["funding_complete_start"])
    ena_start = str(cfg["data"]["ena_start"])

    prices_15m = _fetch_prices(symbols, "15m", price_start, end, int(args.max_workers))
    prices_8h = _fetch_prices(symbols, "8h", funding_start, end, int(args.max_workers))
    prices_1d = _fetch_prices(symbols, "1d", funding_start, end, int(args.max_workers))
    funding = _fetch_funding(symbols, funding_start, end, max(1, min(3, int(args.max_workers))))
    ena_1h = _fetch_prices(["ENA_USDT"], "1h", ena_start, end, 1)["ENA_USDT"]

    funding_first = {
        symbol: (frame.index.min() if len(frame) else None)
        for symbol, frame in funding.items()
    }
    if any(value is None for value in funding_first.values()):
        raise SystemExit("funding-complete methodology lane requires non-empty funding history for every frozen symbol")
    effective_funding_start = max(value for value in funding_first.values() if value is not None)
    declared = _utc(funding_start)
    if effective_funding_start > declared + pd.Timedelta(hours=8):
        raise SystemExit(
            f"declared funding-complete start {declared} is earlier than common observed funding start {effective_funding_start}"
        )

    methods = cfg["methodologies"]
    cells: list[dict[str, Any]] = []
    cells.extend(_lagged_reversal(
        prices_15m,
        symbols,
        [float(v) for v in methods["lagged_reversal"]["cost_bps"]],
        int(methods["lagged_reversal"]["fold_days"]),
    ))
    cells.extend(_funding_carry(
        prices_8h,
        funding,
        symbols,
        [float(v) for v in methods["funding_carry"]["cost_bps"]],
        [int(v) for v in methods["funding_carry"]["n_each_side"]],
        int(methods["funding_carry"]["fold_days"]),
    ))
    cells.extend(_htf_trend_neighborhood(
        prices_8h,
        funding,
        symbols,
        list(methods["htf_trend_neighborhood"]["variants"]),
        [float(v) for v in methods["htf_trend_neighborhood"]["cost_bps"]],
        int(methods["htf_trend_neighborhood"]["fold_days"]),
    ))
    cells.extend(_cross_sectional_neighborhood(
        prices_1d,
        funding,
        symbols,
        list(methods["cross_sectional_neighborhood"]["variants"]),
        [float(v) for v in methods["cross_sectional_neighborhood"]["cost_bps"]],
        int(methods["cross_sectional_neighborhood"]["fold_days"]),
    ))
    cells.extend(_ena_stop_neighborhood(
        ena_1h,
        [float(v) for v in methods["ena_stop_neighborhood"]["stop_atr_multiple"]],
        [float(v) for v in methods["ena_stop_neighborhood"]["cost_bps"]],
        int(methods["ena_stop_neighborhood"]["fold_days"]),
    ))

    payload = {
        "schema_version": 1,
        "protocol_name": cfg["protocol_name"],
        "protocol_sha256": protocol_sha,
        "status": cfg["status"],
        "data": {
            "symbols": symbols,
            "end_exclusive": end,
            "price_15m_coverage": _coverage(prices_15m),
            "price_8h_coverage": _coverage(prices_8h),
            "price_1d_coverage": _coverage(prices_1d),
            "funding_coverage": _coverage(funding),
            "ena_1h_coverage": _coverage({"ENA_USDT": ena_1h}),
            "effective_common_funding_start": _iso(effective_funding_start),
        },
        "trial_count": len(cells),
        "all_predeclared_trials_retained": True,
        "cells": cells,
        "claims": cfg["claims"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "protocol": cfg["protocol_name"],
        "trial_count": len(cells),
        "methodologies": sorted({str(row["methodology"]) for row in cells}),
        "claims": cfg["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

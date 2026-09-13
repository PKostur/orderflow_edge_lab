from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
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
            if attempt >= attempts:
                raise
            time.sleep(pause * attempt)
    raise RuntimeError("retry exhausted") from last


def _fetch_prices(
    symbols: Sequence[str], interval: str, start: str, end: str, workers: int
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> tuple[str, pd.DataFrame]:
        frame = _retry(lambda: fetch_mexc_futures_klines(symbol, interval, start, end))
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, frame = future.result()
            out[symbol] = frame
    return out


def _fetch_funding(
    symbols: Sequence[str], start: str, end: str, workers: int
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> tuple[str, pd.DataFrame]:
        frame = _retry(lambda: fetch_mexc_funding_history(symbol, start, end), attempts=3, pause=3.0)
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, frame = future.result()
            out[symbol] = frame
    return out


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].astype(float).shift(1)
    true_range = pd.concat(
        [
            (frame["high"].astype(float) - frame["low"].astype(float)).abs(),
            (frame["high"].astype(float) - previous_close).abs(),
            (frame["low"].astype(float) - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(int(period), min_periods=int(period)).mean()


def _common_index(frames: Mapping[str, pd.DataFrame], symbols: Sequence[str]) -> pd.DatetimeIndex:
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
    series = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    return float(series[(series.index > start) & (series.index <= end)].sum())


def _pf(returns: Sequence[float]) -> float | str | None:
    gains = sum(float(value) for value in returns if float(value) > 0)
    losses = -sum(float(value) for value in returns if float(value) < 0)
    if losses > 0:
        return float(gains / losses)
    if gains > 0:
        return "INF"
    return None


def _return_stats(returns: Sequence[float]) -> dict[str, Any]:
    arr = np.asarray([float(x) for x in returns if math.isfinite(float(x))], dtype=float)
    if not len(arr):
        return {
            "observations": 0,
            "expectancy_bps": None,
            "profit_factor": None,
            "win_rate": None,
            "compounded_return": None,
            "max_drawdown": None,
        }
    equity = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(equity)
    return {
        "observations": int(len(arr)),
        "expectancy_bps": float(arr.mean() * 10_000.0),
        "profit_factor": _pf(arr.tolist()),
        "win_rate": float(np.mean(arr > 0.0)),
        "compounded_return": float(equity[-1] - 1.0),
        "max_drawdown": float(np.min(equity / peak - 1.0)),
    }


def _trade_stats(trades: Sequence[Mapping[str, Any]], fold_days: int) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in trades]
    base = _return_stats(returns)
    if not trades:
        return {
            **base,
            "setup_count": 0,
            "median_mae_bps": None,
            "median_mfe_bps": None,
            "stop_fraction": None,
            "positive_fold_fraction": None,
            "fold_count": 0,
        }
    mae = np.asarray([float(row.get("mae_bps", np.nan)) for row in trades], dtype=float)
    mfe = np.asarray([float(row.get("mfe_bps", np.nan)) for row in trades], dtype=float)
    stop_fraction = float(np.mean([row.get("exit_reason") == "stop" for row in trades]))

    times = [_utc(row["entry_time"]) for row in trades]
    first = min(times).floor("d")
    last = max(times).ceil("d") + pd.Timedelta(days=1)
    fold_expectancies: list[float] = []
    cursor = first
    while cursor < last:
        right = cursor + pd.Timedelta(days=int(fold_days))
        fold_returns = [
            float(row["net_return"])
            for row in trades
            if cursor <= _utc(row["entry_time"]) < right
        ]
        if fold_returns:
            fold_expectancies.append(float(np.mean(fold_returns)))
        cursor = right
    return {
        **base,
        "setup_count": len(trades),
        "median_mae_bps": float(np.nanmedian(mae)) if np.isfinite(mae).any() else None,
        "median_mfe_bps": float(np.nanmedian(mfe)) if np.isfinite(mfe).any() else None,
        "stop_fraction": stop_fraction,
        "positive_fold_fraction": (
            float(np.mean(np.asarray(fold_expectancies) > 0.0)) if fold_expectancies else None
        ),
        "fold_count": len(fold_expectancies),
    }


def directional_fib_depth(
    frame: pd.DataFrame,
    target: pd.Series,
    *,
    lookback_bars: int,
    minimum_impulse_atr: float,
    atr_period: int = 14,
) -> pd.Series:
    """Causal retracement depth using only bars strictly before each signal bar."""
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    atr = _atr(frame, atr_period).shift(1)
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    sides = target.reindex(frame.index).fillna(0.0).astype(float)

    for i in range(int(lookback_bars), len(frame)):
        side = int(np.sign(float(sides.iloc[i])))
        if side == 0:
            continue
        hist = frame.iloc[i - int(lookback_bars) : i]
        if len(hist) < int(lookback_bars):
            continue

        if side > 0:
            low_pos = int(np.argmin(hist["low"].to_numpy(dtype=float)))
            if low_pos >= len(hist) - 1:
                continue
            after = hist.iloc[low_pos + 1 :]
            swing_low = float(hist["low"].iloc[low_pos])
            swing_high = float(after["high"].max())
        else:
            high_pos = int(np.argmax(hist["high"].to_numpy(dtype=float)))
            if high_pos >= len(hist) - 1:
                continue
            after = hist.iloc[high_pos + 1 :]
            swing_high = float(hist["high"].iloc[high_pos])
            swing_low = float(after["low"].min())

        impulse = swing_high - swing_low
        atr_ref = atr.iloc[i]
        if impulse <= 0 or pd.isna(atr_ref) or float(atr_ref) <= 0:
            continue
        if impulse < float(minimum_impulse_atr) * float(atr_ref):
            continue

        signal_close = float(close.iloc[i])
        depth = (
            (swing_high - signal_close) / impulse
            if side > 0
            else (signal_close - swing_low) / impulse
        )
        if 0.0 <= depth <= 1.0 and math.isfinite(depth):
            out.iloc[i] = float(depth)
    return out


def _eligible(depth: pd.Series, levels: Sequence[float] | None, tolerance: float) -> pd.Series:
    if levels is None:
        return pd.Series(True, index=depth.index, dtype=bool)
    values = depth.to_numpy(dtype=float)
    ok = np.zeros(len(depth), dtype=bool)
    finite = np.isfinite(values)
    for level in levels:
        ok |= finite & (np.abs(values - float(level)) <= float(tolerance))
    return pd.Series(ok, index=depth.index, dtype=bool)


def gate_target_on_entry_transitions(target: pd.Series, eligible: pd.Series) -> pd.Series:
    """Gate only baseline entry/reversal transitions; never manufacture delayed entries."""
    base = target.fillna(0.0).clip(-1.0, 1.0).astype(float)
    gate = eligible.reindex(base.index).fillna(False).astype(bool)
    out = np.zeros(len(base), dtype=float)
    overlay_state = 0
    previous_baseline = 0

    for i in range(len(base)):
        desired = int(np.sign(float(base.iloc[i])))
        transition = desired != previous_baseline
        if overlay_state == 0:
            if desired != 0 and transition and bool(gate.iloc[i]):
                overlay_state = desired
        else:
            if desired == overlay_state:
                pass
            elif desired == 0:
                overlay_state = 0
            else:
                overlay_state = desired if transition and bool(gate.iloc[i]) else 0
        out[i] = float(overlay_state)
        previous_baseline = desired
    return pd.Series(out, index=base.index, dtype=float)


def _simulate_ena(
    frame: pd.DataFrame,
    target: pd.Series,
    *,
    atr_period: int,
    stop_atr_multiple: float,
    round_trip_cost_bps: float,
) -> list[dict[str, Any]]:
    desired = target.shift(1).fillna(0.0).clip(-1.0, 1.0)
    signal_atr = _atr(frame, atr_period).shift(1)
    cost_fraction = float(round_trip_cost_bps) / 10_000.0
    trades: list[dict[str, Any]] = []
    side = 0
    locked_side = 0
    entry_i: int | None = None
    entry_price: float | None = None
    atr_at_entry: float | None = None
    mae = 0.0
    mfe = 0.0

    def close_trade(exit_i: int, exit_price: float, reason: str) -> None:
        nonlocal side, entry_i, entry_price, atr_at_entry, mae, mfe
        if side == 0 or entry_i is None or entry_price is None:
            raise RuntimeError("incomplete ENA trade")
        gross = side * (float(exit_price) / float(entry_price) - 1.0)
        trades.append(
            {
                "entry_time": _iso(frame.index[entry_i]),
                "exit_time": _iso(frame.index[exit_i]),
                "side": "long" if side > 0 else "short",
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "gross_return": float(gross),
                "net_return": float(gross - cost_fraction),
                "exit_reason": reason,
                "mae_bps": float(mae * 10_000.0),
                "mfe_bps": float(mfe * 10_000.0),
            }
        )
        side = 0
        entry_i = None
        entry_price = None
        atr_at_entry = None
        mae = 0.0
        mfe = 0.0

    for i, (_, row) in enumerate(frame.iterrows()):
        requested = int(np.sign(float(desired.iloc[i])))
        if locked_side and requested != locked_side:
            locked_side = 0

        if side and requested != side:
            previous_side = side
            close_trade(i, float(row["open"]), "signal_exit")
            if requested == -previous_side:
                locked_side = 0

        if side == 0 and requested and requested != locked_side:
            candidate_atr = signal_atr.iloc[i]
            if pd.notna(candidate_atr) and float(candidate_atr) > 0:
                side = requested
                entry_i = i
                entry_price = float(row["open"])
                atr_at_entry = float(candidate_atr)
                mae = 0.0
                mfe = 0.0

        if side == 0 or entry_price is None or atr_at_entry is None:
            continue

        if side > 0:
            adverse = float(row["low"]) / entry_price - 1.0
            favorable = float(row["high"]) / entry_price - 1.0
        else:
            adverse = -(float(row["high"]) / entry_price - 1.0)
            favorable = -(float(row["low"]) / entry_price - 1.0)
        mae = min(mae, adverse)
        mfe = max(mfe, favorable)

        risk_distance = atr_at_entry * float(stop_atr_multiple)
        stop_price = entry_price - side * risk_distance
        stop_hit = (
            float(row["low"]) <= stop_price
            if side > 0
            else float(row["high"]) >= stop_price
        )
        if stop_hit:
            exit_side = side
            close_trade(i, float(stop_price), "stop")
            locked_side = exit_side

    if side and entry_price is not None:
        close_trade(len(frame) - 1, float(frame["close"].iloc[-1]), "end_of_data")
    return trades


def _portfolio_returns(
    prices: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    raw_positions: pd.DataFrame,
    cost_bps: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    symbols = list(raw_positions.columns)
    common = raw_positions.index
    previous = pd.Series(0.0, index=symbols, dtype=float)
    side_cost = float(cost_bps) / 2.0 / 10_000.0
    net_values: list[float] = []
    funding_values: list[float] = []
    cost_values: list[float] = []
    times: list[pd.Timestamp] = []

    for i, ts in enumerate(common[:-1]):
        end = common[i + 1]
        raw = raw_positions.loc[ts].fillna(0.0).astype(float)
        gross_abs = float(raw.abs().sum())
        weights = raw / gross_abs if gross_abs > 0 else raw
        turnover = float((weights - previous).abs().sum())
        gross_ret = 0.0
        funding_ret = 0.0
        for symbol in symbols:
            weight = float(weights[symbol])
            if abs(weight) < 1e-15:
                continue
            entry = float(prices[symbol].loc[ts, "open"])
            exit_ = float(prices[symbol].loc[end, "open"])
            gross_ret += weight * (exit_ / entry - 1.0)
            funding_ret += -weight * _funding_between(funding[symbol], ts, end)
        cost_ret = turnover * side_cost
        net_values.append(float(gross_ret + funding_ret - cost_ret))
        funding_values.append(float(funding_ret))
        cost_values.append(float(cost_ret))
        times.append(ts)
        previous = weights

    idx = pd.DatetimeIndex(times)
    return (
        pd.Series(net_values, index=idx, dtype=float),
        pd.Series(funding_values, index=idx, dtype=float),
        pd.Series(cost_values, index=idx, dtype=float),
    )


def _extract_position_trades(
    frame: pd.DataFrame,
    funding: pd.DataFrame,
    executed: pd.Series,
    *,
    round_trip_cost_bps: float,
) -> list[dict[str, Any]]:
    position = executed.reindex(frame.index).fillna(0.0).clip(-1.0, 1.0)
    trades: list[dict[str, Any]] = []
    i = 0
    cost = float(round_trip_cost_bps) / 10_000.0
    while i < len(frame) - 1:
        side = int(np.sign(float(position.iloc[i])))
        if side == 0:
            i += 1
            continue
        start = i
        j = i + 1
        while j < len(frame) and int(np.sign(float(position.iloc[j]))) == side:
            j += 1
        exit_i = min(j, len(frame) - 1)
        entry_price = float(frame["open"].iloc[start])
        exit_price = float(frame["open"].iloc[exit_i]) if j < len(frame) else float(frame["close"].iloc[-1])
        path_end = max(start + 1, exit_i)
        path = frame.iloc[start:path_end]
        if side > 0:
            adverse = float(path["low"].min()) / entry_price - 1.0
            favorable = float(path["high"].max()) / entry_price - 1.0
        else:
            adverse = -(float(path["high"].max()) / entry_price - 1.0)
            favorable = -(float(path["low"].min()) / entry_price - 1.0)
        entry_ts = frame.index[start]
        exit_ts = frame.index[exit_i]
        gross = side * (exit_price / entry_price - 1.0)
        funding_ret = -side * _funding_between(funding, entry_ts, exit_ts)
        trades.append(
            {
                "entry_time": _iso(entry_ts),
                "exit_time": _iso(exit_ts),
                "side": "long" if side > 0 else "short",
                "gross_return": float(gross),
                "funding_return": float(funding_ret),
                "net_return": float(gross + funding_ret - cost),
                "exit_reason": "signal_exit" if j < len(frame) else "end_of_data",
                "mae_bps": float(adverse * 10_000.0),
                "mfe_bps": float(favorable * 10_000.0),
            }
        )
        i = max(j, i + 1)
    return trades


def _numeric_pf(value: Any) -> float | None:
    if value == "INF":
        return math.inf
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else parsed


def _comparison(overlay: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    base_n = int(baseline.get("setup_count", 0) or 0)
    over_n = int(overlay.get("setup_count", 0) or 0)
    base_exp = baseline.get("expectancy_bps")
    over_exp = overlay.get("expectancy_bps")
    base_pf = _numeric_pf(baseline.get("profit_factor"))
    over_pf = _numeric_pf(overlay.get("profit_factor"))
    return {
        "retained_setup_fraction": float(over_n / base_n) if base_n else None,
        "delta_expectancy_bps": (
            float(over_exp) - float(base_exp)
            if over_exp is not None and base_exp is not None
            else None
        ),
        "delta_profit_factor": (
            float(over_pf - base_pf)
            if over_pf is not None
            and base_pf is not None
            and math.isfinite(over_pf)
            and math.isfinite(base_pf)
            else None
        ),
        "delta_median_mae_bps": (
            float(overlay["median_mae_bps"]) - float(baseline["median_mae_bps"])
            if overlay.get("median_mae_bps") is not None and baseline.get("median_mae_bps") is not None
            else None
        ),
        "delta_median_mfe_bps": (
            float(overlay["median_mfe_bps"]) - float(baseline["median_mfe_bps"])
            if overlay.get("median_mfe_bps") is not None and baseline.get("median_mfe_bps") is not None
            else None
        ),
    }


def run(config: Mapping[str, Any], max_workers: int) -> dict[str, Any]:
    fib_cfg = config["fibonacci_definition"]
    overlays = fib_cfg["overlays"]
    lookback = int(fib_cfg["anchor_lookback_bars"])
    min_impulse_atr = float(fib_cfg["minimum_impulse_atr"])
    tolerance = float(fib_cfg["level_tolerance"])
    end = str(config["data"]["end_exclusive"])

    cells: list[dict[str, Any]] = []

    # ENA frozen mean-reversion candidate.
    ena_cfg = config["ena_mean_reversion"]
    ena_frame = _fetch_prices(
        ["ENA_USDT"],
        str(ena_cfg["interval"]),
        str(config["data"]["ena_start"]),
        end,
        max_workers,
    )["ENA_USDT"]
    ena_target = generate_target_position(ena_frame, str(ena_cfg["signal_family"]), ena_cfg["parameters"])
    ena_depth = directional_fib_depth(
        ena_frame,
        ena_target,
        lookback_bars=lookback,
        minimum_impulse_atr=min_impulse_atr,
        atr_period=int(ena_cfg["atr_period"]),
    )
    ena_targets: dict[str, pd.Series] = {}
    for name, spec in overlays.items():
        if name == "baseline":
            ena_targets[name] = ena_target.copy()
        else:
            gate = _eligible(ena_depth, spec["levels"], tolerance)
            ena_targets[name] = gate_target_on_entry_transitions(ena_target, gate)

    for cost in ena_cfg["round_trip_cost_bps"]:
        stats_by_overlay: dict[str, dict[str, Any]] = {}
        for name, gated in ena_targets.items():
            trades = _simulate_ena(
                ena_frame,
                gated,
                atr_period=int(ena_cfg["atr_period"]),
                stop_atr_multiple=float(ena_cfg["hard_stop_atr_multiple"]),
                round_trip_cost_bps=float(cost),
            )
            stats_by_overlay[name] = _trade_stats(trades, int(ena_cfg["fold_days"]))
        baseline = stats_by_overlay["baseline"]
        for name, stats in stats_by_overlay.items():
            cells.append(
                {
                    "strategy": "ena_mean_reversion",
                    "overlay": name,
                    "cost_bps": float(cost),
                    "setup_stats": stats,
                    "comparison_to_baseline": _comparison(stats, baseline),
                    "fib_depth_valid_signal_fraction": float(ena_depth.notna().sum() / max(1, (ena_target != 0).sum())),
                }
            )

    # Frozen HTF trend candidate, funding-aware from the legitimate common funding boundary.
    htf_cfg = config["htf_trend"]
    symbols = list(config["data"]["htf_symbols"])
    htf_start = str(config["data"]["htf_funding_complete_start"])
    htf_prices = _fetch_prices(symbols, str(htf_cfg["interval"]), htf_start, end, max_workers)
    htf_funding = _fetch_funding(symbols, htf_start, end, max_workers)
    declared_start = _utc(htf_start)
    for symbol in symbols:
        funding_frame = htf_funding[symbol]
        if funding_frame.empty:
            raise RuntimeError(f"no observed funding for {symbol}")
        first = funding_frame.index.min()
        if first > declared_start:
            raise RuntimeError(
                f"funding coverage for {symbol} begins {first.isoformat()}, after declared start {declared_start.isoformat()}"
            )

    common = _common_index(htf_prices, symbols)
    if len(common) < 200:
        raise RuntimeError("insufficient common HTF price history")
    raw_by_overlay: dict[str, pd.DataFrame] = {
        name: pd.DataFrame(0.0, index=common, columns=symbols) for name in overlays
    }
    htf_valid_depths = 0
    htf_nonzero_signals = 0

    for symbol in symbols:
        frame = htf_prices[symbol].loc[common]
        target = generate_target_position(frame, str(htf_cfg["signal_family"]), htf_cfg["parameters"])
        depth = directional_fib_depth(
            frame,
            target,
            lookback_bars=lookback,
            minimum_impulse_atr=min_impulse_atr,
            atr_period=int(htf_cfg["parameters"]["atr_period"]),
        )
        htf_valid_depths += int(depth.notna().sum())
        htf_nonzero_signals += int((target != 0).sum())
        for name, spec in overlays.items():
            gated = target if name == "baseline" else gate_target_on_entry_transitions(
                target, _eligible(depth, spec["levels"], tolerance)
            )
            raw_by_overlay[name][symbol] = gated.shift(1).reindex(common).fillna(0.0)

    for cost in htf_cfg["round_trip_cost_bps"]:
        htf_stats: dict[str, dict[str, Any]] = {}
        htf_portfolio: dict[str, dict[str, Any]] = {}
        for name, raw_positions in raw_by_overlay.items():
            all_trades: list[dict[str, Any]] = []
            for symbol in symbols:
                all_trades.extend(
                    _extract_position_trades(
                        htf_prices[symbol].loc[common],
                        htf_funding[symbol],
                        raw_positions[symbol],
                        round_trip_cost_bps=float(cost),
                    )
                )
            setup_stats = _trade_stats(all_trades, int(htf_cfg["fold_days"]))
            net, funding_ret, transaction_cost = _portfolio_returns(
                {symbol: htf_prices[symbol].loc[common] for symbol in symbols},
                htf_funding,
                raw_positions,
                float(cost),
            )
            portfolio_stats = _return_stats(net.tolist())
            portfolio_stats.update(
                {
                    "funding_contribution": float(funding_ret.sum()),
                    "transaction_cost_drag": float(transaction_cost.sum()),
                    "active_bar_fraction": float((raw_positions.abs().sum(axis=1) > 0).mean()),
                }
            )
            htf_stats[name] = setup_stats
            htf_portfolio[name] = portfolio_stats

        baseline = htf_stats["baseline"]
        base_port = htf_portfolio["baseline"]
        for name in overlays:
            port = htf_portfolio[name]
            cells.append(
                {
                    "strategy": "htf_trend",
                    "overlay": name,
                    "cost_bps": float(cost),
                    "setup_stats": htf_stats[name],
                    "comparison_to_baseline": _comparison(htf_stats[name], baseline),
                    "portfolio_stats": port,
                    "portfolio_delta_to_baseline": {
                        "delta_compounded_return": (
                            float(port["compounded_return"]) - float(base_port["compounded_return"])
                            if port.get("compounded_return") is not None and base_port.get("compounded_return") is not None
                            else None
                        ),
                        "delta_max_drawdown": (
                            float(port["max_drawdown"]) - float(base_port["max_drawdown"])
                            if port.get("max_drawdown") is not None and base_port.get("max_drawdown") is not None
                            else None
                        ),
                    },
                    "fib_depth_valid_signal_fraction": float(htf_valid_depths / max(1, htf_nonzero_signals)),
                }
            )

    # Direct Fib-vs-matched-control diagnostics at each like-for-like cost cell.
    fib_specific: list[dict[str, Any]] = []
    for strategy in ("ena_mean_reversion", "htf_trend"):
        for cost in sorted({float(row["cost_bps"]) for row in cells if row["strategy"] == strategy}):
            by_name = {
                row["overlay"]: row
                for row in cells
                if row["strategy"] == strategy and float(row["cost_bps"]) == cost
            }
            core = by_name["fib_core"]["setup_stats"]
            control = by_name["nonfib_matched_control"]["setup_stats"]
            fib_specific.append(
                {
                    "strategy": strategy,
                    "cost_bps": cost,
                    "core_fib_minus_nonfib_expectancy_bps": (
                        float(core["expectancy_bps"]) - float(control["expectancy_bps"])
                        if core.get("expectancy_bps") is not None and control.get("expectancy_bps") is not None
                        else None
                    ),
                    "core_fib_setup_count": int(core.get("setup_count", 0) or 0),
                    "nonfib_control_setup_count": int(control.get("setup_count", 0) or 0),
                    "interpretation_rule": "A positive value is only retrospective evidence that the predeclared Fib-core proximity outperformed this matched depth control; it is not OOS proof and does not authorize retuning or promotion."
                }
            )

    return {
        "schema_version": 1,
        "protocol_name": config["protocol_name"],
        "status": config["status"],
        "data_end_exclusive": end,
        "fibonacci_definition": fib_cfg,
        "cells": cells,
        "trial_count": len(cells),
        "fib_specific_diagnostics": fib_specific,
        "cross_sectional_candidate": config["cross_sectional_candidate"],
        "all_predeclared_overlays_and_cost_cells_retained": len(cells) == 24,
        "analysis_rules": config["analysis_rules"],
        "claims": config["claims"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run predeclared Fibonacci setup-quality retrospective tests")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = run(config, max_workers=max(1, int(args.max_workers)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "protocol": report["protocol_name"],
        "trial_count": report["trial_count"],
        "fib_specific_diagnostics": report["fib_specific_diagnostics"],
    }, indent=2))


if __name__ == "__main__":
    main()

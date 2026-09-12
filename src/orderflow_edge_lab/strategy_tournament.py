from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import itertools
import json
import math
import time
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


BINANCE_USDM_KLINES = "https://fapi.binance.com/fapi/v1/klines"


class StrategyTournamentError(ValueError):
    pass


@dataclass(frozen=True)
class TournamentConfig:
    source: str = "binance_usdm_public"
    start: str = "2026-03-01"
    end: str = "2026-09-11"
    fold_days: int = 21
    min_folds: int = 4
    round_trip_cost_bps: tuple[float, ...] = (12.0, 16.0, 20.0)
    request_pause_seconds: float = 0.06


def _to_ms(value: str | pd.Timestamp) -> int:
    ts = pd.Timestamp(value, tz="UTC") if not isinstance(value, pd.Timestamp) else value.tz_convert("UTC")
    return int(ts.timestamp() * 1000)


def fetch_binance_usdm_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    *,
    base_url: str = BINANCE_USDM_KLINES,
    request_pause_seconds: float = 0.06,
) -> pd.DataFrame:
    if interval not in {"5m", "15m", "1h"}:
        raise StrategyTournamentError(f"unsupported interval: {interval}")
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    if end_ms <= start_ms:
        raise StrategyTournamentError("end must be after start")
    cursor = start_ms
    rows: list[list[Any]] = []
    last_open = -1
    while cursor < end_ms:
        params = urlencode(
            {"symbol": symbol.upper(), "interval": interval, "startTime": cursor, "endTime": end_ms - 1, "limit": 1500}
        )
        req = Request(f"{base_url}?{params}", headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
        with urlopen(req, timeout=20.0) as response:
            if response.status != 200:
                raise StrategyTournamentError(f"historical source HTTP {response.status} for {symbol}")
            raw = response.read(16_000_000)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list):
            raise StrategyTournamentError(f"historical source returned non-list for {symbol}: {payload}")
        if not payload:
            break
        for row in payload:
            if not isinstance(row, list) or len(row) < 7:
                continue
            open_ms = int(row[0])
            if open_ms <= last_open:
                continue
            rows.append(row)
            last_open = open_ms
        next_cursor = int(payload[-1][0]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
        if len(payload) < 1500:
            break
    if not rows:
        raise StrategyTournamentError(f"no historical candles for {symbol} {interval}")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([int(row[0]) for row in rows], unit="ms", utc=True),
            "open": [float(row[1]) for row in rows],
            "high": [float(row[2]) for row in rows],
            "low": [float(row[3]) for row in rows],
            "close": [float(row[4]) for row in rows],
            "volume": [float(row[5]) for row in rows],
        }
    ).drop_duplicates("timestamp").sort_values("timestamp")
    frame = frame[(frame["timestamp"] >= pd.Timestamp(start, tz="UTC")) & (frame["timestamp"] < pd.Timestamp(end, tz="UTC"))]
    frame = frame.set_index("timestamp")
    if len(frame) < 200:
        raise StrategyTournamentError(f"insufficient historical candles for {symbol} {interval}: {len(frame)}")
    return frame


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False, min_periods=int(span)).mean()


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.fillna(50.0)


def _bollinger(close: pd.Series, period: int, std_mult: float) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(int(period), min_periods=int(period)).mean()
    std = close.rolling(int(period), min_periods=int(period)).std(ddof=0)
    upper = mid + float(std_mult) * std
    lower = mid - float(std_mult) * std
    bandwidth = (upper - lower) / mid.replace(0.0, np.nan)
    return mid, upper, lower, bandwidth


def _stateful_events(
    long_entry: pd.Series,
    short_entry: pd.Series,
    long_exit: pd.Series,
    short_exit: pd.Series,
    max_hold_bars: int | None = None,
) -> pd.Series:
    out = np.zeros(len(long_entry), dtype=float)
    state = 0
    held = 0
    le = long_entry.fillna(False).to_numpy(dtype=bool)
    se = short_entry.fillna(False).to_numpy(dtype=bool)
    lx = long_exit.fillna(False).to_numpy(dtype=bool)
    sx = short_exit.fillna(False).to_numpy(dtype=bool)
    for i in range(len(out)):
        if state == 0:
            if le[i] and not se[i]:
                state, held = 1, 0
            elif se[i] and not le[i]:
                state, held = -1, 0
        elif state == 1:
            held += 1
            if se[i]:
                state, held = -1, 0
            elif lx[i] or (max_hold_bars is not None and held >= max_hold_bars):
                state, held = 0, 0
        else:
            held += 1
            if le[i]:
                state, held = 1, 0
            elif sx[i] or (max_hold_bars is not None and held >= max_hold_bars):
                state, held = 0, 0
        out[i] = state
    return pd.Series(out, index=long_entry.index, dtype=float)


def generate_target_position(frame: pd.DataFrame, family: str, params: Mapping[str, Any]) -> pd.Series:
    close = frame["close"].astype(float)
    family = str(family)
    if family == "donchian_breakout":
        lookback = int(params["lookback"])
        high = frame["high"].rolling(lookback, min_periods=lookback).max().shift(1)
        low = frame["low"].rolling(lookback, min_periods=lookback).min().shift(1)
        event = pd.Series(np.where(close > high, 1.0, np.where(close < low, -1.0, np.nan)), index=frame.index)
        return event.ffill().fillna(0.0)
    if family == "ema_tsmom":
        fast = _ema(close, int(params["fast"]))
        slow = _ema(close, int(params["slow"]))
        atr = _atr(frame, int(params.get("atr_period", 14)))
        normalized = (fast - slow) / atr.replace(0.0, np.nan)
        threshold = float(params.get("min_atr_spread", 0.0))
        return pd.Series(np.where(normalized > threshold, 1.0, np.where(normalized < -threshold, -1.0, 0.0)), index=frame.index)
    if family == "bb_mean_reversion":
        period = int(params["period"])
        std_mult = float(params["std"])
        mid, upper, lower, _ = _bollinger(close, period, std_mult)
        rsi = _rsi(close, int(params.get("rsi_period", 14)))
        long_entry = (close < lower) & (rsi < float(params["rsi_low"]))
        short_entry = (close > upper) & (rsi > float(params["rsi_high"]))
        return _stateful_events(long_entry, short_entry, close >= mid, close <= mid, int(params.get("max_hold", period)))
    if family == "bb_squeeze_breakout":
        period = int(params["period"])
        mid, upper, lower, bandwidth = _bollinger(close, period, float(params["std"]))
        q_window = int(params.get("q_window", period * 10))
        q = bandwidth.rolling(q_window, min_periods=q_window).quantile(float(params["squeeze_q"]))
        squeezed = bandwidth.shift(1) <= q.shift(1)
        long_entry = squeezed & (close > upper)
        short_entry = squeezed & (close < lower)
        return _stateful_events(long_entry, short_entry, close < mid, close > mid, int(params.get("max_hold", period * 2)))
    if family == "intraday_reversal":
        lookback = int(params["lookback"])
        ret = close.pct_change(lookback)
        vol = close.pct_change().rolling(int(params.get("vol_window", max(lookback * 4, 20))), min_periods=10).std()
        z = ret / (vol * math.sqrt(max(lookback, 1))).replace(0.0, np.nan)
        threshold = float(params["z"])
        long_entry = z < -threshold
        short_entry = z > threshold
        return _stateful_events(long_entry, short_entry, z >= -0.15, z <= 0.15, int(params["max_hold"]))
    if family == "trend_pullback":
        fast = _ema(close, int(params["fast"]))
        slow = _ema(close, int(params["slow"]))
        rsi = _rsi(close, int(params.get("rsi_period", 14)))
        long_entry = (fast > slow) & (close < fast) & (close > slow) & (rsi < float(params["long_rsi_max"]))
        short_entry = (fast < slow) & (close > fast) & (close < slow) & (rsi > float(params["short_rsi_min"]))
        return _stateful_events(long_entry, short_entry, fast <= slow, fast >= slow, int(params["max_hold"]))
    if family == "vol_scaled_momentum":
        lookback = int(params["lookback"])
        ret = close.pct_change(lookback)
        vol = close.pct_change().rolling(int(params["vol_window"]), min_periods=int(params["vol_window"])).std() * math.sqrt(lookback)
        score = ret / vol.replace(0.0, np.nan)
        threshold = float(params["threshold"])
        return pd.Series(np.where(score > threshold, 1.0, np.where(score < -threshold, -1.0, 0.0)), index=frame.index)
    raise StrategyTournamentError(f"unknown strategy family: {family}")


def _trade_returns(frame: pd.DataFrame, executed_position: pd.Series, round_trip_cost_bps: float) -> list[float]:
    opens = frame["open"].astype(float)
    future = opens.shift(-1)
    gross_bar = executed_position * (future / opens - 1.0)
    pos = executed_position.fillna(0.0).to_numpy()
    gross = gross_bar.fillna(0.0).to_numpy()
    trades: list[float] = []
    i = 0
    n = len(pos)
    rt_cost = float(round_trip_cost_bps) / 10_000.0
    while i < n - 1:
        if pos[i] == 0:
            i += 1
            continue
        side = pos[i]
        j = i
        compounded = 1.0
        while j < n - 1 and pos[j] == side:
            compounded *= 1.0 + gross[j]
            j += 1
        trades.append((compounded - 1.0) - rt_cost)
        i = j
    return trades


def backtest(frame: pd.DataFrame, family: str, params: Mapping[str, Any], round_trip_cost_bps: float) -> dict[str, Any]:
    if len(frame) < 100:
        return {"trades": 0, "profit_factor": None, "expectancy_bps": None, "total_return": None, "max_drawdown": None, "sharpe": None, "win_rate": None}
    target = generate_target_position(frame, family, params).reindex(frame.index).fillna(0.0).clip(-1.0, 1.0)
    position = target.shift(1).fillna(0.0)
    opens = frame["open"].astype(float)
    open_return = opens.shift(-1) / opens - 1.0
    gross = position * open_return
    turnover = (position - position.shift(1).fillna(0.0)).abs()
    side_cost = float(round_trip_cost_bps) / 2.0 / 10_000.0
    net = (gross - turnover * side_cost).fillna(0.0)
    equity = (1.0 + net).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    trades = _trade_returns(frame, position, round_trip_cost_bps)
    gains = sum(value for value in trades if value > 0)
    losses = -sum(value for value in trades if value < 0)
    if losses > 0:
        pf: float | str | None = gains / losses
    elif gains > 0:
        pf = "INF"
    else:
        pf = None
    mean_bar = float(net.mean())
    std_bar = float(net.std(ddof=0))
    bars_per_year = _bars_per_year(frame.index)
    sharpe = mean_bar / std_bar * math.sqrt(bars_per_year) if std_bar > 0 else None
    return {
        "trades": len(trades),
        "profit_factor": pf,
        "expectancy_bps": (sum(trades) / len(trades) * 10_000.0) if trades else None,
        "total_return": float(equity.iloc[-2] - 1.0) if len(equity) > 1 else 0.0,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "sharpe": float(sharpe) if sharpe is not None and math.isfinite(sharpe) else None,
        "win_rate": (sum(value > 0 for value in trades) / len(trades)) if trades else None,
        "exposure_fraction": float((position != 0).mean()),
    }


def _bars_per_year(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 365.0
    seconds = float(np.median(np.diff(index.view("int64"))) / 1e9)
    if seconds <= 0:
        return 365.0
    return 365.25 * 24.0 * 3600.0 / seconds


def _parameter_variants(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    if not keys:
        return [{}]
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[key] for key in keys))]


def _fold_ranges(index: pd.DatetimeIndex, fold_days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if len(index) == 0:
        return []
    start = index.min().normalize()
    end = index.max()
    ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cursor = start
    delta = pd.Timedelta(days=int(fold_days))
    while cursor < end:
        nxt = cursor + delta
        ranges.append((cursor, nxt))
        cursor = nxt
    return ranges


def _finite_pf(value: Any) -> float | None:
    if value == "INF":
        return 999.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def evaluate_variant_across_symbols(
    frames: Mapping[str, pd.DataFrame],
    family: str,
    params: Mapping[str, Any],
    *,
    fold_days: int,
    round_trip_cost_bps: float,
) -> dict[str, Any]:
    fold_rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        full = backtest(frame, family, params, round_trip_cost_bps)
        symbol_rows.append({"symbol": symbol, **full})
        for fold_start, fold_end in _fold_ranges(frame.index, fold_days):
            window = frame[(frame.index >= fold_start) & (frame.index < fold_end)]
            if len(window) < 100:
                continue
            metrics = backtest(window, family, params, round_trip_cost_bps)
            fold_rows.append(
                {
                    "symbol": symbol,
                    "fold_start": fold_start.isoformat(),
                    "fold_end": fold_end.isoformat(),
                    **metrics,
                }
            )
    usable = [row for row in fold_rows if int(row.get("trades") or 0) > 0 and row.get("expectancy_bps") is not None]
    clusters: list[dict[str, Any]] = []
    cluster_keys = sorted({(str(row["fold_start"]), str(row["fold_end"])) for row in usable})
    for fold_start, fold_end in cluster_keys:
        members = [row for row in usable if row["fold_start"] == fold_start and row["fold_end"] == fold_end]
        expectations = [float(row["expectancy_bps"]) for row in members]
        member_pfs = [_finite_pf(row.get("profit_factor")) for row in members]
        member_pfs = [value for value in member_pfs if value is not None]
        member_sharpes = [float(row["sharpe"]) for row in members if row.get("sharpe") is not None]
        clusters.append(
            {
                "fold_start": fold_start,
                "fold_end": fold_end,
                "symbols": len(members),
                "trades": sum(int(row.get("trades") or 0) for row in members),
                "median_symbol_expectancy_bps": float(np.median(expectations)) if expectations else None,
                "mean_symbol_expectancy_bps": float(np.mean(expectations)) if expectations else None,
                "median_symbol_profit_factor": float(np.median(member_pfs)) if member_pfs else None,
                "median_symbol_sharpe": float(np.median(member_sharpes)) if member_sharpes else None,
                "positive_symbol_fraction": sum(float(row["expectancy_bps"]) > 0 for row in members) / len(members) if members else None,
            }
        )
    positive = [row for row in clusters if row.get("median_symbol_expectancy_bps") is not None and float(row["median_symbol_expectancy_bps"]) > 0]
    pfs = [float(row["median_symbol_profit_factor"]) for row in clusters if row.get("median_symbol_profit_factor") is not None]
    expectancies = [float(row["median_symbol_expectancy_bps"]) for row in clusters if row.get("median_symbol_expectancy_bps") is not None]
    sharpes = [float(row["median_symbol_sharpe"]) for row in clusters if row.get("median_symbol_sharpe") is not None]
    total_trades = sum(int(row.get("trades") or 0) for row in usable)
    return {
        "family": family,
        "parameters": dict(params),
        "round_trip_cost_bps": float(round_trip_cost_bps),
        "dependence_cluster": "calendar time fold aggregated across symbols",
        "fold_observations": len(clusters),
        "positive_fold_fraction": (len(positive) / len(clusters)) if clusters else None,
        "median_fold_expectancy_bps": float(np.median(expectancies)) if expectancies else None,
        "mean_fold_expectancy_bps": float(np.mean(expectancies)) if expectancies else None,
        "median_fold_profit_factor": float(np.median(pfs)) if pfs else None,
        "median_fold_sharpe": float(np.median(sharpes)) if sharpes else None,
        "total_trades_across_folds": total_trades,
        "per_symbol": symbol_rows,
        "per_symbol_fold": fold_rows,
        "per_time_fold_cluster": clusters,
    }


def run_family_tournament(
    frames: Mapping[str, pd.DataFrame],
    family: str,
    parameter_grid: Mapping[str, Sequence[Any]],
    config: TournamentConfig,
) -> dict[str, Any]:
    variants = _parameter_variants(parameter_grid)
    rows: list[dict[str, Any]] = []
    for params in variants:
        for cost in config.round_trip_cost_bps:
            rows.append(
                evaluate_variant_across_symbols(
                    frames,
                    family,
                    params,
                    fold_days=config.fold_days,
                    round_trip_cost_bps=cost,
                )
            )
    return {
        "schema_version": 1,
        "experiment": "strategy_tournament_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "family": family,
        "source": config.source,
        "period": {"start": config.start, "end": config.end},
        "fold_days": config.fold_days,
        "strategy_pnl_used_for_universe_selection": False,
        "trial_count": len(rows),
        "results": rows,
        "claims": {
            "development_only": True,
            "walk_forward_like_folds_are_not_final_untouched_oos": True,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }


def rank_results(reports: Iterable[Mapping[str, Any]], *, minimum_trades: int = 80, minimum_folds: int = 6) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for report in reports:
        for item in report.get("results", []):
            if not isinstance(item, Mapping):
                continue
            row = dict(item)
            row["interval"] = report.get("interval")
            row["source_report_family"] = report.get("family")
            trades = int(row.get("total_trades_across_folds") or 0)
            folds = int(row.get("fold_observations") or 0)
            exp = row.get("median_fold_expectancy_bps")
            pf = row.get("median_fold_profit_factor")
            pos = row.get("positive_fold_fraction")
            eligible = (
                trades >= minimum_trades
                and folds >= minimum_folds
                and exp is not None
                and float(exp) > 0
                and pf is not None
                and float(pf) > 1.0
                and pos is not None
                and float(pos) >= 0.60
            )
            row["screening_eligible"] = bool(eligible)
            row["screening_fail_reasons"] = [
                reason
                for condition, reason in (
                    (trades < minimum_trades, f"trades {trades}/{minimum_trades}"),
                    (folds < minimum_folds, f"folds {folds}/{minimum_folds}"),
                    (exp is None or float(exp) <= 0, f"median_expectancy_bps {exp}"),
                    (pf is None or float(pf) <= 1.0, f"median_pf {pf}"),
                    (pos is None or float(pos) < 0.60, f"positive_fold_fraction {pos}"),
                )
                if condition
            ]
            rows.append(row)
    def key(row: Mapping[str, Any]) -> tuple[float, float, float, int]:
        return (
            1.0 if row.get("screening_eligible") else 0.0,
            float(row.get("median_fold_profit_factor") or -999),
            float(row.get("median_fold_expectancy_bps") or -999),
            int(row.get("total_trades_across_folds") or 0),
        )
    rows.sort(key=key, reverse=True)
    return {
        "schema_version": 1,
        "experiment": "strategy_tournament_v1_leaderboard",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "screening_gate": {
            "minimum_trades": minimum_trades,
            "minimum_fold_observations": minimum_folds,
            "positive_median_expectancy_after_cost": True,
            "median_profit_factor_gt": 1.0,
            "minimum_positive_fold_fraction": 0.60,
        },
        "eligible_count": sum(bool(row.get("screening_eligible")) for row in rows),
        "leaderboard": rows,
        "claims": {
            "screening_only_not_candidate_promotion": True,
            "final_untouched_oos_required": True,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

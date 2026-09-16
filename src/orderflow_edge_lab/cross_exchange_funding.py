from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


class CrossExchangeFundingError(ValueError):
    pass


@dataclass(frozen=True)
class FundingDispersionSpec:
    funding_lookback_days: int = 7
    minimum_history_days: int = 5
    break_even_projection_days: int = 7
    safety_multiple_over_cost: float = 1.25
    gross_exposure: float = 1.0
    round_trip_pair_cost_bps: float = 30.0


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _get_json(url: str, timeout: float = 30.0) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise CrossExchangeFundingError(f"public REST returned HTTP {response.status}: {url}")
        raw = response.read(16_000_000)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CrossExchangeFundingError(f"invalid JSON from public REST: {url}") from exc


def _binance_symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "")


def fetch_binance_futures_klines(
    symbol: str,
    start: str,
    end: str,
    *,
    interval: str = "1d",
    request_pause_seconds: float = 0.10,
) -> pd.DataFrame:
    if interval != "1d":
        raise CrossExchangeFundingError("cross-exchange funding v1 supports Binance 1d klines only")
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    if end_ms <= start_ms:
        raise CrossExchangeFundingError("end must be after start")
    rows: dict[int, list[Any]] = {}
    cursor = start_ms
    while cursor < end_ms:
        query = urlencode({
            "symbol": _binance_symbol(symbol),
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms - 1,
            "limit": 1000,
        })
        payload = _get_json(f"https://fapi.binance.com/fapi/v1/klines?{query}")
        if not isinstance(payload, list):
            raise CrossExchangeFundingError(f"Binance kline payload is not a list for {symbol}")
        if not payload:
            break
        last_open = cursor
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                open_ms = int(row[0])
                o, h, l, c, v = (float(row[i]) for i in range(1, 6))
            except (TypeError, ValueError, IndexError):
                continue
            if start_ms <= open_ms < end_ms and min(o, h, l, c) > 0 and all(math.isfinite(x) for x in (o, h, l, c, v)):
                rows[open_ms] = row
                last_open = max(last_open, open_ms)
        next_cursor = last_open + 24 * 60 * 60 * 1000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
    if not rows:
        raise CrossExchangeFundingError(f"no Binance futures klines for {_binance_symbol(symbol)}")
    ordered = [rows[key] for key in sorted(rows)]
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([int(r[0]) for r in ordered], unit="ms", utc=True),
        "open": [float(r[1]) for r in ordered],
        "high": [float(r[2]) for r in ordered],
        "low": [float(r[3]) for r in ordered],
        "close": [float(r[4]) for r in ordered],
        "volume": [float(r[5]) for r in ordered],
    }).set_index("timestamp").sort_index()
    if len(frame) < 20:
        raise CrossExchangeFundingError(f"insufficient Binance futures candles for {symbol}: {len(frame)}")
    return frame


def fetch_binance_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    request_pause_seconds: float = 0.10,
) -> pd.DataFrame:
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    rows: dict[int, float] = {}
    cursor = start_ms
    while cursor < end_ms:
        query = urlencode({
            "symbol": _binance_symbol(symbol),
            "startTime": cursor,
            "endTime": end_ms - 1,
            "limit": 1000,
        })
        payload = _get_json(f"https://fapi.binance.com/fapi/v1/fundingRate?{query}")
        if not isinstance(payload, list):
            raise CrossExchangeFundingError(f"Binance funding payload is not a list for {symbol}")
        if not payload:
            break
        last_time = cursor
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            try:
                ts = int(item["fundingTime"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms <= ts < end_ms and math.isfinite(rate):
                rows[ts] = rate
                last_time = max(last_time, ts)
        next_cursor = last_time + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
    if not rows:
        return pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime(list(rows), unit="ms", utc=True),
        "funding_rate": list(rows.values()),
    })
    return frame.set_index("timestamp").sort_index()


def _daily_funding_totals(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    if values.empty:
        return pd.Series(dtype=float)
    return values.groupby(values.index.floor("D")).sum().sort_index()


def _trailing_expected_daily_rate(
    daily: pd.Series,
    decision_time: pd.Timestamp,
    lookback_days: int,
    minimum_history_days: int,
) -> float | None:
    start = decision_time - pd.Timedelta(days=int(lookback_days))
    sample = daily.loc[(daily.index >= start) & (daily.index < decision_time.floor("D"))]
    if len(sample) < int(minimum_history_days):
        return None
    value = float(sample.mean())
    return value if math.isfinite(value) else None


def _period_funding(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame.empty:
        return 0.0
    values = pd.to_numeric(frame["funding_rate"], errors="coerce").fillna(0.0)
    mask = (values.index > start) & (values.index <= end)
    return float(values.loc[mask].sum())


def build_symbol_daily_returns(
    mexc_prices: pd.DataFrame,
    binance_prices: pd.DataFrame,
    mexc_funding: pd.DataFrame,
    binance_funding: pd.DataFrame,
    spec: FundingDispersionSpec,
    *,
    reverse_control: bool = False,
) -> pd.DataFrame:
    common = mexc_prices.index.intersection(binance_prices.index).sort_values()
    if len(common) < 3:
        raise CrossExchangeFundingError("insufficient common daily opens")
    mexc_daily_funding = _daily_funding_totals(mexc_funding)
    binance_daily_funding = _daily_funding_totals(binance_funding)
    rows: list[dict[str, Any]] = []
    previous_side = 0
    half_rt_cost = float(spec.round_trip_pair_cost_bps) / 20_000.0
    gate_bps = float(spec.round_trip_pair_cost_bps) * float(spec.safety_multiple_over_cost)
    projection_days = int(spec.break_even_projection_days)

    for i in range(len(common) - 1):
        t0, t1 = common[i], common[i + 1]
        mexc_expect = _trailing_expected_daily_rate(
            mexc_daily_funding, t0, spec.funding_lookback_days, spec.minimum_history_days
        )
        binance_expect = _trailing_expected_daily_rate(
            binance_daily_funding, t0, spec.funding_lookback_days, spec.minimum_history_days
        )
        expected_spread = None if mexc_expect is None or binance_expect is None else mexc_expect - binance_expect
        side = 0
        projected_spread_bps = None
        if expected_spread is not None:
            projected_spread_bps = abs(float(expected_spread)) * projection_days * 10_000.0
            if projected_spread_bps >= gate_bps:
                # +1 = short MEXC / long Binance. -1 = long MEXC / short Binance.
                side = 1 if expected_spread > 0 else (-1 if expected_spread < 0 else 0)
        if reverse_control:
            side *= -1

        transition_cost = 0.0
        if previous_side != side:
            if previous_side != 0:
                transition_cost += half_rt_cost
            if side != 0:
                transition_cost += half_rt_cost

        mexc_open0 = float(mexc_prices.loc[t0, "open"])
        mexc_open1 = float(mexc_prices.loc[t1, "open"])
        bin_open0 = float(binance_prices.loc[t0, "open"])
        bin_open1 = float(binance_prices.loc[t1, "open"])
        mexc_ret = mexc_open1 / mexc_open0 - 1.0
        bin_ret = bin_open1 / bin_open0 - 1.0
        price_component = 0.5 * float(spec.gross_exposure) * side * (bin_ret - mexc_ret)

        mexc_rate = _period_funding(mexc_funding, t0, t1)
        bin_rate = _period_funding(binance_funding, t0, t1)
        funding_component = 0.5 * float(spec.gross_exposure) * side * (mexc_rate - bin_rate)
        strategy_return = price_component + funding_component - transition_cost

        rows.append({
            "timestamp": t0,
            "next_timestamp": t1,
            "side": int(side),
            "previous_side": int(previous_side),
            "expected_mexc_daily_funding": mexc_expect,
            "expected_binance_daily_funding": binance_expect,
            "expected_daily_spread": expected_spread,
            "projected_7d_spread_bps": projected_spread_bps,
            "gate_bps": gate_bps,
            "mexc_open_return": mexc_ret,
            "binance_open_return": bin_ret,
            "price_component": price_component,
            "mexc_realized_funding": mexc_rate,
            "binance_realized_funding": bin_rate,
            "funding_component": funding_component,
            "transition_cost": transition_cost,
            "return": strategy_return,
        })
        previous_side = side

    out = pd.DataFrame(rows).set_index("timestamp")
    if previous_side != 0 and not out.empty:
        out.iloc[-1, out.columns.get_loc("transition_cost")] += half_rt_cost
        out.iloc[-1, out.columns.get_loc("return")] -= half_rt_cost
    return out


def summarize_returns(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "observations": 0,
            "active_days": 0,
            "entries": 0,
            "return": 0.0,
            "annualized_sharpe": None,
            "max_drawdown": None,
            "mean_daily_bps": None,
            "active_day_win_rate": None,
            "funding_component_sum_bps": 0.0,
            "price_component_sum_bps": 0.0,
            "cost_sum_bps": 0.0,
        }
    returns = pd.to_numeric(frame["return"], errors="coerce").fillna(0.0).astype(float)
    equity = (1.0 + returns).cumprod()
    peaks = equity.cummax()
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(returns.mean() / std * math.sqrt(365.0)) if std > 0 else None
    active = frame["side"].astype(int) != 0
    entries = int(((frame["side"].astype(int) != frame["previous_side"].astype(int)) & active).sum())
    active_returns = returns.loc[active]
    return {
        "observations": int(len(frame)),
        "active_days": int(active.sum()),
        "entries": entries,
        "return": float(equity.iloc[-1] - 1.0),
        "annualized_sharpe": sharpe,
        "max_drawdown": float((equity / peaks - 1.0).min()),
        "mean_daily_bps": float(returns.mean() * 10_000.0),
        "active_day_win_rate": float((active_returns > 0).mean()) if len(active_returns) else None,
        "funding_component_sum_bps": float(pd.to_numeric(frame["funding_component"], errors="coerce").fillna(0.0).sum() * 10_000.0),
        "price_component_sum_bps": float(pd.to_numeric(frame["price_component"], errors="coerce").fillna(0.0).sum() * 10_000.0),
        "cost_sum_bps": float(pd.to_numeric(frame["transition_cost"], errors="coerce").fillna(0.0).sum() * 10_000.0),
    }


def _portfolio_from_symbol_frames(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=["return"])
    series = [pd.to_numeric(frame["return"], errors="coerce").rename(symbol) for symbol, frame in sorted(frames.items())]
    panel = pd.concat(series, axis=1).sort_index().fillna(0.0)
    out = pd.DataFrame(index=panel.index)
    out["return"] = panel.mean(axis=1)
    out["side"] = 1
    out["previous_side"] = 1
    out["funding_component"] = 0.0
    out["price_component"] = 0.0
    out["transition_cost"] = 0.0
    return out


def evaluate_window(
    datasets: Mapping[str, Mapping[str, pd.DataFrame]],
    spec: FundingDispersionSpec,
    start: str,
    end: str,
    *,
    reverse_control: bool = False,
) -> dict[str, Any]:
    start_ts, end_ts = _utc(start), _utc(end)
    symbol_frames: dict[str, pd.DataFrame] = {}
    per_symbol: list[dict[str, Any]] = []
    for symbol, dataset in sorted(datasets.items()):
        full = build_symbol_daily_returns(
            dataset["mexc_prices"],
            dataset["binance_prices"],
            dataset["mexc_funding"],
            dataset["binance_funding"],
            spec,
            reverse_control=reverse_control,
        )
        cut = full.loc[(full.index >= start_ts) & (full.index < end_ts)].copy()
        symbol_frames[symbol] = cut
        per_symbol.append({"symbol": symbol, **summarize_returns(cut)})
    portfolio = _portfolio_from_symbol_frames(symbol_frames)
    portfolio = portfolio.loc[(portfolio.index >= start_ts) & (portfolio.index < end_ts)]
    portfolio_stats = summarize_returns(portfolio)
    positive = sum(float(row["return"]) > 0 for row in per_symbol)
    return {
        "start_utc": start_ts.isoformat(),
        "end_exclusive_utc": end_ts.isoformat(),
        "reverse_control": bool(reverse_control),
        "portfolio": portfolio_stats,
        "positive_symbol_fraction": positive / len(per_symbol) if per_symbol else None,
        "per_symbol": per_symbol,
    }


def load_symbol_dataset(symbol: str, start: str, end: str) -> dict[str, pd.DataFrame]:
    warmup_start = (_utc(start) - pd.Timedelta(days=14)).isoformat()
    return {
        "mexc_prices": fetch_mexc_futures_klines(symbol, "1d", warmup_start, end),
        "binance_prices": fetch_binance_futures_klines(symbol, warmup_start, end),
        "mexc_funding": fetch_mexc_funding_history(symbol, warmup_start, end),
        "binance_funding": fetch_binance_funding_history(symbol, warmup_start, end),
    }

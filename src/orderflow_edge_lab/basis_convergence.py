from __future__ import annotations

from dataclasses import dataclass
import json
import math
from statistics import median
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


class BasisConvergenceError(ValueError):
    pass


@dataclass(frozen=True)
class BasisVariant:
    upper_entry_bps: float
    lower_exit_bps: float
    round_trip_pair_cost_bps: float


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _get_json(url: str, timeout: float = 20.0) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise BasisConvergenceError(f"public REST returned HTTP {response.status}")
        raw = response.read(16_000_000)
    return json.loads(raw.decode("utf-8"))


def fetch_mexc_spot_klines(symbol: str, start: str, end: str, *, interval: str = "60m") -> pd.DataFrame:
    step_ms = {"60m": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}.get(interval)
    if step_ms is None:
        raise BasisConvergenceError(f"unsupported spot interval: {interval}")
    normalized = symbol.upper().replace("_", "")
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    cursor = start_ms
    rows: dict[int, list[Any]] = {}
    while cursor < end_ms:
        chunk_end = min(end_ms - 1, cursor + step_ms * 999)
        query = urlencode({"symbol": normalized, "interval": interval, "startTime": cursor, "endTime": chunk_end, "limit": 1000})
        payload = _get_json(f"https://api.mexc.com/api/v3/klines?{query}")
        if not isinstance(payload, list):
            raise BasisConvergenceError(f"spot kline payload is not a list for {normalized}")
        if not payload:
            cursor = chunk_end + 1
            continue
        last_open = cursor
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                open_ms = int(row[0])
                values = [float(row[i]) for i in range(1, 6)]
            except (TypeError, ValueError, IndexError):
                continue
            if open_ms < start_ms or open_ms >= end_ms or min(values[:4]) <= 0:
                continue
            rows[open_ms] = row
            last_open = max(last_open, open_ms)
        cursor = max(chunk_end + 1, last_open + step_ms)
    if not rows:
        raise BasisConvergenceError(f"no MEXC spot klines for {normalized}")
    ordered = [rows[key] for key in sorted(rows)]
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([int(r[0]) for r in ordered], unit="ms", utc=True),
        "open": [float(r[1]) for r in ordered],
        "high": [float(r[2]) for r in ordered],
        "low": [float(r[3]) for r in ordered],
        "close": [float(r[4]) for r in ordered],
        "volume": [float(r[5]) for r in ordered],
    }).set_index("timestamp").sort_index()
    if len(frame) < 200:
        raise BasisConvergenceError(f"insufficient MEXC spot candles for {normalized}: {len(frame)}")
    return frame


def fetch_mexc_funding_history(symbol: str, start: str, end: str, *, page_size: int = 1000, max_pages: int = 20) -> pd.DataFrame:
    normalized = symbol.upper()
    if "_" not in normalized and normalized.endswith("USDT"):
        normalized = normalized[:-4] + "_USDT"
    start_ts, end_ts = _utc(start), _utc(end)
    rows: dict[int, float] = {}
    for page in range(1, max_pages + 1):
        query = urlencode({"symbol": normalized, "page_num": page, "page_size": page_size})
        payload = _get_json(f"https://contract.mexc.com/api/v1/contract/funding_rate/history?{query}")
        if not isinstance(payload, Mapping) or payload.get("success") is not True:
            raise BasisConvergenceError(f"funding history request failed for {normalized}: {payload}")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            break
        items = data.get("resultList")
        if not isinstance(items, list) or not items:
            break
        oldest: pd.Timestamp | None = None
        for item in items:
            if not isinstance(item, Mapping):
                continue
            try:
                settle_ms = int(item["settleTime"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            ts = pd.to_datetime(settle_ms, unit="ms", utc=True)
            oldest = ts if oldest is None else min(oldest, ts)
            if start_ts <= ts < end_ts and math.isfinite(rate):
                rows[settle_ms] = rate
        if oldest is not None and oldest <= start_ts:
            break
        total_pages = int(data.get("totalPage") or page)
        if page >= total_pages:
            break
    frame = pd.DataFrame({"timestamp": pd.to_datetime(list(rows), unit="ms", utc=True), "funding_rate": list(rows.values())})
    if frame.empty:
        return pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    return frame.set_index("timestamp").sort_index()


def prepare_basis_frame(spot: pd.DataFrame, perp: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "close"}
    if not required.issubset(spot.columns) or not required.issubset(perp.columns):
        raise BasisConvergenceError("spot and perpetual frames require open/close columns")
    idx = spot.index.intersection(perp.index)
    out = pd.DataFrame(index=idx)
    out["spot_open"] = spot.loc[idx, "open"].astype(float)
    out["spot_close"] = spot.loc[idx, "close"].astype(float)
    out["perp_open"] = perp.loc[idx, "open"].astype(float)
    out["perp_close"] = perp.loc[idx, "close"].astype(float)
    out["basis_close_bps"] = (out["perp_close"] / out["spot_close"] - 1.0) * 10_000.0
    return out.dropna().sort_index()


def simulate_basis_convergence(
    basis: pd.DataFrame,
    funding: pd.DataFrame,
    variant: BasisVariant,
) -> list[dict[str, Any]]:
    if variant.upper_entry_bps <= variant.lower_exit_bps:
        raise BasisConvergenceError("entry threshold must exceed exit threshold")
    if len(basis) < 3:
        return []
    funding_series = funding.get("funding_rate", pd.Series(dtype=float))
    trades: list[dict[str, Any]] = []
    entry_i: int | None = None
    for i in range(1, len(basis)):
        previous_basis = float(basis["basis_close_bps"].iloc[i - 1])
        if entry_i is None and previous_basis >= variant.upper_entry_bps:
            entry_i = i
            continue
        if entry_i is not None and previous_basis <= variant.lower_exit_bps:
            trades.append(_close_trade(basis, funding_series, entry_i, i, variant, "basis_converged"))
            entry_i = None
    if entry_i is not None and entry_i < len(basis) - 1:
        trades.append(_close_trade(basis, funding_series, entry_i, len(basis) - 1, variant, "forced_sample_end"))
    return trades


def _close_trade(
    basis: pd.DataFrame,
    funding: pd.Series,
    entry_i: int,
    exit_i: int,
    variant: BasisVariant,
    reason: str,
) -> dict[str, Any]:
    entry = basis.iloc[entry_i]
    exit_ = basis.iloc[exit_i]
    entry_time = basis.index[entry_i]
    exit_time = basis.index[exit_i]
    spot_ret = float(exit_["spot_open"] / entry["spot_open"] - 1.0)
    perp_ret = float(exit_["perp_open"] / entry["perp_open"] - 1.0)
    mask = (funding.index > entry_time) & (funding.index <= exit_time)
    funding_sum = float(pd.to_numeric(funding.loc[mask], errors="coerce").fillna(0.0).sum()) if len(funding) else 0.0
    # Equal notional spot/perpetual legs. Positive funding is received by the short perpetual leg.
    gross = 0.5 * (spot_ret - perp_ret + funding_sum)
    net = gross - variant.round_trip_pair_cost_bps / 10_000.0
    return {
        "entry_time": entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "exit_reason": reason,
        "entry_signal_basis_bps": float(basis["basis_close_bps"].iloc[entry_i - 1]),
        "exit_signal_basis_bps": float(basis["basis_close_bps"].iloc[max(exit_i - 1, 0)]),
        "spot_return": spot_ret,
        "perp_short_return": -perp_ret,
        "funding_rate_sum": funding_sum,
        "gross_pair_return": gross,
        "net_return": net,
        "holding_hours": float((exit_time - entry_time).total_seconds() / 3600.0),
    }


def _stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(t["net_return"]) for t in trades]
    if not values:
        return {"trades": 0, "expectancy_bps": None, "profit_factor": None, "win_rate": None, "compounded_return": None, "max_drawdown": None}
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    pf: float | str | None = gains / losses if losses > 0 else ("INF" if gains > 0 else None)
    equity = np.cumprod(1.0 + np.asarray(values, dtype=float))
    peaks = np.maximum.accumulate(equity)
    return {
        "trades": len(values),
        "expectancy_bps": float(np.mean(values) * 10_000.0),
        "profit_factor": pf,
        "win_rate": float(np.mean(np.asarray(values) > 0)),
        "compounded_return": float(equity[-1] - 1.0),
        "max_drawdown": float(np.min(equity / peaks - 1.0)),
    }


def evaluate_basis_grid(
    datasets: Mapping[str, tuple[pd.DataFrame, pd.DataFrame]],
    *,
    entry_thresholds: Sequence[float],
    exit_thresholds: Sequence[float],
    cost_cases: Sequence[float],
    fold_days: int = 120,
    minimum_trades: int = 20,
    minimum_folds: int = 4,
    minimum_positive_fold_fraction: float = 0.6,
    minimum_positive_symbol_fraction: float = 0.6,
) -> dict[str, Any]:
    variants: list[dict[str, Any]] = []
    for upper in entry_thresholds:
        for lower in exit_thresholds:
            if float(lower) >= float(upper):
                continue
            for cost in cost_cases:
                variant = BasisVariant(float(upper), float(lower), float(cost))
                symbol_rows: list[dict[str, Any]] = []
                all_trades: list[dict[str, Any]] = []
                for symbol, (basis, funding) in sorted(datasets.items()):
                    trades = simulate_basis_convergence(basis, funding, variant)
                    stats = _stats(trades)
                    symbol_rows.append({"symbol": symbol, **stats})
                    all_trades.extend({"symbol": symbol, **trade} for trade in trades)
                if all_trades:
                    starts = [pd.Timestamp(t["entry_time"]) for t in all_trades]
                    anchor = min(starts).normalize()
                    for trade in all_trades:
                        ts = pd.Timestamp(trade["entry_time"])
                        fold = int((ts - anchor).days // int(fold_days))
                        trade["fold"] = fold
                fold_rows: list[dict[str, Any]] = []
                for fold in sorted({int(t["fold"]) for t in all_trades if "fold" in t}):
                    members = [t for t in all_trades if t.get("fold") == fold]
                    fold_rows.append({"fold": fold, **_stats(members)})
                fold_expect = [float(r["expectancy_bps"]) for r in fold_rows if r.get("expectancy_bps") is not None]
                fold_pf = []
                for row in fold_rows:
                    value = row.get("profit_factor")
                    if value == "INF":
                        fold_pf.append(999.0)
                    elif value is not None:
                        fold_pf.append(float(value))
                positive_folds = sum(v > 0 for v in fold_expect)
                positive_symbols = [r for r in symbol_rows if r.get("expectancy_bps") is not None and float(r["expectancy_bps"]) > 0]
                aggregate = _stats(all_trades)
                positive_fold_fraction = positive_folds / len(fold_expect) if fold_expect else None
                positive_symbol_fraction = len(positive_symbols) / len(symbol_rows) if symbol_rows else None
                eligible = bool(
                    aggregate["trades"] >= minimum_trades
                    and len(fold_rows) >= minimum_folds
                    and positive_fold_fraction is not None and positive_fold_fraction >= minimum_positive_fold_fraction
                    and positive_symbol_fraction is not None and positive_symbol_fraction >= minimum_positive_symbol_fraction
                    and fold_expect and median(fold_expect) > 0
                    and fold_pf and median(fold_pf) > 1.0
                )
                variants.append({
                    "upper_entry_bps": variant.upper_entry_bps,
                    "lower_exit_bps": variant.lower_exit_bps,
                    "round_trip_pair_cost_bps": variant.round_trip_pair_cost_bps,
                    **aggregate,
                    "fold_observations": len(fold_rows),
                    "positive_fold_fraction": positive_fold_fraction,
                    "median_fold_expectancy_bps": float(median(fold_expect)) if fold_expect else None,
                    "median_fold_profit_factor": float(median(fold_pf)) if fold_pf else None,
                    "positive_symbol_fraction": positive_symbol_fraction,
                    "screening_eligible": eligible,
                    "per_symbol": symbol_rows,
                    "per_fold": fold_rows,
                })
    variants.sort(key=lambda r: (bool(r["screening_eligible"]), float(r.get("median_fold_expectancy_bps") or -1e18)), reverse=True)
    return {
        "schema_version": 1,
        "strategy": "positive-basis convergence: long spot / short perpetual",
        "causality": "completed hourly basis signal; next-hour-open execution; funding only while position already spans settlement",
        "dependence_cluster": f"{int(fold_days)}-day calendar fold",
        "variant_count": len(variants),
        "eligible_count": sum(bool(r["screening_eligible"]) for r in variants),
        "variants": variants,
        "claims": {"development_screening_only": True, "profitable_edge_established": False, "verified_out_of_sample_evidence": False, "live_order_transmission_supported": False},
    }


def load_mexc_basis_dataset(symbol: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    spot = fetch_mexc_spot_klines(symbol, start, end, interval="60m")
    perp = fetch_mexc_futures_klines(symbol, "1h", start, end)
    funding = fetch_mexc_funding_history(symbol, start, end)
    return prepare_basis_frame(spot, perp), funding

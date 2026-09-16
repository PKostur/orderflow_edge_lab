from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


class RangeShockMomentumCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateRun:
    observations: pd.DataFrame
    contributions: pd.DataFrame
    weights: pd.DataFrame


def _aligned(
    frames: Mapping[str, pd.DataFrame], symbols: Sequence[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fields: dict[str, dict[str, pd.Series]] = {k: {} for k in ("open", "high", "low", "close")}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            raise RangeShockMomentumCandidateError(f"missing frame: {symbol}")
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise RangeShockMomentumCandidateError(f"{symbol}: DatetimeIndex required")
        frame = frame.sort_index()
        if frame.index.has_duplicates:
            raise RangeShockMomentumCandidateError(f"{symbol}: duplicate timestamps")
        required = {"open", "high", "low", "close"}
        if not required.issubset(frame.columns):
            raise RangeShockMomentumCandidateError(f"{symbol}: OHLC required")
        for field in fields:
            fields[field][symbol] = pd.to_numeric(frame[field], errors="coerce")
    matrices = {field: pd.concat(values, axis=1, join="inner").sort_index() for field, values in fields.items()}
    idx = matrices["open"].index
    for field in ("high", "low", "close"):
        idx = idx.intersection(matrices[field].index)
    aligned = {field: matrix.loc[idx].astype(float) for field, matrix in matrices.items()}
    valid = pd.Series(True, index=idx)
    for matrix in aligned.values():
        valid &= ~matrix.isna().any(axis=1)
    aligned = {field: matrix.loc[valid] for field, matrix in aligned.items()}
    if len(aligned["open"]) < 60:
        raise RangeShockMomentumCandidateError("insufficient aligned history")
    if any((aligned[f] <= 0).any().any() for f in aligned):
        raise RangeShockMomentumCandidateError("non-positive OHLC")
    if (aligned["high"] < aligned["low"]).any().any():
        raise RangeShockMomentumCandidateError("high below low")
    return aligned["open"], aligned["high"], aligned["low"], aligned["close"]


def _funding(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    return float(rates.loc[(rates.index > start) & (rates.index < end)].sum())


def _target(scores: pd.Series, reverse: bool) -> pd.Series:
    ranked = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().sort_values()
    if len(ranked) < 6:
        raise RangeShockMomentumCandidateError("at least six ranked symbols required")
    low, high = list(ranked.index[:2]), list(ranked.index[-2:])
    out = pd.Series(0.0, index=scores.index, dtype=float)
    if reverse:
        out.loc[low] = 0.25
        out.loc[high] = -0.25
    else:
        out.loc[high] = 0.25
        out.loc[low] = -0.25
    return out


def run_range_shock_momentum_candidate(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    range_baseline_days: int = 30,
    fixed_evaluation_warmup_days: int = 45,
    side_cost_bps: float = 10.0,
    reverse: bool = False,
    force_terminal_liquidation: bool = True,
) -> CandidateRun:
    opens, highs, lows, closes = _aligned(daily_frames, symbols)
    if int(fixed_evaluation_warmup_days) < int(range_baseline_days):
        raise RangeShockMomentumCandidateError("warmup shorter than range baseline")

    previous_close = closes.shift(1)
    true_range = pd.DataFrame(
        np.maximum.reduce([
            (highs - lows).to_numpy(dtype=float),
            (highs - previous_close).abs().to_numpy(dtype=float),
            (lows - previous_close).abs().to_numpy(dtype=float),
        ]),
        index=opens.index,
        columns=opens.columns,
    )
    direction = closes / opens - 1.0

    rows: list[dict] = []
    legs: list[dict] = []
    weight_rows: list[pd.Series] = []
    weight_index: list[pd.Timestamp] = []
    previous = pd.Series(0.0, index=opens.columns, dtype=float)
    signal_indices = list(range(int(fixed_evaluation_warmup_days), len(opens) - 2))

    for position, i in enumerate(signal_indices):
        baseline = true_range.iloc[i - int(range_baseline_days):i].median(axis=0).replace(0.0, np.nan)
        score = direction.iloc[i] * (true_range.iloc[i] / baseline)
        target = _target(score, reverse=reverse).reindex(opens.columns, fill_value=0.0)
        start, end = opens.index[i + 1], opens.index[i + 2]
        price_return = opens.loc[end] / opens.loc[start] - 1.0
        final_period = position == len(signal_indices) - 1
        gross = 0.0
        cost = 0.0
        for symbol in opens.columns:
            w = float(target[symbol])
            prev = float(previous[symbol])
            funding = _funding(funding_frames.get(symbol) if funding_frames else None, start, end)
            leg_gross = w * (float(price_return[symbol]) - funding)
            leg_cost = abs(w - prev) * float(side_cost_bps) / 10_000.0
            if force_terminal_liquidation and final_period:
                leg_cost += abs(w) * float(side_cost_bps) / 10_000.0
            gross += leg_gross
            cost += leg_cost
            legs.append({"timestamp": start, "symbol": symbol, "net_contribution_bps": (leg_gross - leg_cost) * 10_000.0})
        rows.append({
            "timestamp": start,
            "end_timestamp": end,
            "gross_return_bps": gross * 10_000.0,
            "cost_bps": cost * 10_000.0,
            "net_return_bps": (gross - cost) * 10_000.0,
            "active_gross": float(target.abs().sum()),
        })
        weight_rows.append(target.copy())
        weight_index.append(start)
        previous = target

    if not rows:
        raise RangeShockMomentumCandidateError("no completed observations")
    return CandidateRun(
        observations=pd.DataFrame(rows).set_index("timestamp"),
        contributions=pd.DataFrame(legs),
        weights=pd.DataFrame(weight_rows, index=pd.DatetimeIndex(weight_index, name="timestamp")),
    )

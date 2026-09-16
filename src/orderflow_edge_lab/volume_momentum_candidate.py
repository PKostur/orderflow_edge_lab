from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


class VolumeMomentumCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateRun:
    observations: pd.DataFrame
    contributions: pd.DataFrame
    weights: pd.DataFrame


def _aligned(frames: Mapping[str, pd.DataFrame], symbols: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            raise VolumeMomentumCandidateError(f"missing frame: {symbol}")
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise VolumeMomentumCandidateError(f"{symbol}: DatetimeIndex required")
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            frame = frame.sort_index()
            if frame.index.has_duplicates:
                raise VolumeMomentumCandidateError(f"{symbol}: duplicate timestamps")
        if not {"open", "close", "volume"}.issubset(frame.columns):
            raise VolumeMomentumCandidateError(f"{symbol}: open/close/volume required")
        opens[symbol] = pd.to_numeric(frame["open"], errors="coerce")
        closes[symbol] = pd.to_numeric(frame["close"], errors="coerce")
        volumes[symbol] = pd.to_numeric(frame["volume"], errors="coerce")
    o = pd.concat(opens, axis=1, join="inner")
    c = pd.concat(closes, axis=1, join="inner")
    v = pd.concat(volumes, axis=1, join="inner")
    idx = o.index.intersection(c.index).intersection(v.index).sort_values()
    o, c, v = o.loc[idx].astype(float), c.loc[idx].astype(float), v.loc[idx].astype(float)
    mask = ~(o.isna().any(axis=1) | c.isna().any(axis=1) | v.isna().any(axis=1))
    o, c, v = o.loc[mask], c.loc[mask], v.loc[mask]
    if len(o) < 60:
        raise VolumeMomentumCandidateError(f"insufficient aligned history: {len(o)}")
    if (o <= 0).any().any() or (c <= 0).any().any() or (v < 0).any().any():
        raise VolumeMomentumCandidateError("invalid non-positive price or negative volume")
    return o, c, v


def _funding(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    return float(rates.loc[(rates.index > start) & (rates.index < end)].sum())


def _weights(scores: pd.Series, reverse: bool) -> pd.Series:
    ranked = pd.to_numeric(scores, errors="coerce").dropna().sort_values()
    if len(ranked) < 6:
        raise VolumeMomentumCandidateError("at least six ranked symbols required")
    low = list(ranked.index[:2])
    high = list(ranked.index[-2:])
    target = pd.Series(0.0, index=scores.index, dtype=float)
    if reverse:
        target.loc[low] = 0.25
        target.loc[high] = -0.25
    else:
        target.loc[high] = 0.25
        target.loc[low] = -0.25
    return target


def run_volume_momentum_candidate(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    volume_baseline_days: int = 30,
    fixed_evaluation_warmup_days: int = 45,
    side_cost_bps: float = 10.0,
    reverse: bool = False,
    force_terminal_liquidation: bool = True,
) -> CandidateRun:
    opens, closes, volumes = _aligned(daily_frames, symbols)
    if fixed_evaluation_warmup_days < volume_baseline_days:
        raise VolumeMomentumCandidateError("warmup cannot be shorter than economic lookback")
    returns = closes.pct_change()
    rows: list[dict] = []
    legs: list[dict] = []
    weight_rows: list[pd.Series] = []
    weight_index: list[pd.Timestamp] = []
    previous = pd.Series(0.0, index=opens.columns, dtype=float)

    signal_indices = list(range(int(fixed_evaluation_warmup_days), len(opens) - 2))
    for position, i in enumerate(signal_indices):
        baseline = volumes.iloc[i - int(volume_baseline_days):i].median(axis=0).replace(0.0, np.nan)
        score = returns.iloc[i] * (volumes.iloc[i] / baseline)
        score = pd.to_numeric(score, errors="coerce").replace([np.inf, -np.inf], np.nan)
        target = _weights(score, reverse=reverse).reindex(opens.columns, fill_value=0.0)
        start = opens.index[i + 1]
        end = opens.index[i + 2]
        price_returns = opens.loc[end] / opens.loc[start] - 1.0
        final_period = position == len(signal_indices) - 1
        gross = 0.0
        cost = 0.0
        for symbol in opens.columns:
            w = float(target[symbol])
            prev = float(previous[symbol])
            funding = _funding(funding_frames.get(symbol) if funding_frames else None, start, end)
            leg_gross = w * (float(price_returns[symbol]) - funding)
            leg_cost = abs(w - prev) * float(side_cost_bps) / 10_000.0
            if force_terminal_liquidation and final_period:
                leg_cost += abs(w) * float(side_cost_bps) / 10_000.0
            gross += leg_gross
            cost += leg_cost
            legs.append({
                "timestamp": start,
                "symbol": symbol,
                "net_contribution_bps": (leg_gross - leg_cost) * 10_000.0,
            })
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
        raise VolumeMomentumCandidateError("no completed observations")
    observations = pd.DataFrame(rows).set_index("timestamp")
    contributions = pd.DataFrame(legs)
    weights = pd.DataFrame(weight_rows, index=pd.DatetimeIndex(weight_index, name="timestamp"))
    return CandidateRun(observations=observations, contributions=contributions, weights=weights)

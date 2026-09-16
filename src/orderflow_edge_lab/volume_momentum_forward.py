from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


class VolumeMomentumForwardError(ValueError):
    pass


def _align(
    frames: Mapping[str, pd.DataFrame], symbols: Sequence[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    opens = pd.concat(
        {s: pd.to_numeric(frames[s]["open"], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).dropna().sort_index()
    closes = pd.concat(
        {s: pd.to_numeric(frames[s]["close"], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).dropna().sort_index()
    volumes = pd.concat(
        {s: pd.to_numeric(frames[s]["volume"], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).dropna().sort_index()
    idx = opens.index.intersection(closes.index).intersection(volumes.index).sort_values()
    opens, closes, volumes = opens.loc[idx], closes.loc[idx], volumes.loc[idx]
    if len(idx) < 45 or idx.has_duplicates:
        raise VolumeMomentumForwardError("invalid aligned history")
    if (opens <= 0).any().any() or (closes <= 0).any().any() or (volumes < 0).any().any():
        raise VolumeMomentumForwardError("invalid price or volume")
    return opens.astype(float), closes.astype(float), volumes.astype(float)


def _target(scores: pd.Series, reverse: bool = False) -> pd.Series:
    ranked = pd.to_numeric(scores, errors="coerce").dropna().sort_values()
    out = pd.Series(0.0, index=scores.index, dtype=float)
    if len(ranked) < 6:
        return out
    low = list(ranked.index[:2])
    high = list(ranked.index[-2:])
    if reverse:
        out.loc[low] = 0.25
        out.loc[high] = -0.25
    else:
        out.loc[high] = 0.25
        out.loc[low] = -0.25
    return out


def _funding(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty or "funding_rate" not in frame.columns:
        return 0.0
    rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    return float(rates.loc[(rates.index > start) & (rates.index < end)].sum())


def simulate_forward(
    frames: Mapping[str, pd.DataFrame],
    funding_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    volume_baseline_days: int,
    forward_start: pd.Timestamp,
    asof: pd.Timestamp,
    side_cost_bps: float,
    reverse: bool = False,
) -> dict:
    opens, closes, volumes = _align(frames, symbols)
    returns = closes.pct_change()
    forward_start = pd.Timestamp(forward_start)
    asof = pd.Timestamp(asof)
    if forward_start.tzinfo is None:
        forward_start = forward_start.tz_localize("UTC")
    else:
        forward_start = forward_start.tz_convert("UTC")
    if asof.tzinfo is None:
        asof = asof.tz_localize("UTC")
    else:
        asof = asof.tz_convert("UTC")

    signals: list[tuple[int, pd.Series]] = []
    for i in range(int(volume_baseline_days), len(opens) - 1):
        signal_completed_at = opens.index[i] + pd.Timedelta(days=1)
        if signal_completed_at > asof:
            continue
        baseline = volumes.iloc[i - int(volume_baseline_days):i].median(axis=0).replace(0.0, np.nan)
        scores = returns.iloc[i] * (volumes.iloc[i] / baseline)
        scores = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan)
        signals.append((i, _target(scores, reverse=reverse).reindex(list(symbols), fill_value=0.0)))

    previous = pd.Series(0.0, index=list(symbols), dtype=float)
    rows: list[dict] = []
    contributions: list[dict] = []
    weights: list[pd.Series] = []
    weight_times: list[pd.Timestamp] = []
    open_position = None

    for signal_i, target in signals:
        start_i = signal_i + 1
        if start_i >= len(opens):
            continue
        start = opens.index[start_i]
        if start < forward_start:
            continue

        turnover_cost = (target - previous).abs() * float(side_cost_bps) / 10_000.0
        end_i = start_i + 1
        if end_i >= len(opens) or opens.index[end_i] > asof:
            open_position = {
                "entry_time": start.isoformat(),
                "weights": {s: float(target[s]) for s in symbols if abs(float(target[s])) > 1e-12},
                "entry_cost_bps": float(turnover_cost.sum() * 10_000.0),
            }
            break

        end = opens.index[end_i]
        price_returns = opens.loc[end] / opens.loc[start] - 1.0
        gross = 0.0
        cost = float(turnover_cost.sum())
        for symbol in symbols:
            w = float(target[symbol])
            leg_gross = w * (float(price_returns[symbol]) - _funding(funding_frames.get(symbol), start, end))
            leg_net = leg_gross - float(turnover_cost[symbol])
            gross += leg_gross
            contributions.append(
                {
                    "timestamp": start,
                    "symbol": symbol,
                    "net_contribution_bps": leg_net * 10_000.0,
                }
            )
        rows.append(
            {
                "timestamp": start,
                "end_timestamp": end,
                "gross_return_bps": gross * 10_000.0,
                "cost_bps": cost * 10_000.0,
                "net_return_bps": (gross - cost) * 10_000.0,
                "active_gross": float(target.abs().sum()),
            }
        )
        weights.append(target.copy())
        weight_times.append(start)
        previous = target

    observations = pd.DataFrame(rows)
    if not observations.empty:
        observations = observations.set_index("timestamp")
    contrib = pd.DataFrame(contributions)
    weight_frame = pd.DataFrame(weights, index=pd.DatetimeIndex(weight_times, name="timestamp"))
    return {
        "observations": observations,
        "contributions": contrib,
        "weights": weight_frame,
        "open_position": open_position,
    }


def observations_sha256(observations: pd.DataFrame) -> str:
    if observations.empty:
        payload = b""
    else:
        canonical = observations.copy().sort_index()
        payload = canonical.to_csv(index_label="timestamp", float_format="%.15g").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def summarize(run: dict, cost_multipliers=(1.0, 1.5, 2.0)) -> dict:
    obs = run["observations"]
    if obs.empty:
        return {
            "completed_periods": 0,
            "pnl_per_1000": 0.0,
            "max_drawdown": None,
            "cost_cases": {},
            "open_position": run["open_position"],
            "observations_sha256": observations_sha256(obs),
        }
    gross = obs["gross_return_bps"].astype(float)
    costs = obs["cost_bps"].astype(float)
    cases = {}
    for multiplier in cost_multipliers:
        returns = (gross - costs * float(multiplier)) / 10_000.0
        equity = (1.0 + returns).cumprod()
        drawdown = equity / equity.cummax() - 1.0
        cases[str(float(multiplier))] = {
            "mean_net_bps": float((returns * 10_000.0).mean()),
            "pnl_per_1000": float((equity.iloc[-1] - 1.0) * 1000.0),
            "max_drawdown": float(drawdown.min()),
        }
    return {
        "completed_periods": int(len(obs)),
        "start": obs.index.min().isoformat(),
        "end": pd.Timestamp(obs["end_timestamp"].max()).isoformat(),
        "pnl_per_1000": cases["1.0"]["pnl_per_1000"],
        "max_drawdown": cases["1.0"]["max_drawdown"],
        "cost_cases": cases,
        "open_position": run["open_position"],
        "observations_sha256": observations_sha256(obs),
    }

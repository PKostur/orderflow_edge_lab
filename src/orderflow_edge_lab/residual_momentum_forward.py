from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


class ResidualMomentumForwardError(ValueError):
    pass


def _align(frames: Mapping[str, pd.DataFrame], symbols: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens = pd.concat({s: pd.to_numeric(frames[s]["open"], errors="coerce") for s in symbols}, axis=1, join="inner").dropna().sort_index()
    closes = pd.concat({s: pd.to_numeric(frames[s]["close"], errors="coerce") for s in symbols}, axis=1, join="inner").dropna().sort_index()
    idx = opens.index.intersection(closes.index)
    opens, closes = opens.loc[idx].astype(float), closes.loc[idx].astype(float)
    if len(idx) < 50 or opens.index.has_duplicates or closes.index.has_duplicates:
        raise ResidualMomentumForwardError("invalid aligned history")
    return opens, closes


def _ols(x: np.ndarray, y: np.ndarray, now: float) -> float:
    coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(x)), x]), y, rcond=None)
    return float(coef[0] + coef[1] * now)


def _target(scores: pd.Series, reverse: bool) -> pd.Series:
    ranked = scores.dropna().sort_values(); out = pd.Series(0.0, index=scores.index, dtype=float)
    if len(ranked) < 4: return out
    low, high = list(ranked.index[:2]), list(ranked.index[-2:])
    if reverse:
        out.loc[high] = 0.25; out.loc[low] = -0.25
    else:
        out.loc[low] = 0.25; out.loc[high] = -0.25
    return out


def _funding(frame: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if frame is None or frame.empty: return 0.0
    s = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
    return float(s.loc[(s.index > start) & (s.index < end)].sum())


def simulate_forward(
    frames: Mapping[str, pd.DataFrame],
    funding_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    lookback: int,
    forward_start: pd.Timestamp,
    asof: pd.Timestamp,
    side_cost_bps: float,
    reverse: bool,
) -> dict:
    opens, closes = _align(frames, symbols); returns = closes.pct_change(); alts = [s for s in symbols if s != "BTC_USDT"]
    completed_signal = pd.Series(opens.index + pd.Timedelta(days=1) <= asof, index=opens.index)
    signals: list[tuple[pd.Timestamp, pd.Series]] = []
    for i in range(lookback + 1, len(opens)):
        if not bool(completed_signal.iloc[i]): continue
        x = returns["BTC_USDT"].iloc[i-lookback:i].to_numpy(dtype=float); xnow = float(returns["BTC_USDT"].iloc[i])
        if not np.isfinite(x).all() or not math.isfinite(xnow): continue
        scores = pd.Series(index=alts, dtype=float)
        for s in alts:
            y = returns[s].iloc[i-lookback:i].to_numpy(dtype=float); ynow = float(returns[s].iloc[i])
            scores[s] = ynow - _ols(x, y, xnow) if np.isfinite(y).all() and math.isfinite(ynow) else np.nan
        signals.append((opens.index[i], _target(scores, reverse=reverse)))

    previous = pd.Series(0.0, index=symbols, dtype=float); rows = []; contributions = []; open_position = None
    for signal_time, target in signals:
        pos = opens.index.get_indexer([signal_time])[0]; start_i = pos + 1
        if start_i >= len(opens): continue
        start = opens.index[start_i]
        if start < forward_start: continue
        turnover_cost = (target - previous).abs() * side_cost_bps / 10000.0
        end_i = start_i + 1
        if end_i >= len(opens) or opens.index[end_i] > asof:
            open_position = {"entry_time": start.isoformat(), "weights": {s: float(target[s]) for s in symbols if abs(float(target[s])) > 1e-12}, "entry_cost_bps": float(turnover_cost.sum()*10000.0)}
            break
        end = opens.index[end_i]; price = opens.loc[end] / opens.loc[start] - 1.0
        gross = 0.0; cost = float(turnover_cost.sum()); legs = {}
        for s in symbols:
            w = float(target[s]); leg = w * (float(price[s]) - _funding(funding_frames.get(s), start, end)); gross += leg
            legs[s] = leg - float(turnover_cost[s])
        rows.append({"timestamp": start, "end_timestamp": end, "gross_return_bps": gross*10000.0, "cost_bps": cost*10000.0, "net_return_bps": (gross-cost)*10000.0})
        for s, value in legs.items():
            if abs(value) > 1e-15: contributions.append({"timestamp": start, "symbol": s, "net_contribution_bps": value*10000.0})
        previous = target
    obs = pd.DataFrame(rows)
    if not obs.empty: obs = obs.set_index("timestamp")
    contrib = pd.DataFrame(contributions)
    return {"observations": obs, "contributions": contrib, "open_position": open_position}


def summarize(run: dict, cost_multipliers=(1.0, 1.5, 2.0)) -> dict:
    obs = run["observations"]
    if obs.empty:
        return {"completed_periods": 0, "pnl_per_1000": 0.0, "max_drawdown": None, "cost_cases": {}, "open_position": run["open_position"]}
    base = obs["gross_return_bps"].astype(float); costs = obs["cost_bps"].astype(float)
    cases = {}
    for m in cost_multipliers:
        r = (base - costs*float(m))/10000.0; eq = (1+r).cumprod(); dd = eq/eq.cummax()-1
        cases[str(float(m))] = {"mean_net_bps": float((r*10000).mean()), "pnl_per_1000": float((eq.iloc[-1]-1)*1000.0), "max_drawdown": float(dd.min())}
    return {"completed_periods": int(len(obs)), "start": obs.index.min().isoformat(), "end": pd.Timestamp(obs["end_timestamp"].max()).isoformat(), "pnl_per_1000": cases["1.0"]["pnl_per_1000"], "max_drawdown": cases["1.0"]["max_drawdown"], "cost_cases": cases, "open_position": run["open_position"]}

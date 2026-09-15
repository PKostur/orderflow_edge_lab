from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


STATE_ORDER = [
    "DOWN|LOW",
    "DOWN|NORMAL",
    "DOWN|HIGH",
    "FLAT|LOW",
    "FLAT|NORMAL",
    "FLAT|HIGH",
    "UP|LOW",
    "UP|NORMAL",
    "UP|HIGH",
]

_DIRECTION = ("DOWN", "FLAT", "UP")


@dataclass(frozen=True)
class MarkovStateSpec:
    direction_scale_lookback_bars: int = 30
    direction_z_down_lt: float = -0.5
    direction_z_up_gt: float = 0.5
    volatility_short_lookback_bars: int = 10
    volatility_long_lookback_bars: int = 60
    volatility_ratio_low_lt: float = 0.8
    volatility_ratio_high_gt: float = 1.2
    transition_smoothing_alpha: float = 0.5
    minimum_state_transition_count_for_reliable_label: int = 20


def _direction_label(z: float, spec: MarkovStateSpec) -> str:
    if z < spec.direction_z_down_lt:
        return "DOWN"
    if z > spec.direction_z_up_gt:
        return "UP"
    return "FLAT"


def _volatility_label(ratio: float, spec: MarkovStateSpec) -> str:
    if ratio < spec.volatility_ratio_low_lt:
        return "LOW"
    if ratio > spec.volatility_ratio_high_gt:
        return "HIGH"
    return "NORMAL"


def build_price_states(frame: pd.DataFrame, spec: MarkovStateSpec) -> pd.DataFrame:
    if "close" not in frame.columns:
        raise ValueError("price frame must contain close")
    close = pd.to_numeric(frame["close"], errors="coerce")
    if (close <= 0).any():
        raise ValueError("close prices must be positive")

    log_return = np.log(close / close.shift(1))
    prior = log_return.shift(1)
    direction_scale = prior.rolling(spec.direction_scale_lookback_bars).std(ddof=0)
    short_vol = prior.rolling(spec.volatility_short_lookback_bars).std(ddof=0)
    long_vol = prior.rolling(spec.volatility_long_lookback_bars).std(ddof=0)

    direction_z = log_return / direction_scale.replace(0.0, np.nan)
    volatility_ratio = short_vol / long_vol.replace(0.0, np.nan)

    out = pd.DataFrame(
        {
            "close": close,
            "log_return": log_return,
            "direction_z": direction_z,
            "volatility_ratio": volatility_ratio,
        },
        index=frame.index,
    )
    valid = out[["log_return", "direction_z", "volatility_ratio"]].notna().all(axis=1)
    out = out.loc[valid].copy()
    out["direction"] = [
        _direction_label(float(value), spec) for value in out["direction_z"].to_numpy()
    ]
    out["volatility"] = [
        _volatility_label(float(value), spec) for value in out["volatility_ratio"].to_numpy()
    ]
    out["state"] = out["direction"] + "|" + out["volatility"]
    return out


def fit_transition_matrix(
    states: pd.Series,
    *,
    alpha: float,
    state_order: Iterable[str] = STATE_ORDER,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = list(state_order)
    counts = pd.DataFrame(0, index=labels, columns=labels, dtype=int)
    clean = states.dropna().astype(str)
    for current, nxt in zip(clean.iloc[:-1], clean.iloc[1:]):
        if current in counts.index and nxt in counts.columns:
            counts.loc[current, nxt] += 1

    denom = counts.sum(axis=1).astype(float) + alpha * len(labels)
    probs = (counts.astype(float) + alpha).div(denom, axis=0)
    return counts, probs


def _matrix_power_probs(
    transition: pd.DataFrame,
    current_state: str,
    steps: int,
) -> dict[str, float]:
    if steps < 1:
        raise ValueError("forecast steps must be positive")
    labels = list(transition.index)
    if current_state not in labels:
        raise ValueError(f"unknown current state: {current_state}")
    power = np.linalg.matrix_power(transition.to_numpy(dtype=float), steps)
    row = power[labels.index(current_state)]
    return {label: float(value) for label, value in zip(labels, row)}


def _collapse_direction(state_probs: dict[str, float]) -> dict[str, float]:
    result = {direction: 0.0 for direction in _DIRECTION}
    for state, probability in state_probs.items():
        direction = state.split("|", 1)[0]
        if direction in result:
            result[direction] += float(probability)
    return result


def _conditional_next_return_stats(states: pd.DataFrame, current_state: str) -> dict[str, Any]:
    work = states[["state", "log_return"]].copy()
    work["next_log_return"] = work["log_return"].shift(-1)
    sample = work.loc[work["state"] == current_state, "next_log_return"].dropna()
    n = int(sample.size)
    if n == 0:
        return {
            "observations": 0,
            "prob_next_positive": None,
            "prob_next_negative": None,
            "mean_next_return_bps": None,
            "median_next_return_bps": None,
        }
    positives = int((sample > 0).sum())
    negatives = int((sample < 0).sum())
    # Symmetric beta(0.5, 0.5) smoothing avoids 0/1 estimates in sparse states.
    positive_prob = (positives + 0.5) / (n + 1.0)
    negative_prob = (negatives + 0.5) / (n + 1.0)
    return {
        "observations": n,
        "prob_next_positive": float(positive_prob),
        "prob_next_negative": float(negative_prob),
        "mean_next_return_bps": float(sample.mean() * 10_000.0),
        "median_next_return_bps": float(sample.median() * 10_000.0),
    }


def analyze_symbol(
    frame: pd.DataFrame,
    *,
    training_end_exclusive_utc: str,
    forecast_steps: Iterable[int],
    spec: MarkovStateSpec,
) -> dict[str, Any]:
    states = build_price_states(frame, spec)
    cutoff = pd.Timestamp(training_end_exclusive_utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    training = states.loc[states.index < cutoff].copy()
    if len(training) < spec.volatility_long_lookback_bars + 20:
        raise ValueError(f"insufficient pre-freeze Markov states: {len(training)}")
    if states.empty:
        raise ValueError("no valid price states")

    counts, transition = fit_transition_matrix(
        training["state"],
        alpha=spec.transition_smoothing_alpha,
    )
    current = states.iloc[-1]
    current_state = str(current["state"])
    state_transition_count = int(counts.loc[current_state].sum())

    forecasts: dict[str, Any] = {}
    for steps in sorted({int(value) for value in forecast_steps if int(value) > 0}):
        probs = _matrix_power_probs(transition, current_state, steps)
        forecasts[str(steps)] = {
            "state_probabilities": probs,
            "direction_probabilities": _collapse_direction(probs),
        }

    return {
        "latest_completed_state_timestamp_utc": states.index[-1].isoformat(),
        "current_state": current_state,
        "current_direction_z": float(current["direction_z"]),
        "current_volatility_ratio": float(current["volatility_ratio"]),
        "training_state_observations": int(len(training)),
        "training_transition_observations": int(max(len(training) - 1, 0)),
        "current_state_transition_count": state_transition_count,
        "current_state_reliability": (
            "adequate"
            if state_transition_count >= spec.minimum_state_transition_count_for_reliable_label
            else "sparse"
        ),
        "conditional_next_return": _conditional_next_return_stats(training, current_state),
        "forecasts": forecasts,
        "transition_counts": {
            row: {col: int(counts.loc[row, col]) for col in counts.columns}
            for row in counts.index
        },
        "transition_probabilities": {
            row: {col: float(transition.loc[row, col]) for col in transition.columns}
            for row in transition.index
        },
    }


def aggregate_candidate(symbol_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not symbol_results:
        return {}

    next_positive = []
    next_bps = []
    reliability = {"adequate": 0, "sparse": 0}
    for result in symbol_results.values():
        stats = result["conditional_next_return"]
        if stats["prob_next_positive"] is not None:
            next_positive.append(float(stats["prob_next_positive"]))
        if stats["mean_next_return_bps"] is not None:
            next_bps.append(float(stats["mean_next_return_bps"]))
        reliability[result["current_state_reliability"]] += 1

    return {
        "symbols": len(symbol_results),
        "median_conditional_prob_next_positive": (
            float(np.median(next_positive)) if next_positive else None
        ),
        "median_conditional_mean_next_return_bps": (
            float(np.median(next_bps)) if next_bps else None
        ),
        "current_state_reliability_counts": reliability,
    }

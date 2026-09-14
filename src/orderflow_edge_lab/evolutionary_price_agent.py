from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


FEATURES_PER_BAR = 5


@dataclass
class Genome:
    lookback: int
    hold_bars: int
    threshold: float
    bias: float
    weights: np.ndarray

    def clone(self) -> "Genome":
        return Genome(self.lookback, self.hold_bars, self.threshold, self.bias, self.weights.copy())


def raw_feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"frame missing required fields: {sorted(required - set(frame.columns))}")
    close = frame["close"].astype(float)
    safe_close = close.replace(0.0, np.nan)
    volume = frame["volume"].astype(float).clip(lower=1e-12)
    out = pd.DataFrame(index=frame.index)
    out["ret"] = np.log(safe_close / safe_close.shift(1))
    out["open_rel"] = np.log(frame["open"].astype(float) / safe_close)
    out["high_rel"] = np.log(frame["high"].astype(float) / safe_close)
    out["low_rel"] = np.log(frame["low"].astype(float) / safe_close)
    out["vol_chg"] = np.log(volume / volume.shift(1))
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _window_vector(features: np.ndarray, index: int, lookback: int, maximum_lookback: int) -> np.ndarray:
    start = index - lookback + 1
    window = features[start : index + 1]
    flat = window.reshape(-1)
    result = np.zeros(maximum_lookback * FEATURES_PER_BAR, dtype=float)
    result[-len(flat) :] = flat
    scale = float(np.std(flat))
    if scale > 1e-12:
        result[-len(flat) :] /= scale
    return result


def signal_scores(frame: pd.DataFrame, genome: Genome, maximum_lookback: int) -> np.ndarray:
    features = raw_feature_matrix(frame).to_numpy(dtype=float)
    scores = np.zeros(len(frame), dtype=float)
    for i in range(maximum_lookback - 1, len(frame)):
        vector = _window_vector(features, i, genome.lookback, maximum_lookback)
        scores[i] = genome.bias + float(np.dot(genome.weights, vector)) / math.sqrt(max(1, genome.lookback * FEATURES_PER_BAR))
    return scores


def simulate_trades(
    frame: pd.DataFrame,
    genome: Genome,
    *,
    maximum_lookback: int,
    round_trip_cost_bps: float,
) -> list[dict[str, Any]]:
    if len(frame) <= maximum_lookback + genome.hold_bars + 2:
        return []
    scores = signal_scores(frame, genome, maximum_lookback)
    opens = frame["open"].astype(float).to_numpy()
    timestamps = frame.index
    cost = float(round_trip_cost_bps) / 10_000.0
    trades: list[dict[str, Any]] = []
    i = maximum_lookback - 1
    last_signal = len(frame) - genome.hold_bars - 2
    while i <= last_signal:
        score = float(scores[i])
        side = 1 if score >= genome.threshold else (-1 if score <= -genome.threshold else 0)
        if side == 0:
            i += 1
            continue
        entry_i = i + 1
        exit_i = entry_i + genome.hold_bars
        gross = side * (opens[exit_i] / opens[entry_i] - 1.0)
        net = gross - cost
        trades.append(
            {
                "signal_time": timestamps[i].isoformat(),
                "entry_time": timestamps[entry_i].isoformat(),
                "exit_time": timestamps[exit_i].isoformat(),
                "side": side,
                "score": score,
                "gross_return": float(gross),
                "net_return": float(net),
            }
        )
        i = exit_i
    return trades


def trade_stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = np.asarray([float(t["net_return"]) for t in trades], dtype=float)
    if len(values) == 0:
        return {
            "trades": 0,
            "expectancy_bps": None,
            "profit_factor": None,
            "win_rate": None,
            "total_return": 0.0,
            "max_drawdown": None,
        }
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    pf: float | str | None = gains / losses if losses > 0 else ("INF" if gains > 0 else None)
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(equity)
    return {
        "trades": int(len(values)),
        "expectancy_bps": float(values.mean() * 10_000.0),
        "profit_factor": pf,
        "win_rate": float((values > 0).mean()),
        "total_return": float(equity[-1] - 1.0),
        "max_drawdown": float(np.min(equity / peaks - 1.0)),
    }


def _pf_number(value: Any) -> float | None:
    if value == "INF":
        return 10.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate_genome(
    frame: pd.DataFrame,
    genome: Genome,
    *,
    maximum_lookback: int,
    round_trip_cost_bps: float,
    fold_days: int,
    minimum_trades_per_fold: int,
    minimum_folds: int,
    fitness_weights: Mapping[str, float],
) -> dict[str, Any]:
    trades = simulate_trades(
        frame,
        genome,
        maximum_lookback=maximum_lookback,
        round_trip_cost_bps=round_trip_cost_bps,
    )
    if not trades:
        return {"fitness": -1e9, "trades": 0, "per_fold": [], "aggregate": trade_stats([])}
    anchor = frame.index.min().normalize()
    by_fold: dict[int, list[dict[str, Any]]] = {}
    for trade in trades:
        ts = pd.Timestamp(trade["entry_time"])
        fold = int((ts - anchor).days // int(fold_days))
        by_fold.setdefault(fold, []).append(trade)
    fold_rows = []
    for fold, members in sorted(by_fold.items()):
        stats = trade_stats(members)
        fold_rows.append({"fold": fold, **stats})
    valid = [row for row in fold_rows if int(row["trades"]) >= minimum_trades_per_fold]
    if len(valid) < minimum_folds:
        aggregate = trade_stats(trades)
        return {
            "fitness": -float(fitness_weights["low_trade_penalty"]) * (minimum_folds - len(valid) + 1),
            "trades": aggregate["trades"],
            "per_fold": fold_rows,
            "aggregate": aggregate,
        }
    exp = [float(row["expectancy_bps"]) for row in valid if row["expectancy_bps"] is not None]
    wins = [float(row["win_rate"]) for row in valid if row["win_rate"] is not None]
    pfs = [_pf_number(row["profit_factor"]) for row in valid]
    pfs = [value for value in pfs if value is not None]
    dds = [abs(float(row["max_drawdown"] or 0.0)) for row in valid]
    positive_fraction = sum(value > 0 for value in exp) / len(exp) if exp else 0.0
    med_exp = float(median(exp)) if exp else -1e6
    med_win = float(median(wins)) if wins else 0.0
    med_pf = float(median(pfs)) if pfs else 0.0
    med_dd = float(median(dds)) if dds else 1.0
    w = fitness_weights
    fitness = (
        float(w["median_expectancy_bps"]) * med_exp
        + float(w["median_win_rate_above_half"]) * max(0.0, med_win - 0.5)
        + float(w["median_profit_factor_above_one"]) * max(0.0, med_pf - 1.0)
        + float(w["positive_fold_fraction"]) * positive_fraction
        - float(w["drawdown_penalty"]) * med_dd
    )
    aggregate = trade_stats(trades)
    return {
        "fitness": float(fitness),
        "trades": aggregate["trades"],
        "median_fold_expectancy_bps": med_exp,
        "median_fold_win_rate": med_win,
        "median_fold_profit_factor": med_pf,
        "positive_fold_fraction": positive_fraction,
        "median_fold_drawdown": med_dd,
        "per_fold": fold_rows,
        "aggregate": aggregate,
    }


def random_genome(rng: np.random.Generator, cfg: Mapping[str, Any], maximum_lookback: int) -> Genome:
    lookback = int(rng.choice(cfg["lookbacks"]))
    hold = int(rng.choice(cfg["holding_period_bars"]))
    lo, hi = map(float, cfg["entry_threshold_range"])
    return Genome(
        lookback=lookback,
        hold_bars=hold,
        threshold=float(rng.uniform(lo, hi)),
        bias=float(rng.normal(0.0, 0.2)),
        weights=rng.normal(0.0, 1.0, maximum_lookback * FEATURES_PER_BAR),
    )


def mutate(parent: Genome, rng: np.random.Generator, cfg: Mapping[str, Any], maximum_lookback: int) -> Genome:
    child = parent.clone()
    scale = float(cfg["mutation_scale"])
    child.weights += rng.normal(0.0, scale, child.weights.shape)
    child.bias += float(rng.normal(0.0, scale * 0.25))
    child.threshold = max(
        float(cfg["entry_threshold_range"][0]),
        min(float(cfg["entry_threshold_range"][1]), child.threshold * math.exp(float(rng.normal(0.0, scale * 0.20)))),
    )
    if rng.random() < 0.15:
        child.lookback = int(rng.choice(cfg["lookbacks"]))
    if rng.random() < 0.15:
        child.hold_bars = int(rng.choice(cfg["holding_period_bars"]))
    if rng.random() < 0.03:
        child.weights = rng.normal(0.0, 1.0, maximum_lookback * FEATURES_PER_BAR)
    return child


def evolve(frame: pd.DataFrame, cfg: Mapping[str, Any]) -> dict[str, Any]:
    maximum_lookback = int(cfg["maximum_lookback_bars"])
    ecfg = cfg["evolution"]
    rng = np.random.default_rng(int(ecfg["seed"]))
    population_size = int(ecfg["population"])
    population = [random_genome(rng, ecfg, maximum_lookback) for _ in range(population_size)]
    history: list[dict[str, Any]] = []
    best_genome: Genome | None = None
    best_eval: dict[str, Any] | None = None

    for generation in range(int(ecfg["generations"])):
        scored: list[tuple[float, Genome, dict[str, Any]]] = []
        for genome in population:
            evaluation = evaluate_genome(
                frame,
                genome,
                maximum_lookback=maximum_lookback,
                round_trip_cost_bps=float(ecfg["round_trip_cost_bps"]),
                fold_days=int(ecfg["fold_days"]),
                minimum_trades_per_fold=int(ecfg["minimum_trades_per_fold"]),
                minimum_folds=int(ecfg["minimum_folds"]),
                fitness_weights=ecfg["fitness_weights"],
            )
            scored.append((float(evaluation["fitness"]), genome, evaluation))
        scored.sort(key=lambda item: item[0], reverse=True)
        top_fit, top_genome, top_eval = scored[0]
        if best_eval is None or top_fit > float(best_eval["fitness"]):
            best_genome = top_genome.clone()
            best_eval = dict(top_eval)
        history.append(
            {
                "generation": generation,
                "best_fitness": top_fit,
                "median_population_fitness": float(np.median([row[0] for row in scored])),
                "best_median_fold_expectancy_bps": top_eval.get("median_fold_expectancy_bps"),
                "best_median_fold_win_rate": top_eval.get("median_fold_win_rate"),
                "best_median_fold_profit_factor": top_eval.get("median_fold_profit_factor"),
                "best_positive_fold_fraction": top_eval.get("positive_fold_fraction"),
                "best_trades": top_eval.get("trades"),
            }
        )
        elite_n = max(2, int(population_size * float(ecfg["elite_fraction"])))
        random_n = max(0, int(population_size * float(ecfg["random_survivor_fraction"])))
        survivors = [row[1].clone() for row in scored[:elite_n]]
        if random_n:
            pool = scored[elite_n:]
            if pool:
                indexes = rng.choice(len(pool), size=min(random_n, len(pool)), replace=False)
                survivors.extend(pool[int(i)][1].clone() for i in indexes)
        new_population = [g.clone() for g in survivors]
        while len(new_population) < population_size:
            parent = survivors[int(rng.integers(0, len(survivors)))]
            new_population.append(mutate(parent, rng, ecfg, maximum_lookback))
        population = new_population

    assert best_genome is not None and best_eval is not None
    return {
        "best_genome": {
            "lookback": best_genome.lookback,
            "hold_bars": best_genome.hold_bars,
            "threshold": best_genome.threshold,
            "bias": best_genome.bias,
            "weights": best_genome.weights.tolist(),
        },
        "best_discovery_evaluation": best_eval,
        "generation_history": history,
    }


def genome_from_dict(payload: Mapping[str, Any]) -> Genome:
    return Genome(
        lookback=int(payload["lookback"]),
        hold_bars=int(payload["hold_bars"]),
        threshold=float(payload["threshold"]),
        bias=float(payload["bias"]),
        weights=np.asarray(payload["weights"], dtype=float),
    )

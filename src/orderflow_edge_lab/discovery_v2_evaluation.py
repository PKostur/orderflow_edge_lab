from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import NormalDist
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class DiscoveryV2EvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class BootstrapResult:
    mean: float
    lower: float
    upper: float


def _finite(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise DiscoveryV2EvaluationError("no finite observations")
    return arr


def sharpe_unannualized(values: Sequence[float]) -> float:
    arr = _finite(values)
    if arr.size < 2:
        return float("nan")
    std = float(np.std(arr, ddof=1))
    if std == 0.0:
        if float(np.mean(arr)) > 0:
            return float("inf")
        if float(np.mean(arr)) < 0:
            return float("-inf")
        return 0.0
    return float(np.mean(arr) / std)


def moving_block_bootstrap_mean(
    values: Sequence[float],
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int = 17,
) -> BootstrapResult:
    arr = _finite(values)
    n = arr.size
    if n < 2:
        return BootstrapResult(float(np.mean(arr)), float(arr[0]), float(arr[0]))
    block = max(1, min(int(block_length), n))
    draws = int(resamples)
    if draws < 100:
        raise DiscoveryV2EvaluationError("resamples must be at least 100")
    rng = np.random.default_rng(seed)
    starts = np.arange(n)
    means = np.empty(draws, dtype=float)
    blocks_needed = int(math.ceil(n / block))
    for j in range(draws):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([arr[(start + np.arange(block)) % n] for start in chosen])[:n]
        means[j] = float(np.mean(sample))
    alpha = 1.0 - float(confidence)
    return BootstrapResult(
        mean=float(np.mean(arr)),
        lower=float(np.quantile(means, alpha / 2.0)),
        upper=float(np.quantile(means, 1.0 - alpha / 2.0)),
    )


def _sample_skew_kurtosis(values: np.ndarray) -> tuple[float, float]:
    n = len(values)
    if n < 4:
        return 0.0, 3.0
    mean = float(np.mean(values))
    centered = values - mean
    m2 = float(np.mean(centered**2))
    if m2 <= 0:
        return 0.0, 3.0
    m3 = float(np.mean(centered**3))
    m4 = float(np.mean(centered**4))
    return m3 / (m2**1.5), m4 / (m2**2)


def expected_max_sharpe(trial_sharpes: Sequence[float]) -> float:
    vals = _finite(trial_sharpes)
    n = vals.size
    if n <= 1:
        return float(vals[0])
    mu = float(np.mean(vals))
    sigma = float(np.std(vals, ddof=1))
    if sigma == 0:
        return mu
    gamma = 0.5772156649015329
    normal = NormalDist()
    a = normal.inv_cdf(1.0 - 1.0 / n)
    b = normal.inv_cdf(1.0 - 1.0 / (n * math.e))
    return float(mu + sigma * ((1.0 - gamma) * a + gamma * b))


def deflated_sharpe_probability(candidate_returns: Sequence[float], trial_sharpes: Sequence[float]) -> dict[str, float]:
    arr = _finite(candidate_returns)
    if arr.size < 3:
        return {"sharpe": float("nan"), "expected_max_sharpe": float("nan"), "probability": float("nan")}
    sr = sharpe_unannualized(arr)
    if not math.isfinite(sr):
        probability = 1.0 if sr > 0 else 0.0
        return {"sharpe": sr, "expected_max_sharpe": expected_max_sharpe(trial_sharpes), "probability": probability}
    sr_star = expected_max_sharpe(trial_sharpes)
    skew, kurt = _sample_skew_kurtosis(arr)
    denom_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr**2)
    if denom_sq <= 0:
        probability = float("nan")
    else:
        z = ((sr - sr_star) * math.sqrt(arr.size - 1.0)) / math.sqrt(denom_sq)
        probability = NormalDist().cdf(z)
    return {
        "sharpe": float(sr),
        "expected_max_sharpe": float(sr_star),
        "skew": float(skew),
        "kurtosis": float(kurt),
        "probability": float(probability),
    }


def _metric_mean_over_std(matrix: np.ndarray) -> np.ndarray:
    means = np.nanmean(matrix, axis=0)
    stds = np.nanstd(matrix, axis=0, ddof=1)
    out = np.divide(means, stds, out=np.full_like(means, -np.inf, dtype=float), where=stds > 0)
    zero_std_positive = (stds == 0) & (means > 0)
    out[zero_std_positive] = np.inf
    return out


def cscv_pbo(variant_returns: pd.DataFrame, *, partitions: int = 8) -> dict[str, Any]:
    clean = variant_returns.astype(float).replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="any")
    n_obs, n_variants = clean.shape
    s = int(partitions)
    if n_variants < 2 or n_obs < s or s < 4 or s % 2:
        raise DiscoveryV2EvaluationError("CSCV requires >=2 variants, even partitions >=4, and enough observations")
    blocks = np.array_split(np.arange(n_obs), s)
    from itertools import combinations

    logits: list[float] = []
    selected: list[int] = []
    oos_percentiles: list[float] = []
    array = clean.to_numpy(dtype=float)
    for train_blocks in combinations(range(s), s // 2):
        train_set = set(train_blocks)
        train_idx = np.concatenate([blocks[i] for i in range(s) if i in train_set])
        test_idx = np.concatenate([blocks[i] for i in range(s) if i not in train_set])
        train_metric = _metric_mean_over_std(array[train_idx])
        winner = int(np.nanargmax(train_metric))
        test_metric = _metric_mean_over_std(array[test_idx])
        # Percentile is the fraction of variants strictly worse plus half the ties.
        winner_score = test_metric[winner]
        worse = float(np.sum(test_metric < winner_score))
        ties = float(np.sum(test_metric == winner_score))
        omega = (worse + 0.5 * ties) / float(n_variants)
        eps = 1e-12
        omega = min(1.0 - eps, max(eps, omega))
        logits.append(math.log(omega / (1.0 - omega)))
        selected.append(winner)
        oos_percentiles.append(omega)
    pbo = float(np.mean(np.asarray(logits) <= 0.0))
    return {
        "pbo": pbo,
        "splits": len(logits),
        "median_logit": float(np.median(logits)),
        "median_oos_percentile": float(np.median(oos_percentiles)),
        "selection_counts": {str(clean.columns[i]): int(selected.count(i)) for i in sorted(set(selected))},
    }


def white_style_reality_check(
    variant_returns: pd.DataFrame,
    *,
    block_length: int = 5,
    resamples: int = 4000,
    seed: int = 29,
) -> dict[str, float]:
    clean = variant_returns.astype(float).replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="any")
    if clean.empty or clean.shape[1] < 1:
        raise DiscoveryV2EvaluationError("variant returns are empty")
    array = clean.to_numpy(dtype=float)
    n, _ = array.shape
    observed_means = np.mean(array, axis=0)
    observed_max = float(np.max(observed_means))
    centered = array - observed_means
    rng = np.random.default_rng(seed)
    block = max(1, min(int(block_length), n))
    blocks_needed = int(math.ceil(n / block))
    starts = np.arange(n)
    maxima = np.empty(int(resamples), dtype=float)
    for b in range(int(resamples)):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        idx = np.concatenate([(start + np.arange(block)) % n for start in chosen])[:n]
        maxima[b] = float(np.max(np.mean(centered[idx, :], axis=0)))
    p = float((1.0 + np.sum(maxima >= observed_max)) / (len(maxima) + 1.0))
    return {"observed_best_mean": observed_max, "bootstrap_p_value": p}


def cost_surface(gross_return_bps: Sequence[float], base_cost_bps: Sequence[float] | float, multipliers: Sequence[float]) -> dict[str, Any]:
    gross = _finite(gross_return_bps)
    if np.isscalar(base_cost_bps):
        costs = np.full(gross.size, float(base_cost_bps), dtype=float)
    else:
        costs = _finite(base_cost_bps)  # type: ignore[arg-type]
        if costs.size != gross.size:
            raise DiscoveryV2EvaluationError("cost vector length must match returns")
    rows = {}
    for multiplier in multipliers:
        net = gross - costs * float(multiplier)
        rows[str(float(multiplier))] = {
            "mean_net_bps": float(np.mean(net)),
            "median_net_bps": float(np.median(net)),
            "positive_fraction": float(np.mean(net > 0)),
        }
    base_mean_cost = float(np.mean(costs))
    break_even = float(np.mean(gross))
    return {
        "base_mean_cost_bps": base_mean_cost,
        "break_even_round_trip_cost_bps": break_even,
        "break_even_to_base_cost_ratio": break_even / base_mean_cost if base_mean_cost > 0 else float("inf"),
        "cases": rows,
    }


def _positive_share(grouped: pd.Series) -> float | None:
    positive = grouped[grouped > 0]
    total = float(positive.sum())
    if total <= 0 or positive.empty:
        return None
    return float(positive.max() / total)


def concentration_diagnostics(observations: pd.DataFrame, *, return_col: str = "net_return_bps") -> dict[str, Any]:
    required = {return_col, "symbol", "timestamp"}
    if not required.issubset(observations.columns):
        raise DiscoveryV2EvaluationError(f"missing concentration columns: {sorted(required - set(observations.columns))}")
    frame = observations.copy()
    frame[return_col] = pd.to_numeric(frame[return_col], errors="coerce")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.dropna(subset=[return_col, "symbol", "timestamp"])
    if frame.empty:
        raise DiscoveryV2EvaluationError("no usable observations")
    by_symbol = frame.groupby("symbol", observed=True)[return_col].sum().sort_values(ascending=False)
    by_month = frame.groupby(frame["timestamp"].dt.to_period("M"))[return_col].sum().sort_values(ascending=False)
    positives = frame.loc[frame[return_col] > 0, return_col].sort_values(ascending=False)
    positive_total = float(positives.sum())
    top5_share = float(positives.head(5).sum() / positive_total) if positive_total > 0 else None
    loo = {}
    symbols = sorted(frame["symbol"].astype(str).unique())
    for symbol in symbols:
        subset = frame.loc[frame["symbol"].astype(str) != symbol, return_col]
        loo[symbol] = float(subset.mean()) if not subset.empty else None
    side_stats = {}
    if "side" in frame.columns:
        for side, members in frame.groupby("side", observed=True):
            side_stats[str(side)] = {"count": int(len(members)), "mean_bps": float(members[return_col].mean()), "sum_bps": float(members[return_col].sum())}
    return {
        "best_symbol_positive_pnl_share": _positive_share(by_symbol),
        "best_calendar_month_positive_pnl_share": _positive_share(by_month),
        "top5_positive_pnl_share": top5_share,
        "per_symbol_sum_bps": {str(k): float(v) for k, v in by_symbol.items()},
        "per_month_sum_bps": {str(k): float(v) for k, v in by_month.items()},
        "leave_one_symbol_out_mean_bps": loo,
        "minimum_leave_one_symbol_out_mean_bps": min(v for v in loo.values() if v is not None) if loo else None,
        "side_stats": side_stats,
    }


def build_evidence_vector(
    observations: pd.DataFrame,
    *,
    trial_returns: pd.DataFrame | None,
    methodology: Mapping[str, Any],
    independence_level: str,
    validity_flags: Mapping[str, bool],
) -> dict[str, Any]:
    required = {"gross_return_bps", "cost_bps", "symbol", "timestamp"}
    if not required.issubset(observations.columns):
        raise DiscoveryV2EvaluationError(f"missing required observation columns: {sorted(required - set(observations.columns))}")
    frame = observations.copy()
    frame["gross_return_bps"] = pd.to_numeric(frame["gross_return_bps"], errors="coerce")
    frame["cost_bps"] = pd.to_numeric(frame["cost_bps"], errors="coerce")
    frame["net_return_bps"] = frame["gross_return_bps"] - frame["cost_bps"]
    frame = frame.dropna(subset=["net_return_bps"])
    if frame.empty:
        raise DiscoveryV2EvaluationError("no completed economic observations")

    stats_cfg = methodology["statistics"]
    econ_cfg = methodology["economics"]
    conc_cfg = methodology["concentration"]
    bootstrap = moving_block_bootstrap_mean(
        frame["net_return_bps"].to_numpy(),
        block_length=int(stats_cfg["block_bootstrap_length"]),
        resamples=int(stats_cfg["block_bootstrap_resamples"]),
        confidence=float(stats_cfg["confidence_level"]),
    )
    economics = cost_surface(
        frame["gross_return_bps"].to_numpy(),
        frame["cost_bps"].to_numpy(),
        econ_cfg["cost_multipliers"],
    )
    concentration = concentration_diagnostics(frame)

    statistical: dict[str, Any] = {
        "block_bootstrap_mean_bps": bootstrap.mean,
        "block_bootstrap_lower_bps": bootstrap.lower,
        "block_bootstrap_upper_bps": bootstrap.upper,
    }
    if trial_returns is not None and trial_returns.shape[1] >= int(stats_cfg["minimum_variants_for_pbo"]):
        trial_sharpes = [sharpe_unannualized(trial_returns[col].to_numpy()) for col in trial_returns]
        selected_col = trial_returns.mean().idxmax()
        statistical["deflated_sharpe"] = deflated_sharpe_probability(trial_returns[selected_col].to_numpy(), trial_sharpes)
        statistical["pbo_cscv"] = cscv_pbo(trial_returns, partitions=int(stats_cfg["cscv_partitions"]))
        statistical["reality_check"] = white_style_reality_check(
            trial_returns,
            block_length=int(stats_cfg["block_bootstrap_length"]),
            resamples=int(stats_cfg["block_bootstrap_resamples"]),
        )
        statistical["selected_variant_for_family_diagnostics"] = str(selected_col)
    else:
        statistical["family_selection_diagnostics_status"] = "insufficient_variant_family"

    validity_pass = bool(validity_flags) and all(bool(v) for v in validity_flags.values())
    economics_pass = bool(
        economics["cases"]["1.0"]["mean_net_bps"] > 0
        and economics["break_even_to_base_cost_ratio"] >= float(econ_cfg["minimum_break_even_to_base_cost_ratio"])
    )
    concentration_pass = True
    for key, threshold_key in (
        ("best_symbol_positive_pnl_share", "maximum_best_symbol_positive_pnl_share"),
        ("best_calendar_month_positive_pnl_share", "maximum_best_calendar_month_positive_pnl_share"),
        ("top5_positive_pnl_share", "maximum_top5_positive_pnl_share"),
    ):
        value = concentration[key]
        if value is not None and value > float(conc_cfg[threshold_key]):
            concentration_pass = False
    if bool(conc_cfg["leave_one_symbol_out_expectancy_must_remain_positive"]):
        min_loo = concentration["minimum_leave_one_symbol_out_mean_bps"]
        concentration_pass = concentration_pass and min_loo is not None and min_loo > 0

    statistical_pass: bool | None = None
    if "deflated_sharpe" in statistical:
        statistical_pass = bool(
            statistical["deflated_sharpe"]["probability"] >= float(stats_cfg["deflated_sharpe_min_probability"])
            and statistical["pbo_cscv"]["pbo"] <= float(stats_cfg["pbo_max"])
            and statistical["reality_check"]["bootstrap_p_value"] <= float(stats_cfg["reality_check_max_p"])
            and bootstrap.lower > 0
        )

    return {
        "observation_count": int(len(frame)),
        "independence_level": independence_level,
        "validity": {"flags": dict(validity_flags), "pass": validity_pass},
        "economics": {**economics, "pass": economics_pass},
        "statistical_robustness": {**statistical, "pass": statistical_pass},
        "concentration": {**concentration, "pass": concentration_pass},
        "execution_robustness": {"status": "requires_explicit_delay_fill_spread_stress_inputs", "pass": None},
        "independence": {"level": independence_level, "pass_for_live_review": independence_level == methodology["independence"]["minimum_for_live_review"]},
        "promotion": {
            "single_composite_score": None,
            "eligible": False,
            "reason": "Evidence vector only; lifecycle advancement requires all stage-specific mandatory dimensions and independent locked/prospective evidence.",
        },
        "claims": {
            "evaluation_output_alone_establishes_edge": False,
            "live_order_transmission_supported": False,
        },
    }

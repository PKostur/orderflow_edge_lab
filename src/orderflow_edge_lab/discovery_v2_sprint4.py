from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


class DiscoveryV2Sprint4Error(ValueError):
    pass


def _aligned_field(
    frames: Mapping[str, pd.DataFrame], symbols: Sequence[str], field: str, index: pd.DatetimeIndex
) -> pd.DataFrame:
    values = pd.concat(
        {s: pd.to_numeric(frames[s][field], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).sort_index()
    return values.reindex(index)


def _rank_min4(scores: pd.Series, *, long_high: bool) -> pd.Series:
    clean = pd.to_numeric(scores, errors="coerce").dropna().sort_values()
    out = pd.Series(0.0, index=scores.index, dtype=float)
    if len(clean) < 4:
        return out
    low, high = list(clean.index[:2]), list(clean.index[-2:])
    if long_high:
        out.loc[high] = 0.25
        out.loc[low] = -0.25
    else:
        out.loc[low] = 0.25
        out.loc[high] = -0.25
    return out


def volatility_compression_breakout(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    recent_vol_days: int,
    reference_vol_days: int,
    compression_ratio_threshold: float,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    returns = closes.pct_change()
    signals: list[tuple[int, int, pd.Series]] = []
    earliest = max(int(common_warmup_days), int(recent_vol_days) + int(reference_vol_days))

    for i in range(earliest, len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        recent = returns.iloc[i - int(recent_vol_days) + 1 : i + 1]
        reference = returns.iloc[
            i - int(recent_vol_days) - int(reference_vol_days) + 1 : i - int(recent_vol_days) + 1
        ]
        recent_vol = recent.std(axis=0, ddof=1)
        reference_vol = reference.std(axis=0, ddof=1).replace(0.0, np.nan)
        ratio = recent_vol / reference_vol
        active = ratio < float(compression_ratio_threshold)
        scores = returns.iloc[i].where(active)
        target = _rank_min4(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def liquidity_range_shock_reversal(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    range_baseline_days: int,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    highs = _aligned_field(daily_frames, symbols, "high", opens.index)
    lows = _aligned_field(daily_frames, symbols, "low", opens.index)
    prior_close = closes.shift(1)
    true_range = pd.DataFrame(
        np.maximum.reduce(
            [
                (highs - lows).to_numpy(dtype=float),
                (highs - prior_close).abs().to_numpy(dtype=float),
                (lows - prior_close).abs().to_numpy(dtype=float),
            ]
        ),
        index=opens.index,
        columns=opens.columns,
    )
    directional = closes / opens - 1.0
    signals: list[tuple[int, int, pd.Series]] = []

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        baseline = true_range.iloc[i - int(range_baseline_days) : i].median(axis=0).replace(0.0, np.nan)
        range_ratio = true_range.iloc[i] / baseline
        scores = (directional.iloc[i] * range_ratio).replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def _pair_target(
    ratio_scores: Mapping[tuple[str, str], float],
    *,
    symbols: Sequence[str],
    threshold: float,
    reverse: bool,
) -> pd.Series:
    active = [(pair, z) for pair, z in ratio_scores.items() if np.isfinite(z) and abs(float(z)) >= float(threshold)]
    target = pd.Series(0.0, index=list(symbols), dtype=float)
    if not active:
        return target
    pair_gross = 1.0 / len(active)
    leg = pair_gross / 2.0
    for (a, b), z in active:
        sign = 1.0 if float(z) > 0 else -1.0
        if reverse:
            sign *= -1.0
        # Mean-reversion direction: positive log(A/B) z => short A, long B.
        target.loc[a] += -sign * leg
        target.loc[b] += sign * leg
    gross = float(target.abs().sum())
    if gross > 0:
        target *= 1.0 / gross
    return target


def fixed_pair_relative_value_reversion(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    fixed_pairs: Sequence[Sequence[str]],
    ratio_lookback_days: int,
    entry_abs_z_threshold: float,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    symbol_set = set(symbols)
    pairs = [(str(p[0]), str(p[1])) for p in fixed_pairs]
    if len(set(pairs)) != len(pairs):
        raise DiscoveryV2Sprint4Error("duplicate fixed pair")
    if any(a not in symbol_set or b not in symbol_set or a == b for a, b in pairs):
        raise DiscoveryV2Sprint4Error("invalid fixed pair universe")

    log_close = np.log(closes)
    ratios = {(a, b): log_close[a] - log_close[b] for a, b in pairs}
    signals: list[tuple[int, int, pd.Series]] = []

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        scores: dict[tuple[str, str], float] = {}
        for pair, series in ratios.items():
            prior = pd.to_numeric(series.iloc[i - int(ratio_lookback_days) : i], errors="coerce").dropna()
            current = float(series.iloc[i])
            if len(prior) != int(ratio_lookback_days) or not np.isfinite(current):
                scores[pair] = float("nan")
                continue
            sd = float(prior.std(ddof=1))
            scores[pair] = (current - float(prior.mean())) / sd if sd > 0 else 0.0
        target = _pair_target(
            scores,
            symbols=symbols,
            threshold=float(entry_abs_z_threshold),
            reverse=bool(reverse),
        ).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def evaluate_sprint4_family(
    variants: Mapping[str, VariantRun],
    controls: Mapping[str, VariantRun],
    *,
    ordered_variant_ids: Sequence[str],
    evaluation_config: Mapping[str, Any],
    principal_control_for_variant: Mapping[str, str],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    out = evaluate_sprint2_family(
        variants,
        controls,
        ordered_variant_ids=ordered_variant_ids,
        evaluation_config=evaluation_config,
        principal_control_for_variant=principal_control_for_variant,
        gate=gate,
    )
    out["sprint4_selected_variant"] = out.pop("sprint2_selected_variant", None)
    out["sprint4_selected_control"] = out.pop("sprint2_selected_control", None)
    out["sprint4_selected_advantage_bps"] = out.pop("sprint2_selected_advantage_bps", None)
    out["sprint4_hard_checks"] = out.pop("sprint2_hard_checks", {})
    return out

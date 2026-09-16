from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


class DiscoveryV2Sprint5Error(ValueError):
    pass


def _aligned_field(
    frames: Mapping[str, pd.DataFrame], symbols: Sequence[str], field: str, index: pd.DatetimeIndex
) -> pd.DataFrame:
    return pd.concat(
        {s: pd.to_numeric(frames[s][field], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).sort_index().reindex(index)


def donchian_channel_position_continuation(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    channel_lookback_days: int,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    highs = _aligned_field(daily_frames, symbols, "high", opens.index)
    lows = _aligned_field(daily_frames, symbols, "low", opens.index)
    signals: list[tuple[int, int, pd.Series]] = []

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        prior_high = highs.iloc[i - int(channel_lookback_days) : i].max(axis=0)
        prior_low = lows.iloc[i - int(channel_lookback_days) : i].min(axis=0)
        width = (prior_high - prior_low).replace(0.0, np.nan)
        scores = 2.0 * (closes.iloc[i] - prior_low) / width - 1.0
        scores = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def amihud_liquidity_premium(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    lookback_days: int,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    volumes = _aligned_field(daily_frames, symbols, "volume", opens.index)
    returns = closes.pct_change().abs()
    dollar_volume = (closes * volumes).where((closes * volumes) > 0)
    daily_illiquidity = returns / dollar_volume
    signals: list[tuple[int, int, pd.Series]] = []

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        recent = daily_illiquidity.iloc[i - int(lookback_days) + 1 : i + 1]
        scores = recent.mean(axis=0).replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        # Hypothesis: liquid symbols outperform illiquid symbols.
        target = _rank(scores, long_high=bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def close_location_pressure(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    lookback_days: int,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    highs = _aligned_field(daily_frames, symbols, "high", opens.index)
    lows = _aligned_field(daily_frames, symbols, "low", opens.index)
    width = (highs - lows).replace(0.0, np.nan)
    clv = (2.0 * closes - highs - lows) / width
    signals: list[tuple[int, int, pd.Series]] = []

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        scores = clv.iloc[i - int(lookback_days) + 1 : i + 1].mean(axis=0)
        scores = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def evaluate_sprint5_family(
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
    out["sprint5_selected_variant"] = out.pop("sprint2_selected_variant", None)
    out["sprint5_selected_control"] = out.pop("sprint2_selected_control", None)
    out["sprint5_selected_advantage_bps"] = out.pop("sprint2_selected_advantage_bps", None)
    out["sprint5_hard_checks"] = out.pop("sprint2_hard_checks", {})
    return out

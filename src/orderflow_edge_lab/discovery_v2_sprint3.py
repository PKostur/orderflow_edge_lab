from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import (
    _rank,
    _sample_skew,
    _simulate_signals,
    evaluate_sprint2_family,
)


class DiscoveryV2Sprint3Error(ValueError):
    pass


def btc_downtrend_intraday_skewness(
    daily_frames: Mapping[str, pd.DataFrame],
    four_hour_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    lookback_days: int,
    common_warmup_days: int,
    btc_trend_lookback_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    if "BTC_USDT" not in symbols:
        raise DiscoveryV2Sprint3Error("BTC_USDT is required for the trend gate")
    opens, closes = _validate_price_frames(daily_frames, symbols)
    four_closes = pd.concat(
        {s: pd.to_numeric(four_hour_frames[s]["close"], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).dropna().sort_index()
    log_returns = np.log(four_closes).diff()
    signals: list[tuple[int, int, pd.Series]] = []
    warmup = max(int(common_warmup_days), int(btc_trend_lookback_days))

    for i in range(warmup, len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        boundary = opens.index[start_i]
        prior_btc_trend = float(
            np.log(float(closes["BTC_USDT"].iloc[i]) / float(closes["BTC_USDT"].iloc[i - int(btc_trend_lookback_days)]))
        )
        if not np.isfinite(prior_btc_trend):
            continue
        if prior_btc_trend >= 0:
            target = pd.Series(0.0, index=opens.columns, dtype=float)
        else:
            available_at = log_returns.index + pd.Timedelta(hours=4)
            recent = log_returns.loc[
                (available_at <= boundary)
                & (available_at > boundary - pd.Timedelta(days=int(lookback_days)))
            ]
            if len(recent) < 3:
                continue
            scores = recent.apply(lambda s: _sample_skew(s.to_numpy(dtype=float)), axis=0)
            target = _rank(scores, long_high=bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def funding_carry_spread(
    daily_frames: Mapping[str, pd.DataFrame],
    funding_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    lookback_days: int,
    common_warmup_days: int,
    minimum_settlements_per_day: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, _ = _validate_price_frames(daily_frames, symbols)
    signals: list[tuple[int, int, pd.Series]] = []
    min_events = int(lookback_days) * int(minimum_settlements_per_day)

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        boundary = opens.index[start_i]
        lower = boundary - pd.Timedelta(days=int(lookback_days))
        scores = pd.Series(index=list(symbols), dtype=float)
        for symbol in symbols:
            frame = funding_frames[symbol]
            if "funding_rate" not in frame.columns:
                scores[symbol] = np.nan
                continue
            values = pd.to_numeric(
                frame.loc[(frame.index < boundary) & (frame.index >= lower), "funding_rate"],
                errors="coerce",
            ).dropna()
            scores[symbol] = float(values.mean()) if len(values) >= min_events else np.nan
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def volume_confirmed_momentum(
    daily_frames: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    funding_frames: Mapping[str, pd.DataFrame] | None,
    volume_baseline_days: int,
    common_warmup_days: int,
    side_cost_bps: float,
    reverse: bool = False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    volumes = pd.concat(
        {s: pd.to_numeric(daily_frames[s]["volume"], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).reindex(opens.index)
    returns = closes.pct_change()
    signals: list[tuple[int, int, pd.Series]] = []

    for i in range(int(common_warmup_days), len(opens) - 2):
        start_i, end_i = i + 1, i + 2
        prior_volume = volumes.iloc[i - int(volume_baseline_days):i]
        baseline = prior_volume.median(axis=0).replace(0.0, np.nan)
        volume_ratio = volumes.iloc[i] / baseline
        scores = returns.iloc[i] * volume_ratio
        scores = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((start_i, end_i, target))

    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def evaluate_sprint3_family(
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
    out["sprint3_selected_variant"] = out.pop("sprint2_selected_variant", None)
    out["sprint3_selected_control"] = out.pop("sprint2_selected_control", None)
    out["sprint3_selected_advantage_bps"] = out.pop("sprint2_selected_advantage_bps", None)
    out["sprint3_hard_checks"] = out.pop("sprint2_hard_checks", {})
    return out

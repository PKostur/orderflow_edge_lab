from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


def vol_adjusted_short_term_reversal(
    daily_frames,
    *,
    symbols,
    funding_frames,
    volatility_lookback_days,
    common_warmup_days,
    side_cost_bps,
    reverse=False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    signals = []
    n = int(volatility_lookback_days)
    for i in range(int(common_warmup_days), len(opens) - 2):
        prior_vol = ret.iloc[i - n:i].std(axis=0, ddof=1).replace(0.0, np.nan)
        scores = (-ret.iloc[i] / prior_vol).replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def momentum_acceleration(
    daily_frames,
    *,
    symbols,
    funding_frames,
    window_days,
    common_warmup_days,
    side_cost_bps,
    reverse=False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    signals = []
    n = int(window_days)
    for i in range(int(common_warmup_days), len(opens) - 2):
        recent = ret.iloc[i - n + 1:i + 1].sum(axis=0, min_count=n)
        previous = ret.iloc[i - 2 * n + 1:i - n + 1].sum(axis=0, min_count=n)
        scores = (recent - previous).replace([np.inf, -np.inf], np.nan)
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def _ols_slope(x: pd.Series, y: pd.Series) -> float:
    pair = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(pair) < 2:
        return float("nan")
    xv = pair.iloc[:, 0].to_numpy(float)
    yv = pair.iloc[:, 1].to_numpy(float)
    centered = xv - xv.mean()
    denom = float(np.dot(centered, centered))
    if denom <= 0.0:
        return float("nan")
    return float(np.dot(centered, yv - yv.mean()) / denom)


def upside_downside_beta_asymmetry(
    daily_frames,
    *,
    symbols,
    alt_symbols,
    funding_frames,
    lookback_days,
    common_warmup_days,
    minimum_subset_observations,
    side_cost_bps,
    reverse=False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    btc = "BTC_USDT"
    if btc not in ret.columns:
        raise ValueError("BTC_USDT factor is required")
    signals = []
    n = int(lookback_days)
    min_obs = int(minimum_subset_observations)
    alt_symbols = [s for s in alt_symbols if s in ret.columns and s != btc]
    for i in range(int(common_warmup_days), len(opens) - 2):
        window = ret.iloc[i - n + 1:i + 1]
        x = window[btc]
        up_mask = x > 0.0
        down_mask = x < 0.0
        scores = pd.Series(np.nan, index=alt_symbols, dtype=float)
        if int(up_mask.sum()) >= min_obs and int(down_mask.sum()) >= min_obs:
            for symbol in alt_symbols:
                beta_up = _ols_slope(x.loc[up_mask], window.loc[up_mask, symbol])
                beta_down = _ols_slope(x.loc[down_mask], window.loc[down_mask, symbol])
                if np.isfinite(beta_up) and np.isfinite(beta_down):
                    scores.loc[symbol] = beta_up - beta_down
        if scores.notna().sum() < 6:
            continue
        target_alt = _rank(scores, long_high=not bool(reverse))
        target = pd.Series(0.0, index=opens.columns, dtype=float)
        target.loc[target_alt.index] = target_alt
        target.loc[btc] = 0.0
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def evaluate_sprint7_family(
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
    out["sprint7_selected_variant"] = out.pop("sprint2_selected_variant", None)
    out["sprint7_selected_control"] = out.pop("sprint2_selected_control", None)
    out["sprint7_selected_advantage_bps"] = out.pop("sprint2_selected_advantage_bps", None)
    out["sprint7_hard_checks"] = out.pop("sprint2_hard_checks", {})
    return out

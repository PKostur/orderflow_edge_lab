from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


def _ols_slope_intercept(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    xv = np.asarray(x, dtype=float)
    yv = np.asarray(y, dtype=float)
    if len(xv) != len(yv) or len(xv) < 2 or not np.isfinite(xv).all() or not np.isfinite(yv).all():
        return float("nan"), float("nan")
    xmat = np.column_stack([np.ones(len(xv)), xv])
    coef, *_ = np.linalg.lstsq(xmat, yv, rcond=None)
    return float(coef[0]), float(coef[1])


def cross_sectional_funding_carry(
    daily_frames,
    *,
    symbols,
    funding_frames,
    lookback_calendar_days,
    common_warmup_days,
    side_cost_bps,
    reverse=False,
) -> VariantRun:
    opens, _ = _validate_price_frames(daily_frames, symbols)
    n = int(lookback_calendar_days)
    signals = []
    for i in range(int(common_warmup_days), len(opens) - 2):
        execution_ts = opens.index[i + 1]
        lower = execution_ts - pd.Timedelta(days=n)
        scores = pd.Series(np.nan, index=opens.columns, dtype=float)
        for symbol in opens.columns:
            frame = funding_frames.get(symbol)
            if frame is None or frame.empty or "funding_rate" not in frame.columns:
                continue
            rates = pd.to_numeric(frame["funding_rate"], errors="coerce").dropna()
            recent = rates.loc[(rates.index >= lower) & (rates.index < execution_ts)]
            if recent.empty:
                continue
            daily_burden = float(recent.sum()) / float(n)
            scores.loc[symbol] = -daily_burden
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def adaptive_ar1_forecast(
    daily_frames,
    *,
    symbols,
    funding_frames,
    lookback_pairs,
    common_warmup_days,
    side_cost_bps,
    reverse=False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    n = int(lookback_pairs)
    signals = []
    for i in range(int(common_warmup_days), len(opens) - 2):
        scores = pd.Series(np.nan, index=opens.columns, dtype=float)
        for symbol in opens.columns:
            values = pd.to_numeric(ret[symbol].iloc[i - n:i + 1], errors="coerce").to_numpy(float)
            if len(values) != n + 1 or not np.isfinite(values).all():
                continue
            alpha, phi = _ols_slope_intercept(values[:-1], values[1:])
            if np.isfinite(alpha) and np.isfinite(phi):
                scores.loc[symbol] = alpha + phi * float(values[-1])
        if scores.notna().sum() < 6:
            continue
        target = _rank(scores, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def cross_sectional_low_btc_beta(
    daily_frames,
    *,
    symbols,
    alt_symbols,
    funding_frames,
    lookback_days,
    common_warmup_days,
    side_cost_bps,
    reverse=False,
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    btc = "BTC_USDT"
    if btc not in ret.columns:
        raise ValueError("BTC_USDT factor required")
    alts = [s for s in alt_symbols if s in ret.columns and s != btc]
    n = int(lookback_days)
    signals = []
    for i in range(int(common_warmup_days), len(opens) - 2):
        x = pd.to_numeric(ret[btc].iloc[i - n + 1:i + 1], errors="coerce").to_numpy(float)
        scores = pd.Series(np.nan, index=alts, dtype=float)
        if len(x) == n and np.isfinite(x).all():
            for symbol in alts:
                y = pd.to_numeric(ret[symbol].iloc[i - n + 1:i + 1], errors="coerce").to_numpy(float)
                alpha, beta = _ols_slope_intercept(x, y)
                if np.isfinite(alpha) and np.isfinite(beta):
                    scores.loc[symbol] = -beta
        if scores.notna().sum() < 6:
            continue
        alt_target = _rank(scores, long_high=not bool(reverse))
        target = pd.Series(0.0, index=opens.columns, dtype=float)
        target.loc[alt_target.index] = alt_target
        target.loc[btc] = 0.0
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def evaluate_sprint9_family(
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
    out["sprint9_selected_variant"] = out.pop("sprint2_selected_variant", None)
    out["sprint9_selected_control"] = out.pop("sprint2_selected_control", None)
    out["sprint9_selected_advantage_bps"] = out.pop("sprint2_selected_advantage_bps", None)
    out["sprint9_hard_checks"] = out.pop("sprint2_hard_checks", {})
    return out

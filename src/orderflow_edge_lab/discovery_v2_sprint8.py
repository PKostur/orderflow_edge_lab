from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, _validate_price_frames
from orderflow_edge_lab.discovery_v2_sprint2 import _rank, _simulate_signals, evaluate_sprint2_family


def _field(frames: Mapping[str, pd.DataFrame], symbols: Sequence[str], name: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.concat(
        {s: pd.to_numeric(frames[s][name], errors="coerce") for s in symbols},
        axis=1,
        join="inner",
    ).sort_index().reindex(idx)


def _wilder_adx(frame: pd.DataFrame, period: int) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    alpha = 1.0 / float(period)
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_smoothed = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_smoothed = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_smoothed / atr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_smoothed / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def build_frozen_regimes(
    btc_frame: pd.DataFrame,
    *,
    rv_window_days: int = 20,
    annualization_days: int = 365,
    threshold_history_observations: int = 60,
    adx_period_days: int = 14,
    trend_threshold: float = 25.0,
) -> pd.Series:
    btc = btc_frame.sort_index().copy()
    close = pd.to_numeric(btc["close"], errors="coerce")
    logret = np.log(close).diff()
    rv = logret.rolling(int(rv_window_days), min_periods=int(rv_window_days)).std(ddof=1) * np.sqrt(float(annualization_days))
    rv_threshold = rv.shift(1).rolling(
        int(threshold_history_observations), min_periods=int(threshold_history_observations)
    ).median()
    adx = _wilder_adx(btc, int(adx_period_days))
    features = pd.DataFrame(
        {
            "rv20": rv.shift(1),
            "rv_threshold": rv_threshold.shift(1),
            "adx14": adx.shift(1),
        },
        index=btc.index,
    )
    valid = features.notna().all(axis=1)
    high_vol = features["rv20"] > features["rv_threshold"]
    trend = features["adx14"] >= float(trend_threshold)
    regime = pd.Series(
        np.where(
            high_vol & trend,
            "HIGH_VOL_TREND",
            np.where(
                high_vol & ~trend,
                "HIGH_VOL_RANGE",
                np.where(~high_vol & trend, "LOW_VOL_TREND", "LOW_VOL_RANGE"),
            ),
        ),
        index=btc.index,
        dtype="object",
    )
    regime.loc[~valid] = None
    return regime


def _zero(columns: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=columns, dtype=float)


def _gate_target(
    base_target: pd.Series,
    *,
    regime: str | None,
    active_regimes: set[str],
    mode: str,
    columns: pd.Index,
) -> pd.Series:
    if regime is None:
        return _zero(columns)
    active = regime in active_regimes
    if mode == "hypothesis":
        return base_target.reindex(columns, fill_value=0.0) if active else _zero(columns)
    if mode == "complement":
        return _zero(columns) if active else base_target.reindex(columns, fill_value=0.0)
    raise ValueError(f"unsupported gate mode: {mode}")


def trend_gated_momentum_acceleration(
    daily_frames,
    *,
    symbols,
    funding_frames,
    window_days,
    common_warmup_days,
    side_cost_bps,
    active_regimes=("HIGH_VOL_TREND", "LOW_VOL_TREND"),
    reverse=False,
    gate_mode="hypothesis",
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    regimes = build_frozen_regimes(daily_frames["BTC_USDT"]).reindex(opens.index)
    n = int(window_days)
    active_set = set(active_regimes)
    signals = []
    for i in range(int(common_warmup_days), len(opens) - 2):
        recent = ret.iloc[i - n + 1:i + 1].sum(axis=0, min_count=n)
        previous = ret.iloc[i - 2 * n + 1:i - n + 1].sum(axis=0, min_count=n)
        score = (recent - previous).replace([np.inf, -np.inf], np.nan)
        if score.notna().sum() < 6:
            base = _zero(opens.columns)
        else:
            base = _rank(score, long_high=not bool(reverse)).reindex(opens.columns, fill_value=0.0)
        execution_ts = opens.index[i + 1]
        regime = regimes.get(execution_ts)
        target = _gate_target(
            base,
            regime=None if pd.isna(regime) else str(regime),
            active_regimes=active_set,
            mode=gate_mode,
            columns=opens.columns,
        )
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


def low_vol_range_beta_asymmetry(
    daily_frames,
    *,
    symbols,
    alt_symbols,
    funding_frames,
    lookback_days,
    common_warmup_days,
    minimum_subset_observations,
    side_cost_bps,
    active_regimes=("LOW_VOL_RANGE",),
    reverse=False,
    gate_mode="hypothesis",
) -> VariantRun:
    opens, closes = _validate_price_frames(daily_frames, symbols)
    ret = closes.pct_change()
    regimes = build_frozen_regimes(daily_frames["BTC_USDT"]).reindex(opens.index)
    btc = "BTC_USDT"
    alts = [s for s in alt_symbols if s in ret.columns and s != btc]
    n = int(lookback_days)
    min_obs = int(minimum_subset_observations)
    active_set = set(active_regimes)
    signals = []
    for i in range(int(common_warmup_days), len(opens) - 2):
        window = ret.iloc[i - n + 1:i + 1]
        x = window[btc]
        up_mask = x > 0.0
        down_mask = x < 0.0
        scores = pd.Series(np.nan, index=alts, dtype=float)
        if int(up_mask.sum()) >= min_obs and int(down_mask.sum()) >= min_obs:
            for symbol in alts:
                up_beta = _ols_slope(x.loc[up_mask], window.loc[up_mask, symbol])
                down_beta = _ols_slope(x.loc[down_mask], window.loc[down_mask, symbol])
                if np.isfinite(up_beta) and np.isfinite(down_beta):
                    scores.loc[symbol] = up_beta - down_beta
        if scores.notna().sum() >= 6:
            alt_target = _rank(scores, long_high=not bool(reverse))
            base = _zero(opens.columns)
            base.loc[alt_target.index] = alt_target
            base.loc[btc] = 0.0
        else:
            base = _zero(opens.columns)
        execution_ts = opens.index[i + 1]
        regime = regimes.get(execution_ts)
        target = _gate_target(
            base,
            regime=None if pd.isna(regime) else str(regime),
            active_regimes=active_set,
            mode=gate_mode,
            columns=opens.columns,
        )
        target.loc[btc] = 0.0
        signals.append((i + 1, i + 2, target))
    return _simulate_signals(signals, opens, funding_frames, side_cost_bps=side_cost_bps)


def evaluate_sprint8_family(
    variants: Mapping[str, VariantRun],
    controls: Mapping[str, VariantRun],
    *,
    ordered_variant_ids: Sequence[str],
    evaluation_config: Mapping[str, Any],
    reversed_control_for_variant: Mapping[str, str],
    complement_control_for_variant: Mapping[str, str],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    out = evaluate_sprint2_family(
        variants,
        controls,
        ordered_variant_ids=ordered_variant_ids,
        evaluation_config=evaluation_config,
        principal_control_for_variant=reversed_control_for_variant,
        gate=gate,
    )
    selected = out.get("sprint2_selected_variant")
    complement_id = complement_control_for_variant.get(selected) if selected else None
    complement = out.get("control_summaries", {}).get(complement_id) if complement_id else None
    candidate = out.get("variant_summaries", {}).get(selected) if selected else None
    advantage = None
    complement_pass = False
    if candidate is not None and complement is not None:
        advantage = float(candidate["mean_net_bps"] - complement["mean_net_bps"])
        complement_pass = advantage >= float(gate["minimum_candidate_minus_complement_regime_control_mean_bps"])
    previous_state = out.get("state")
    if previous_state == "REPLICATION_PENDING" and not complement_pass:
        out["state"] = "FALSIFIED"
        out["sprint2_selected_variant"] = None
    out["sprint8_pre_complement_state"] = previous_state
    out["sprint8_selected_variant"] = selected if previous_state == "REPLICATION_PENDING" and complement_pass else None
    out["sprint8_selected_complement_control"] = complement_id
    out["sprint8_selected_complement_advantage_bps"] = advantage
    out["sprint8_selected_beats_complement_by_5bps"] = complement_pass
    out["claims"] = {
        "d0_post_diagnostic_result_establishes_edge": False,
        "same_period_regime_result_is_validation": False,
        "live_eligible": False,
    }
    return out

from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class CrossMarketRegimeAtlasError(ValueError):
    pass


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _validate_frame(frame: pd.DataFrame, instrument: str) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise CrossMarketRegimeAtlasError(f"{instrument}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise CrossMarketRegimeAtlasError(f"{instrument}: duplicate timestamps")
    required = {"open", "high", "low", "close"}
    missing = required - set(out.columns)
    if missing:
        raise CrossMarketRegimeAtlasError(f"{instrument}: missing OHLC columns: {sorted(missing)}")
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    values = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise CrossMarketRegimeAtlasError(f"{instrument}: invalid OHLC values")
    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    if len(out) < 100:
        raise CrossMarketRegimeAtlasError(f"{instrument}: insufficient bars")
    return out


def _causal_tercile(
    values: pd.Series,
    *,
    history_bars: int,
    minimum_history: int,
    labels: tuple[str, str, str],
) -> pd.Series:
    if history_bars <= 0 or minimum_history <= 0 or minimum_history > history_bars:
        raise CrossMarketRegimeAtlasError("invalid causal rank history settings")
    out = pd.Series("UNKNOWN", index=values.index, dtype="object")
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    for i in range(len(numeric)):
        current = _finite(numeric.iloc[i])
        if current is None:
            continue
        prior = numeric.iloc[max(0, i - history_bars):i]
        prior = prior[np.isfinite(prior.to_numpy(dtype=float))]
        if len(prior) < minimum_history:
            continue
        q1, q2 = np.quantile(prior.to_numpy(dtype=float), [1.0 / 3.0, 2.0 / 3.0])
        if current <= q1:
            out.iloc[i] = labels[0]
        elif current <= q2:
            out.iloc[i] = labels[1]
        else:
            out.iloc[i] = labels[2]
    return out


def _utc_time_block(index: pd.DatetimeIndex) -> pd.Series:
    labels = np.where(
        index.hour < 8,
        "00-08",
        np.where(index.hour < 16, "08-16", "16-24"),
    )
    return pd.Series(labels, index=index, dtype="object")


def _btc_correlation_bucket(value: Any) -> str:
    rho = _finite(value)
    if rho is None:
        return "UNKNOWN"
    if rho <= -0.65:
        return "HIGH_NEGATIVE"
    if rho <= -0.25:
        return "MODERATE_NEGATIVE"
    if rho < 0.25:
        return "LOW_ABS"
    if rho < 0.65:
        return "MODERATE_POSITIVE"
    return "HIGH_POSITIVE"


def _direction_state(displacement: pd.Series, flat_tolerance_bps: float) -> pd.Series:
    bps = pd.to_numeric(displacement, errors="coerce") * 10_000.0
    out = pd.Series("FLAT", index=displacement.index, dtype="object")
    out.loc[bps > flat_tolerance_bps] = "UP"
    out.loc[bps < -flat_tolerance_bps] = "DOWN"
    out.loc[~np.isfinite(bps.to_numpy(dtype=float))] = "FLAT"
    return out


def _future_outcomes(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    if horizon <= 0:
        raise CrossMarketRegimeAtlasError("future horizon must be positive")
    close = frame["close"].astype(float)
    ret = (close.shift(-horizon) / close - 1.0) * 10_000.0
    ranges: list[float | None] = []
    for i in range(len(frame)):
        if i + horizon >= len(frame):
            ranges.append(None)
            continue
        future = frame.iloc[i + 1:i + horizon + 1]
        low = float(future["low"].min())
        high = float(future["high"].max())
        ranges.append((high / low - 1.0) * 10_000.0 if low > 0 else None)
    return pd.DataFrame(
        {
            "future_return_bps": ret,
            "future_abs_return_bps": ret.abs(),
            "future_high_low_range_bps": ranges,
        },
        index=frame.index,
    )


def build_instrument_state_frame(
    frame: pd.DataFrame,
    config: Mapping[str, Any],
    *,
    instrument: str,
    context_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    out = _validate_frame(frame, instrument)
    defs = config["state_definitions"]

    close = out["close"].astype(float)
    simple_returns = close.pct_change()
    log_returns = np.log(close).diff()

    trend_cfg = defs["trend_efficiency"]
    trend_lookback = int(trend_cfg["lookback_bars"])
    path = simple_returns.abs().rolling(trend_lookback, min_periods=trend_lookback).sum()
    trend_efficiency = close.pct_change(trend_lookback).abs() / path.replace(0.0, np.nan)
    trend_state = _causal_tercile(
        trend_efficiency,
        history_bars=int(trend_cfg["rank_history_bars"]),
        minimum_history=int(trend_cfg["minimum_rank_history"]),
        labels=("RANGE", "MIXED", "TREND"),
    )

    vol_cfg = defs["realized_volatility"]
    vol_lookback = int(vol_cfg["lookback_bars"])
    realized_vol = log_returns.rolling(vol_lookback, min_periods=vol_lookback).std(ddof=0)
    volatility_state = _causal_tercile(
        realized_vol,
        history_bars=int(vol_cfg["rank_history_bars"]),
        minimum_history=int(vol_cfg["minimum_rank_history"]),
        labels=("LOW", "MID", "HIGH"),
    )

    displacement_cfg = defs["displacement"]
    displacement = close.pct_change(int(displacement_cfg["lookback_bars"]))
    displacement_state = _causal_tercile(
        displacement,
        history_bars=int(displacement_cfg["rank_history_bars"]),
        minimum_history=int(displacement_cfg["minimum_rank_history"]),
        labels=("DOWN", "NEUTRAL", "UP"),
    )

    activity_cfg = defs["activity"]
    if "volume" in out.columns:
        volume = pd.to_numeric(out["volume"], errors="coerce").astype(float)
        volume = volume.where(volume >= 0.0)
        activity_state = _causal_tercile(
            volume,
            history_bars=int(activity_cfg["rank_history_bars"]),
            minimum_history=int(activity_cfg["minimum_rank_history"]),
            labels=("LOW", "MID", "HIGH"),
        )
    else:
        volume = pd.Series(np.nan, index=out.index, dtype=float)
        activity_state = pd.Series("UNKNOWN", index=out.index, dtype="object")

    corr_cfg = defs["btc_correlation"]
    btc_corr = pd.Series(np.nan, index=out.index, dtype=float)
    if context_frame is not None:
        context = _validate_frame(context_frame, str(config["development_data"]["context_symbol"]))
        aligned = pd.concat(
            [
                simple_returns.rename("asset"),
                context["close"].astype(float).pct_change().rename("context"),
            ],
            axis=1,
            join="inner",
        )
        rolling_corr = aligned["asset"].rolling(
            int(corr_cfg["lookback_bars"]),
            min_periods=int(corr_cfg["minimum_observations"]),
        ).corr(aligned["context"])
        btc_corr.loc[rolling_corr.index.intersection(btc_corr.index)] = rolling_corr.reindex(
            btc_corr.index.intersection(rolling_corr.index)
        )
    btc_correlation_state = btc_corr.map(_btc_correlation_bucket)

    direction_state = _direction_state(
        displacement,
        float(defs["direction"]["flat_tolerance_bps"]),
    )

    state = pd.DataFrame(index=out.index)
    state["trend_efficiency"] = trend_efficiency
    state["trend_state"] = trend_state
    state["realized_volatility"] = realized_vol
    state["volatility_state"] = volatility_state
    state["displacement_return"] = displacement
    state["displacement_state"] = displacement_state
    state["volume"] = volume
    state["activity_state"] = activity_state
    state["btc_correlation"] = btc_corr
    state["btc_correlation_state"] = btc_correlation_state
    state["utc_time_block"] = _utc_time_block(out.index)
    state["direction_state"] = direction_state
    state["liquidity_efficiency_state"] = "UNKNOWN"
    return state


def _direction_match(direction: str, future_return_bps: float) -> bool | None:
    if direction == "UP":
        return future_return_bps > 0.0
    if direction == "DOWN":
        return future_return_bps < 0.0
    return None


def build_atlas_observations(
    frames: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    symbols = [str(value) for value in config["development_data"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise CrossMarketRegimeAtlasError(f"missing frames: {missing}")
    context_symbol = str(config["development_data"]["context_symbol"])
    context = frames.get(context_symbol)
    if context is None:
        raise CrossMarketRegimeAtlasError("context frame missing")

    horizons = [int(value) for value in config["raw_future_outcomes"]["horizons_bars"]]
    rows: list[dict[str, Any]] = []
    for instrument in symbols:
        frame = _validate_frame(frames[instrument], instrument)
        state = build_instrument_state_frame(
            frame,
            config,
            instrument=instrument,
            context_frame=context,
        )
        for horizon in horizons:
            future = _future_outcomes(frame, horizon)
            joined = state.join(future)
            for ts, row in joined.iterrows():
                future_return = _finite(row.get("future_return_bps"))
                future_abs = _finite(row.get("future_abs_return_bps"))
                future_range = _finite(row.get("future_high_low_range_bps"))
                if future_return is None or future_abs is None or future_range is None:
                    continue
                direction = str(row["direction_state"])
                rows.append(
                    {
                        "market": str(config["development_data"]["market"]),
                        "venue": str(config["development_data"]["venue"]),
                        "instrument": instrument,
                        "interval": str(config["development_data"]["interval"]),
                        "timestamp_utc": pd.Timestamp(ts).isoformat(),
                        "horizon_bars": horizon,
                        "utc_time_block": str(row["utc_time_block"]),
                        "trend_state": str(row["trend_state"]),
                        "volatility_state": str(row["volatility_state"]),
                        "displacement_state": str(row["displacement_state"]),
                        "activity_state": str(row["activity_state"]),
                        "btc_correlation_state": str(row["btc_correlation_state"]),
                        "direction_state": direction,
                        "liquidity_efficiency_state": str(row["liquidity_efficiency_state"]),
                        "trend_efficiency": _finite(row["trend_efficiency"]),
                        "realized_volatility": _finite(row["realized_volatility"]),
                        "displacement_return": _finite(row["displacement_return"]),
                        "btc_correlation": _finite(row["btc_correlation"]),
                        "future_return_bps": future_return,
                        "future_abs_return_bps": future_abs,
                        "future_high_low_range_bps": future_range,
                        "direction_match": _direction_match(direction, future_return),
                    }
                )
    return rows


def _summary(rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "observations": 0,
            "distinct_utc_dates": 0,
            "mean_future_return_bps": None,
            "median_future_return_bps": None,
            "positive_future_return_fraction": None,
            "mean_future_abs_return_bps": None,
            "median_future_abs_return_bps": None,
            "mean_future_high_low_range_bps": None,
            "median_future_high_low_range_bps": None,
            "direction_match_rate": None,
            "descriptive_cell_sufficient": False,
        }
    future_ret = [float(row["future_return_bps"]) for row in rows]
    future_abs = [float(row["future_abs_return_bps"]) for row in rows]
    future_range = [float(row["future_high_low_range_bps"]) for row in rows]
    direction_match = [bool(row["direction_match"]) for row in rows if row["direction_match"] is not None]
    dates = {str(row["timestamp_utc"])[:10] for row in rows}
    rules = config["cell_protocol"]
    return {
        "observations": n,
        "distinct_utc_dates": len(dates),
        "mean_future_return_bps": statistics.fmean(future_ret),
        "median_future_return_bps": statistics.median(future_ret),
        "positive_future_return_fraction": sum(value > 0.0 for value in future_ret) / n,
        "mean_future_abs_return_bps": statistics.fmean(future_abs),
        "median_future_abs_return_bps": statistics.median(future_abs),
        "mean_future_high_low_range_bps": statistics.fmean(future_range),
        "median_future_high_low_range_bps": statistics.median(future_range),
        "direction_match_rate": (
            sum(direction_match) / len(direction_match) if direction_match else None
        ),
        "descriptive_cell_sufficient": bool(
            n >= int(rules["minimum_observations_for_descriptive_cell"])
            and len(dates) >= int(rules["minimum_distinct_utc_dates"])
        ),
    }


def summarize_atlas(
    observations: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    dimensions = [str(value) for value in config["cell_protocol"]["dimensions"]]
    interactions = [
        tuple(str(value) for value in pair)
        for pair in config["cell_protocol"]["interactions"]
    ]
    groups: dict[tuple[str, int, str, str], list[Mapping[str, Any]]] = defaultdict(list)

    for row in observations:
        instrument = str(row["instrument"])
        horizon = int(row["horizon_bars"])
        groups[(instrument, horizon, "ALL", "ALL")].append(row)
        for dimension in dimensions:
            groups[(instrument, horizon, dimension, str(row.get(dimension, "UNKNOWN")))].append(row)
        for left, right in interactions:
            cell = f"{row.get(left, 'UNKNOWN')}|{row.get(right, 'UNKNOWN')}"
            groups[(instrument, horizon, f"{left}__X__{right}", cell)].append(row)

    output: list[dict[str, Any]] = []
    for (instrument, horizon, family, cell), rows in sorted(groups.items()):
        output.append(
            {
                "market": str(config["development_data"]["market"]),
                "venue": str(config["development_data"]["venue"]),
                "instrument": instrument,
                "interval": str(config["development_data"]["interval"]),
                "horizon_bars": horizon,
                "cell_family": family,
                "cell": cell,
                **_summary(rows, config),
            }
        )
    return output


def cross_instrument_breadth(
    cells: Sequence[Mapping[str, Any]],
    *,
    universe_instrument_count: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in cells:
        grouped[(int(row["horizon_bars"]), str(row["cell_family"]), str(row["cell"]))].append(row)
    output: list[dict[str, Any]] = []
    for (horizon, family, cell), rows in sorted(grouped.items()):
        sufficient = [row for row in rows if bool(row["descriptive_cell_sufficient"])]
        med_abs = [
            float(row["median_future_abs_return_bps"])
            for row in sufficient
            if _finite(row.get("median_future_abs_return_bps")) is not None
        ]
        mean_ret = [
            float(row["mean_future_return_bps"])
            for row in sufficient
            if _finite(row.get("mean_future_return_bps")) is not None
        ]
        output.append(
            {
                "horizon_bars": horizon,
                "cell_family": family,
                "cell": cell,
                "instrument_count": len(rows),
                "universe_instrument_count": universe_instrument_count,
                "instrument_coverage_fraction": (
                    len(rows) / universe_instrument_count
                    if universe_instrument_count > 0
                    else None
                ),
                "sufficient_instrument_count": len(sufficient),
                "sufficient_instrument_coverage_fraction": (
                    len(sufficient) / universe_instrument_count
                    if universe_instrument_count > 0
                    else None
                ),
                "median_of_instrument_median_future_abs_return_bps": (
                    statistics.median(med_abs) if med_abs else None
                ),
                "median_of_instrument_mean_future_return_bps": (
                    statistics.median(mean_ret) if mean_ret else None
                ),
                "positive_instrument_mean_return_fraction": (
                    sum(value > 0.0 for value in mean_ret) / len(mean_ret)
                    if mean_ret
                    else None
                ),
            }
        )
    return output


def build_regime_atlas_report(
    frames: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    observations = build_atlas_observations(frames, config)
    cells = summarize_atlas(observations, config)
    breadth = cross_instrument_breadth(
        cells,
        universe_instrument_count=len(config["development_data"]["symbols"]),
    )
    return {
        "schema_version": 1,
        "analysis": "cross_market_regime_atlas_v1_1",
        "protocol_name": str(config["protocol_name"]),
        "phase": str(config["phase"]),
        "development_data": dict(config["development_data"]),
        "state_definitions": dict(config["state_definitions"]),
        "raw_future_outcomes": dict(config["raw_future_outcomes"]),
        "cell_protocol": dict(config["cell_protocol"]),
        "observation_count": len(observations),
        "cell_count": len(cells),
        "observations": observations,
        "cells": cells,
        "cross_instrument_breadth": breadth,
        "claims": {
            **dict(config["claims"]),
            "raw_market_behavior_only": True,
            "strategy_overlay_used": False,
            "state_labels_selected_on_strategy_pnl": False,
            "atlas_result_can_promote_candidate": False,
        },
    }

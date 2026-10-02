"""Regime-switching composite: trend following in trending regimes, mean reversion in chop.

The regime is the frozen ``descriptive_regime_labels_v1`` trend-efficiency label
(Kaufman ER percentile bucket with persistence), computed causally from
completed bars.  Components are the frozen DON8/EMA8 trend targets and a
textbook Bollinger/RSI mean-reversion target.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.descriptive_regime_labels_v1 import kaufman_er, percentile_bucket, persist
from orderflow_edge_lab.strategy_tournament import generate_target_position
from orderflow_edge_lab.universal_backtest import FunctionStrategy

VARIANTS = ("trend_only", "meanrev_only", "switch", "chop_filter")


def regime_labels(frame: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.Series:
    er = kaufman_er(frame["close"], int(cfg["kaufman_er_window_bars"]))
    raw, _, _ = percentile_bucket(er, int(cfg["percentile_history_bars"]),
                                  float(cfg["lower_quantile"]), float(cfg["upper_quantile"]))
    return persist(raw, int(cfg["persistence_bars"]), dict(cfg["labels"]))


def component_targets(frame: pd.DataFrame, trend_params: Mapping[str, Mapping[str, Any]],
                      mr_params: Mapping[str, Any]) -> tuple[pd.Series, pd.Series]:
    don = generate_target_position(frame, "donchian_breakout", dict(trend_params["DON8"]))
    ema = generate_target_position(frame, "ema_tsmom", dict(trend_params["EMA8"]))
    trend = (don.reindex(frame.index).fillna(0.0) + ema.reindex(frame.index).fillna(0.0)) / 2.0
    mr = generate_target_position(frame, "bb_mean_reversion", dict(mr_params)).reindex(frame.index).fillna(0.0)
    return trend, mr


def combine(variant: str, regime: pd.Series, trend: pd.Series, mr: pd.Series) -> pd.Series:
    r = regime.reindex(trend.index).fillna("UNKNOWN")
    known = r != "UNKNOWN"
    chop = r == "CHOP"
    if variant == "trend_only":
        out = trend.where(known, 0.0)
    elif variant == "meanrev_only":
        out = mr.where(known, 0.0)
    elif variant == "switch":
        out = trend.where(~chop, mr).where(known, 0.0)
    elif variant == "chop_filter":
        out = trend.where(~chop, 0.0).where(known, 0.0)
    else:
        raise ValueError(f"unknown variant {variant}")
    return out.astype(float)


def regime_strategy(variant: str, config: Mapping[str, Any], universe: str) -> FunctionStrategy:
    u = config["universes"][universe]
    reg_cfg = config["regime"]
    mr_params = config["components"]["mean_reversion"]["parameters"]

    def target(frame: pd.DataFrame, _params: Mapping[str, Any]) -> pd.Series:
        trend, mr = component_targets(frame, u["trend_parameters"], mr_params)
        return combine(variant, regime_labels(frame, reg_cfg), trend, mr)

    warm = int(reg_cfg["kaufman_er_window_bars"]) + int(reg_cfg["percentile_history_bars"])
    return FunctionStrategy(strategy_id=f"regime:{variant}", target_fn=target, warmup_bars=warm)


def regime_shares(frame: pd.DataFrame, cfg: Mapping[str, Any]) -> dict[str, float]:
    r = regime_labels(frame, cfg)
    r = r[r != "UNKNOWN"]
    return {k: float((r == k).mean()) for k in ("TREND", "MIXED", "CHOP")} if len(r) else {}

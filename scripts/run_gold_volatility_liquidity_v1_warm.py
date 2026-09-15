from __future__ import annotations

"""Launcher that applies the frozen 2020-11/12 warmup to same-clock baselines.

No state result existed when this implementation correction was made. The frozen
features, targets, hypotheses, statistics, and gates are unchanged.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


CORE = Path(__file__).with_name("run_gold_volatility_liquidity_v1.py")
spec = importlib.util.spec_from_file_location("gold_volatility_liquidity_v1_core", CORE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load frozen scorer from {CORE}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def build_observations_with_warmup(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    grid = cfg["observation_grid"]
    hours = set(int(x) for x in grid["anchor_hours_local"])
    warmup_start = pd.Timestamp(cfg["evidence_boundary"]["warmup_start"], tz="UTC")
    dev_start = pd.Timestamp(cfg["evidence_boundary"]["development_start"], tz="UTC")
    dev_end = pd.Timestamp(cfg["evidence_boundary"]["development_end_exclusive"], tz="UTC")

    candidates = d.index[(d.index >= warmup_start) & (d.index < dev_end)]
    local = candidates.tz_convert(module.NY)
    mask = (
        (local.weekday < 5)
        & (local.minute == int(grid["anchor_minute"]))
        & (local.second == 0)
        & np.isin(local.hour, list(hours))
    )
    anchors = candidates[mask]

    rows = []
    for t0 in anchors:
        obs = module.raw_observation(d, pd.Timestamp(t0))
        if obs is not None:
            rows.append(obs)
    raw = pd.DataFrame(rows)
    if raw.empty:
        raise ValueError("no scorable raw observations")
    raw = raw.sort_values(["anchor_hour", "t0_utc"]).reset_index(drop=True)

    lookback = int(grid["same_clock_baseline_lookback_observations"])
    baseline_map = {
        "pre_rv": "baseline_pre_rv",
        "future_rv": "baseline_future_rv",
        "pre_range": "baseline_pre_range",
        "future_range": "baseline_future_range",
        "pre15_spread": "baseline_pre15_spread",
    }
    for source, dest in baseline_map.items():
        raw[dest] = raw.groupby("anchor_hour", group_keys=False)[source].transform(
            lambda s: s.shift(1).rolling(lookback, min_periods=lookback).median()
        )

    raw["pre_rv_ratio"] = raw.pre_rv / raw.baseline_pre_rv
    raw["future_rv_ratio"] = raw.future_rv / raw.baseline_future_rv
    raw["spread_level_ratio"] = raw.pre15_spread / raw.baseline_pre15_spread
    raw["pre_range_ratio"] = raw.pre_range / raw.baseline_pre_range
    raw["future_range_ratio"] = raw.future_range / raw.baseline_future_range

    ratio_cols = [
        "pre_rv_ratio",
        "future_rv_ratio",
        "spread_level_ratio",
        "spread_deterioration_ratio",
        "pre_range_ratio",
        "future_range_ratio",
        "negative_semivariance_share",
    ]
    raw = raw.replace([np.inf, -np.inf], np.nan)
    raw = raw.dropna(subset=["pre_rv_ratio", "future_rv_ratio", "future_range_ratio"])
    raw = raw[(raw.pre_rv_ratio > 0) & (raw.future_rv_ratio > 0) & (raw.future_range_ratio > 0)]
    for c in ratio_cols:
        if c not in raw.columns:
            raise ValueError(f"missing derived column {c}")

    raw = raw[(raw.t0_utc >= dev_start) & (raw.t0_utc < dev_end)].copy()
    if raw.empty:
        raise ValueError("no development observations after warmup baseline construction")
    return raw.sort_values("t0_utc").reset_index(drop=True)


module.build_observations = build_observations_with_warmup

if __name__ == "__main__":
    raise SystemExit(module.main())

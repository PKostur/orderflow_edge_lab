from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint12 import run_meta_family


SYMBOLS = [
    "BTC_USDT",
    "ETH_USDT",
    "SOL_USDT",
    "XRP_USDT",
    "DOGE_USDT",
    "BNB_USDT",
    "ADA_USDT",
    "LINK_USDT",
    "SUI_USDT",
    "ENA_USDT",
]


def _fixtures(days: int = 285):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2025-12-15", periods=(days + 20) * 3, freq="8h", tz="UTC")
    t = np.arange(days, dtype=float)
    daily = {}
    funding = {}
    for j, symbol in enumerate(SYMBOLS):
        factor = 0.0045 * np.sin(t / 7.0) + 0.0025 * np.cos(t / 17.0)
        idio = 0.007 * np.sin(t / (2.3 + 0.11 * j) + 0.73 * j) + 0.003 * np.cos(t / (5.5 + 0.2 * j) + j)
        regime = np.where((t.astype(int) // 35) % 2 == 0, 1.0, -0.65)
        ret = factor * (0.7 + 0.04 * j) + idio * regime + (j - 4.5) * 0.00008
        close = (80.0 + 7.0 * j) * np.cumprod(1.0 + ret)
        open_ = close * (1.0 + 0.002 * np.sin(t / 3.0 + 0.4 * j))
        high = np.maximum(open_, close) * (1.008 + 0.001 * (j % 3))
        low = np.minimum(open_, close) * (0.992 - 0.0005 * (j % 2))
        daily[symbol] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
        k = np.arange(len(fidx), dtype=float)
        rate = 2e-5 * np.sin(k / (11.0 + j)) + (j - 4.5) * 1.5e-6
        funding[symbol] = pd.DataFrame({"funding_rate": rate}, index=fidx)
    return daily, funding


def test_protocol_freeze_has_single_model_and_single_threshold():
    p = json.loads(Path("config/discovery_v2_sprint12_meta_selection_v1.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_MARKET_RESULTS"
    assert p["method_change"]["one_model_specification_only"] is True
    assert p["method_change"]["one_acceptance_threshold_only"] is True
    assert p["method_change"]["no_threshold_or_hyperparameter_grid"] is True
    assert p["walk_forward_model"]["training_window_prior_primary_setups"] == 80
    assert p["walk_forward_model"]["minimum_prior_primary_setups"] == 60
    assert p["walk_forward_model"]["accept_if_probability_positive_at_least"] == 0.60
    assert p["data"]["no_2025_data_for_discovery"] is True
    assert p["claims"]["persistent_edge_established"] is False


def test_meta_selector_produces_causal_probabilities_and_one_x_exposure():
    daily, funding = _fixtures()
    run = run_meta_family(
        "meta_low_skew_90d",
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        side_cost_bps=10.0,
        training_window=80,
        minimum_training=60,
        accept_probability=0.60,
    )
    p = pd.to_numeric(run.predictions["probability_positive"], errors="coerce")
    assert p.notna().sum() > 20
    finite = run.predictions.loc[p.notna()].copy()
    assert (finite["trade"].to_numpy() == (finite["probability_positive"].to_numpy() >= 0.60)).all()
    assert run.candidate.observations.index.equals(run.reversed_same_decisions.observations.index)
    assert run.candidate.observations.index.equals(run.ungated_parent.observations.index)
    assert (run.candidate.observations["active_gross"] <= 1.0 + 1e-12).all()
    assert (run.ungated_parent.observations["active_gross"] <= 1.0 + 1e-12).all()
    assert np.isfinite(run.candidate.observations["net_return_bps"]).all()


def test_same_open_closing_label_cannot_change_current_meta_probability():
    daily, funding = _fixtures()
    base = run_meta_family(
        "meta_funding_carry_14d",
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        side_cost_bps=10.0,
        training_window=80,
        minimum_training=60,
        accept_probability=0.60,
    )
    finite = base.predictions.loc[np.isfinite(pd.to_numeric(base.predictions["probability_positive"], errors="coerce"))]
    assert len(finite) > 10
    row = finite.iloc[min(5, len(finite) - 1)]
    entry = pd.Timestamp(row["start_timestamp"])
    changed = {k: v.copy() for k, v in daily.items()}
    for j, symbol in enumerate(SYMBOLS):
        changed[symbol].loc[entry, "open"] *= 0.82 + 0.04 * j
    alt = run_meta_family(
        "meta_funding_carry_14d",
        changed,
        symbols=SYMBOLS,
        funding_frames=funding,
        side_cost_bps=10.0,
        training_window=80,
        minimum_training=60,
        accept_probability=0.60,
    )
    a = base.predictions.loc[pd.to_datetime(base.predictions["start_timestamp"], utc=True) == entry].iloc[0]
    b = alt.predictions.loc[pd.to_datetime(alt.predictions["start_timestamp"], utc=True) == entry].iloc[0]
    assert np.isclose(float(a["probability_positive"]), float(b["probability_positive"]), atol=1e-12, rtol=0.0)
    assert bool(a["trade"]) == bool(b["trade"])


def test_future_prices_do_not_change_earlier_meta_decisions():
    daily, funding = _fixtures()
    base = run_meta_family(
        "meta_low_skew_90d",
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        side_cost_bps=10.0,
        training_window=80,
        minimum_training=60,
        accept_probability=0.60,
    )
    finite = base.predictions.loc[np.isfinite(pd.to_numeric(base.predictions["probability_positive"], errors="coerce"))]
    cutoff = pd.Timestamp(finite.iloc[min(10, len(finite) - 1)]["start_timestamp"])
    changed = {k: v.copy() for k, v in daily.items()}
    future_mask = changed[SYMBOLS[0]].index > cutoff
    for j, symbol in enumerate(SYMBOLS):
        changed[symbol].loc[future_mask, "close"] *= 1.0 + 0.15 * np.sin(np.arange(future_mask.sum()) + j)
        changed[symbol].loc[future_mask, "high"] = np.maximum(
            changed[symbol].loc[future_mask, "high"], changed[symbol].loc[future_mask, "close"] * 1.01
        )
        changed[symbol].loc[future_mask, "low"] = np.minimum(
            changed[symbol].loc[future_mask, "low"], changed[symbol].loc[future_mask, "close"] * 0.99
        )
    alt = run_meta_family(
        "meta_low_skew_90d",
        changed,
        symbols=SYMBOLS,
        funding_frames=funding,
        side_cost_bps=10.0,
        training_window=80,
        minimum_training=60,
        accept_probability=0.60,
    )
    left = base.predictions.loc[pd.to_datetime(base.predictions["start_timestamp"], utc=True) <= cutoff].copy()
    right = alt.predictions.loc[pd.to_datetime(alt.predictions["start_timestamp"], utc=True) <= cutoff].copy()
    merged = left.merge(right, on="start_timestamp", suffixes=("_a", "_b"))
    mask = np.isfinite(pd.to_numeric(merged["probability_positive_a"], errors="coerce"))
    assert mask.sum() > 5
    assert np.allclose(
        merged.loc[mask, "probability_positive_a"].to_numpy(float),
        merged.loc[mask, "probability_positive_b"].to_numpy(float),
        atol=1e-12,
        rtol=0.0,
    )

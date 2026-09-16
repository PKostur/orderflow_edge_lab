from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint4 import (
    _pair_target,
    fixed_pair_relative_value_reversion,
    liquidity_range_shock_reversal,
    volatility_compression_breakout,
)


SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT",
    "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT",
]


def _fixtures(days: int = 120):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    funding_idx = pd.date_range("2026-01-01", periods=days * 3, freq="8h", tz="UTC")
    daily = {}
    funding = {}
    t = np.arange(days, dtype=float)
    for j, symbol in enumerate(SYMBOLS):
        drift = (j - 4.5) * 0.0003
        wave = 0.012 * np.sin(t / (3.0 + j * 0.15)) + 0.004 * np.sin(t / 11.0 + j)
        close = 100.0 * np.exp(drift * t + wave)
        open_ = close * (1.0 + 0.0025 * np.cos(t / 4.0 + j * 0.3))
        width = 0.008 + 0.004 * (1.0 + np.sin(t / (5.0 + 0.1 * j)))
        high = np.maximum(open_, close) * (1.0 + width)
        low = np.minimum(open_, close) * (1.0 - width)
        volume = 1000.0 + 30.0 * j + 100.0 * (1.0 + np.cos(t / 6.0 + j))
        daily[symbol] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )
        rates = (j - 4.5) * 0.000005 + 0.000003 * np.sin(np.arange(days * 3) / 9.0 + j)
        funding[symbol] = pd.DataFrame({"funding_rate": rates}, index=funding_idx)
    return daily, funding


def test_protocol_is_frozen_before_results():
    p = json.loads(Path("config/discovery_v2_sprint4_v1.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_MARKET_RESULTS"
    assert p["execution"]["leverage"] == 1.0
    assert p["execution"]["transaction_cost_bps_per_side_on_turnover"] == 10.0
    assert len(p["families"]) == 3
    assert len(p["families"]["volatility_compression_breakout"]["compression_ratio_threshold_variants"]) == 4
    assert len(p["families"]["liquidity_range_shock_reversal"]["range_baseline_days_variants"]) == 4
    assert len(p["families"]["fixed_pair_relative_value_reversion"]["ratio_lookback_days_variants"]) == 4
    assert len(p["families"]["fixed_pair_relative_value_reversion"]["fixed_pairs"]) == 7
    assert p["trial_accounting"]["directional_candidate_variants"] == 12
    assert p["trial_accounting"]["all_12_variants_count"] is True
    assert p["trial_accounting"]["no_grid_expansion_after_results"] is True
    assert p["trial_accounting"]["no_regime_router_selection_inside_this_sprint"] is True
    assert p["claims"]["persistent_edge_established"] is False
    assert p["claims"]["live_execution_supported"] is False
    assert p["claims"]["existing_candidates_modified"] is False
    assert p["claims"]["failed_prior_family_rescued"] is False


def test_all_three_engines_emit_next_open_observations():
    daily, funding = _fixtures()
    compression = volatility_compression_breakout(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        recent_vol_days=5,
        reference_vol_days=20,
        compression_ratio_threshold=0.90,
        common_warmup_days=25,
        side_cost_bps=10.0,
    )
    shock = liquidity_range_shock_reversal(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        range_baseline_days=20,
        common_warmup_days=45,
        side_cost_bps=10.0,
    )
    pairs = fixed_pair_relative_value_reversion(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        fixed_pairs=[
            ["ETH_USDT", "SOL_USDT"], ["ETH_USDT", "BNB_USDT"],
            ["SOL_USDT", "SUI_USDT"], ["ETH_USDT", "LINK_USDT"],
            ["ETH_USDT", "ENA_USDT"], ["XRP_USDT", "ADA_USDT"],
            ["XRP_USDT", "DOGE_USDT"],
        ],
        ratio_lookback_days=20,
        entry_abs_z_threshold=1.5,
        common_warmup_days=45,
        side_cost_bps=10.0,
    )
    for run in (compression, shock, pairs):
        assert len(run.observations) > 20
        assert run.observations.index.is_monotonic_increasing
        assert (run.observations["active_gross"] <= 1.0 + 1e-12).all()
        assert np.isfinite(run.observations["net_return_bps"]).all()
        assert (pd.to_datetime(run.observations["end_timestamp"]) > run.observations.index).all()


def test_reversed_controls_keep_identical_observation_timing():
    daily, funding = _fixtures()
    kwargs = dict(
        daily_frames=daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        range_baseline_days=30,
        common_warmup_days=45,
        side_cost_bps=10.0,
    )
    normal = liquidity_range_shock_reversal(**kwargs, reverse=False)
    control = liquidity_range_shock_reversal(**kwargs, reverse=True)
    assert normal.observations.index.equals(control.observations.index)
    assert normal.observations["end_timestamp"].equals(control.observations["end_timestamp"])


def test_pair_target_is_market_neutral_and_capped_at_one_x_gross():
    scores = {
        ("ETH_USDT", "SOL_USDT"): 2.0,
        ("ETH_USDT", "BNB_USDT"): -2.3,
        ("XRP_USDT", "ADA_USDT"): 0.4,
    }
    target = _pair_target(scores, symbols=SYMBOLS, threshold=1.5, reverse=False)
    assert abs(float(target.sum())) < 1e-12
    assert float(target.abs().sum()) <= 1.0 + 1e-12
    reversed_target = _pair_target(scores, symbols=SYMBOLS, threshold=1.5, reverse=True)
    assert np.allclose(target.to_numpy(), -reversed_target.to_numpy())

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint8 import (
    build_frozen_regimes,
    trend_gated_momentum_acceleration,
    low_vol_range_beta_asymmetry,
)

SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]
ALTS = SYMBOLS[1:]


def _fixtures(days=190):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2026-01-01", periods=days * 3, freq="8h", tz="UTC")
    t = np.arange(days, dtype=float)
    btc_ret = 0.010 * np.sin(t / 3.4) + 0.006 * np.sin(t / 17.0) + 0.0015
    btc_close = 100.0 * np.cumprod(1.0 + btc_ret)
    daily, funding = {}, {}
    for j, symbol in enumerate(SYMBOLS):
        if j == 0:
            close = btc_close
        else:
            own = (0.45 + 0.07 * j) * btc_ret + 0.005 * np.sin(t / (2.5 + 0.17 * j) + j) + (j - 4.5) * 0.0001
            close = (80.0 + 7.0 * j) * np.cumprod(1.0 + own)
        open_ = close * (1.0 + 0.0025 * np.cos(t / 5.0 + j))
        spread = 0.008 + 0.004 * (1.0 + np.sin(t / 9.0 + j))
        high = np.maximum(open_, close) * (1.0 + spread)
        low = np.minimum(open_, close) * (1.0 - spread)
        daily[symbol] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
        funding[symbol] = pd.DataFrame({"funding_rate": np.full(days * 3, (j - 4.5) * 1e-6)}, index=fidx)
    return daily, funding


def test_protocol_is_frozen_and_narrow():
    p = json.loads(Path("config/discovery_v2_sprint8_regime_gated_v1.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_MARKET_RESULTS"
    assert p["trial_accounting"]["directional_candidate_variants_added_this_sprint"] == 8
    assert p["trial_accounting"]["all_8_variants_count"] is True
    assert p["trial_accounting"]["complement_regime_controls_count_as_controls"] is True
    assert p["family_falsification_gate"]["minimum_candidate_minus_complement_regime_control_mean_bps"] == 5.0
    assert p["execution"]["common_comparison_warmup_days"] == 90
    assert p["data"]["no_2025_data_for_discovery"] is True
    assert p["claims"]["persistent_edge_established"] is False
    assert p["claims"]["regime_router_supported"] is False


def test_regime_state_at_execution_open_is_future_invariant():
    d, _ = _fixtures()
    btc = d["BTC_USDT"].copy()
    base = build_frozen_regimes(btc)
    target_ts = btc.index[130]
    changed = btc.copy()
    changed.loc[target_ts, ["high", "low", "close"]] = [btc.loc[target_ts, "high"] * 3.0, btc.loc[target_ts, "low"] * 0.3, btc.loc[target_ts, "close"] * 1.8]
    mutated = build_frozen_regimes(changed)
    assert base.loc[target_ts] == mutated.loc[target_ts]


def test_trend_gate_and_complement_partition_same_timeline():
    d, f = _fixtures()
    kw = dict(
        daily_frames=d, symbols=SYMBOLS, funding_frames=f, window_days=5,
        common_warmup_days=90, side_cost_bps=10.0,
        active_regimes=("HIGH_VOL_TREND", "LOW_VOL_TREND"),
    )
    candidate = trend_gated_momentum_acceleration(**kw, reverse=False, gate_mode="hypothesis")
    reverse = trend_gated_momentum_acceleration(**kw, reverse=True, gate_mode="hypothesis")
    complement = trend_gated_momentum_acceleration(**kw, reverse=False, gate_mode="complement")
    assert candidate.observations.index.equals(reverse.observations.index)
    assert candidate.observations.index.equals(complement.observations.index)
    assert candidate.observations["end_timestamp"].equals(complement.observations["end_timestamp"])
    a = candidate.observations["active_gross"].to_numpy(float)
    b = complement.observations["active_gross"].to_numpy(float)
    assert np.all(a <= 1.0 + 1e-12) and np.all(b <= 1.0 + 1e-12)
    assert np.all((a > 1e-12) & (b > 1e-12) == False)
    assert np.count_nonzero(a > 1e-12) + np.count_nonzero(b > 1e-12) > 20


def test_beta_gate_keeps_btc_zero_and_charges_cash_transitions():
    d, f = _fixtures()
    kw = dict(
        daily_frames=d, symbols=SYMBOLS, alt_symbols=ALTS, funding_frames=f,
        lookback_days=45, common_warmup_days=90, minimum_subset_observations=5,
        side_cost_bps=10.0, active_regimes=("LOW_VOL_RANGE",),
    )
    candidate = low_vol_range_beta_asymmetry(**kw, reverse=False, gate_mode="hypothesis")
    complement = low_vol_range_beta_asymmetry(**kw, reverse=False, gate_mode="complement")
    assert candidate.observations.index.equals(complement.observations.index)
    for run in (candidate, complement):
        btc = run.contributions.loc[run.contributions["symbol"] == "BTC_USDT", "net_contribution_bps"]
        assert len(btc) == len(run.observations)
        assert np.allclose(btc.to_numpy(float), 0.0, atol=1e-12)
        assert (run.observations["active_gross"] <= 1.0 + 1e-12).all()
    active = candidate.observations["active_gross"] > 0.0
    if active.any() and (~active).any():
        transitions = active.astype(int).diff().abs().fillna(0) > 0
        assert transitions.any()
        assert (candidate.observations.loc[transitions, "cost_bps"] > 0.0).any()

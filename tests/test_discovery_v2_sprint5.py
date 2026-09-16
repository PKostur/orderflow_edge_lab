from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint5 import (
    amihud_liquidity_premium,
    close_location_pressure,
    donchian_channel_position_continuation,
)

SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fixtures(days: int = 120):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2026-01-01", periods=days * 3, freq="8h", tz="UTC")
    t = np.arange(days, dtype=float); daily = {}; funding = {}
    for j, s in enumerate(SYMBOLS):
        drift = (j - 4.5) * 0.00025
        close = 100.0 * np.exp(drift * t + 0.018 * np.sin(t / (4.0 + 0.2*j)) + 0.005 * np.cos(t / 13.0 + j))
        open_ = close * (1.0 + 0.003 * np.sin(t / 5.0 + j))
        spread = 0.008 + 0.003 * (1.0 + np.cos(t / 7.0 + j))
        high = np.maximum(open_, close) * (1.0 + spread)
        low = np.minimum(open_, close) * (1.0 - spread)
        volume = 1500.0 + 100.0*j + 250.0*(1.0 + np.sin(t / (6.0 + 0.1*j)))
        daily[s] = pd.DataFrame({"open":open_,"high":high,"low":low,"close":close,"volume":volume}, index=idx)
        funding[s] = pd.DataFrame({"funding_rate": (j-4.5)*0.000004 + 0.000002*np.sin(np.arange(days*3)/8.0+j)}, index=fidx)
    return daily, funding


def test_protocol_is_frozen_and_counts_12_variants():
    p = json.loads(Path("config/discovery_v2_sprint5_v1.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_MARKET_RESULTS"
    assert p["execution"]["leverage"] == 1.0
    assert p["execution"]["transaction_cost_bps_per_side_on_turnover"] == 10.0
    assert p["trial_accounting"]["directional_candidate_variants"] == 12
    assert p["trial_accounting"]["all_12_variants_count"] is True
    assert p["trial_accounting"]["no_grid_expansion_after_results"] is True
    assert len(p["families"]["donchian_channel_position_continuation"]["channel_lookback_days_variants"]) == 4
    assert len(p["families"]["amihud_liquidity_premium"]["lookback_days_variants"]) == 4
    assert len(p["families"]["close_location_pressure"]["lookback_days_variants"]) == 4
    assert p["claims"]["persistent_edge_established"] is False
    assert p["claims"]["existing_candidates_modified"] is False


def test_all_engines_emit_completed_next_open_observations():
    daily, funding = _fixtures()
    runs = [
        donchian_channel_position_continuation(daily, symbols=SYMBOLS, funding_frames=funding, channel_lookback_days=20, common_warmup_days=40, side_cost_bps=10.0),
        amihud_liquidity_premium(daily, symbols=SYMBOLS, funding_frames=funding, lookback_days=28, common_warmup_days=45, side_cost_bps=10.0),
        close_location_pressure(daily, symbols=SYMBOLS, funding_frames=funding, lookback_days=10, common_warmup_days=20, side_cost_bps=10.0),
    ]
    for run in runs:
        assert len(run.observations) > 20
        assert run.observations.index.is_monotonic_increasing
        assert (run.observations["active_gross"] <= 1.0 + 1e-12).all()
        assert np.isfinite(run.observations["net_return_bps"]).all()
        assert (pd.to_datetime(run.observations["end_timestamp"]) > run.observations.index).all()


def test_reversed_control_preserves_timing():
    daily, funding = _fixtures()
    kwargs = dict(daily_frames=daily, symbols=SYMBOLS, funding_frames=funding, lookback_days=10, common_warmup_days=20, side_cost_bps=10.0)
    a = close_location_pressure(**kwargs, reverse=False)
    b = close_location_pressure(**kwargs, reverse=True)
    assert a.observations.index.equals(b.observations.index)
    assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"])

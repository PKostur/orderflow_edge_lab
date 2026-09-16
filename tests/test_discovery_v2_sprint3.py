from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint3 import (
    btc_downtrend_intraday_skewness,
    funding_carry_spread,
    volume_confirmed_momentum,
)


SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fixtures(days: int = 110):
    daily_idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    four_idx = pd.date_range("2026-01-01", periods=days * 6, freq="4h", tz="UTC")
    funding_idx = pd.date_range("2026-01-01", periods=days * 3, freq="8h", tz="UTC")
    daily = {}
    four = {}
    funding = {}
    for j, symbol in enumerate(SYMBOLS):
        drift = -0.0015 if symbol == "BTC_USDT" else (j - 4.5) * 0.00025
        t = np.arange(days, dtype=float)
        close = 100.0 * np.exp(drift * t + 0.01 * np.sin(t / (3.0 + j * 0.1)))
        open_ = close * (1.0 + 0.0005 * np.cos(t / 5.0 + j))
        volume = 1000.0 + 20.0 * j + 100.0 * (1.0 + np.sin(t / (4.0 + j * 0.1)))
        daily[symbol] = pd.DataFrame({
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "volume": volume,
        }, index=daily_idx)

        th = np.arange(days * 6, dtype=float)
        hclose = 100.0 * np.exp((drift / 6.0) * th + 0.004 * np.sin(th / (2.0 + 0.15 * j)))
        four[symbol] = pd.DataFrame({
            "open": hclose,
            "high": hclose * 1.003,
            "low": hclose * 0.997,
            "close": hclose,
            "volume": 200.0 + j + 10.0 * np.cos(th / 7.0),
        }, index=four_idx)

        rates = (j - 4.5) * 0.00001 + 0.000005 * np.sin(np.arange(days * 3) / 8.0)
        funding[symbol] = pd.DataFrame({"funding_rate": rates}, index=funding_idx)
    return daily, four, funding


def test_protocol_is_frozen_before_results():
    p = json.loads(Path("config/discovery_v2_sprint3_v1.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_MARKET_RESULTS"
    assert p["execution"]["leverage"] == 1.0
    assert p["execution"]["transaction_cost_bps_per_side_on_turnover"] == 10.0
    assert len(p["families"]) == 3
    assert len(p["families"]["btc_downtrend_intraday_skewness"]["lookback_days_variants"]) == 4
    assert len(p["families"]["funding_carry_spread"]["lookback_days_variants"]) == 4
    assert len(p["families"]["volume_confirmed_momentum"]["volume_baseline_days_variants"]) == 4
    assert p["trial_accounting"]["all_12_directional_candidate_variants_count"] is True
    assert p["trial_accounting"]["no_grid_expansion_after_results"] is True
    assert p["claims"]["persistent_edge_established"] is False
    assert p["claims"]["live_execution_supported"] is False
    assert p["claims"]["beta45_modified"] is False
    assert p["claims"]["sprint2_failed_family_modified"] is False
    assert "Generated from" in p["hypothesis_provenance"]["btc_downtrend_intraday_skewness"]


def test_all_three_engines_emit_completed_observations():
    daily, four, funding = _fixtures()
    skew = btc_downtrend_intraday_skewness(
        daily, four, symbols=SYMBOLS, funding_frames=funding,
        lookback_days=7, common_warmup_days=20, btc_trend_lookback_days=20,
        side_cost_bps=10.0,
    )
    carry = funding_carry_spread(
        daily, funding, symbols=SYMBOLS,
        lookback_days=7, common_warmup_days=28, minimum_settlements_per_day=2,
        side_cost_bps=10.0,
    )
    volume = volume_confirmed_momentum(
        daily, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=20, common_warmup_days=45, side_cost_bps=10.0,
    )
    for run in (skew, carry, volume):
        assert len(run.observations) > 20
        assert run.observations.index.is_monotonic_increasing
        assert (run.observations["active_gross"] <= 1.0 + 1e-12).all()
        assert np.isfinite(run.observations["net_return_bps"]).all()


def test_reversed_controls_do_not_change_signal_timing():
    daily, four, funding = _fixtures()
    normal = volume_confirmed_momentum(
        daily, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=20, common_warmup_days=45, side_cost_bps=10.0, reverse=False,
    )
    reversed_run = volume_confirmed_momentum(
        daily, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=20, common_warmup_days=45, side_cost_bps=10.0, reverse=True,
    )
    assert normal.observations.index.equals(reversed_run.observations.index)
    assert normal.observations["end_timestamp"].equals(reversed_run.observations["end_timestamp"])

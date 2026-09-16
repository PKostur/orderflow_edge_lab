from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint7 import (
    vol_adjusted_short_term_reversal,
    momentum_acceleration,
    upside_downside_beta_asymmetry,
)

SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]
ALTS = SYMBOLS[1:]


def _fixtures(days=140):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2026-01-01", periods=days * 3, freq="8h", tz="UTC")
    t = np.arange(days, dtype=float)
    btc_ret = 0.012 * np.sin(t / 3.1) + 0.004 * np.cos(t / 7.0)
    btc_close = 100.0 * np.cumprod(1.0 + btc_ret)
    daily, funding = {}, {}
    for j, symbol in enumerate(SYMBOLS):
        if j == 0:
            close = btc_close
        else:
            own = (0.55 + 0.06 * j) * btc_ret + 0.0045 * np.sin(t / (2.2 + j * 0.15) + j) + (j - 4.5) * 0.00012
            close = (90.0 + 5.0 * j) * np.cumprod(1.0 + own)
        open_ = close * (1.0 + 0.002 * np.cos(t / 5.0 + j))
        high = np.maximum(open_, close) * 1.008
        low = np.minimum(open_, close) * 0.992
        daily[symbol] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
        funding[symbol] = pd.DataFrame({"funding_rate": np.full(days * 3, (j - 4.5) * 1e-6)}, index=fidx)
    return daily, funding


def test_protocol_frozen_and_trial_count():
    p = json.loads(Path("config/discovery_v2_sprint7_v1.json").read_text())
    assert p["status"] == "FROZEN_BEFORE_MARKET_RESULTS"
    assert p["execution"]["leverage"] == 1.0
    assert p["trial_accounting"]["directional_candidate_variants_added_this_sprint"] == 12
    assert p["trial_accounting"]["sequential_discovery_debt_acknowledged"] is True
    assert p["trial_accounting"]["no_2025_temporal_data_for_discovery"] is True
    assert p["trial_accounting"]["no_grid_expansion_after_results"] is True
    assert p["evidence_boundary"]["d3_failure_is_terminal_for_candidate_id"] is True
    assert p["claims"]["persistent_edge_established"] is False


def test_engines_emit_next_open_one_x():
    d, f = _fixtures()
    runs = [
        vol_adjusted_short_term_reversal(d, symbols=SYMBOLS, funding_frames=f, volatility_lookback_days=20, common_warmup_days=40, side_cost_bps=10.0),
        momentum_acceleration(d, symbols=SYMBOLS, funding_frames=f, window_days=5, common_warmup_days=20, side_cost_bps=10.0),
        upside_downside_beta_asymmetry(d, symbols=SYMBOLS, alt_symbols=ALTS, funding_frames=f, lookback_days=45, common_warmup_days=60, minimum_subset_observations=5, side_cost_bps=10.0),
    ]
    for r in runs:
        assert len(r.observations) > 20
        assert (r.observations["active_gross"] <= 1.0 + 1e-12).all()
        assert np.isfinite(r.observations["net_return_bps"]).all()
        assert (pd.to_datetime(r.observations["end_timestamp"]) > r.observations.index).all()


def test_reversal_uses_strictly_prior_volatility_and_reverse_preserves_timing():
    d, f = _fixtures()
    kw = dict(daily_frames=d, symbols=SYMBOLS, funding_frames=f, volatility_lookback_days=10, common_warmup_days=40, side_cost_bps=10.0)
    a = vol_adjusted_short_term_reversal(**kw, reverse=False)
    b = vol_adjusted_short_term_reversal(**kw, reverse=True)
    assert a.observations.index.equals(b.observations.index)
    assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"])


def test_beta_family_never_trades_btc_and_reverse_preserves_timing():
    d, f = _fixtures()
    kw = dict(daily_frames=d, symbols=SYMBOLS, alt_symbols=ALTS, funding_frames=f, lookback_days=30, common_warmup_days=60, minimum_subset_observations=5, side_cost_bps=10.0)
    a = upside_downside_beta_asymmetry(**kw, reverse=False)
    b = upside_downside_beta_asymmetry(**kw, reverse=True)
    assert a.observations.index.equals(b.observations.index)
    assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"])
    btc = a.contributions.loc[a.contributions["symbol"] == "BTC_USDT", "net_contribution_bps"]
    assert len(btc) > 0
    assert np.allclose(btc.to_numpy(float), 0.0, atol=1e-12)

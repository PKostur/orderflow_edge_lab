from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.volume_momentum_candidate import run_volume_momentum_candidate


SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fixtures(days: int = 100):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2026-01-01", periods=days * 3, freq="8h", tz="UTC")
    frames = {}
    funding = {}
    for j, symbol in enumerate(SYMBOLS):
        t = np.arange(days, dtype=float)
        close = 100.0 * np.exp((j - 4.5) * 0.0004 * t + 0.01 * np.sin(t / (3.0 + j * 0.15)))
        open_ = close * (1.0 + 0.001 * np.cos(t / 5.0 + j))
        volume = 1000.0 + 50.0 * j + 100.0 * (1.0 + np.sin(t / (4.0 + j * 0.1)))
        frames[symbol] = pd.DataFrame({"open": open_, "close": close, "volume": volume}, index=idx)
        funding[symbol] = pd.DataFrame({"funding_rate": np.full(len(fidx), (j - 4.5) * 1e-6)}, index=fidx)
    return frames, funding


def test_candidate_and_d2_contract_are_locked():
    candidate = json.loads(Path("config/dv2_volume_confirmed_momentum_30d_v1.json").read_text())
    d2 = json.loads(Path("config/dv2_volume_confirmed_momentum_30d_d2_binance_v1.json").read_text())
    assert candidate["candidate_id"] == "dv2_volume_confirmed_momentum_30d_v1"
    assert candidate["status"] == "FROZEN_CANDIDATE"
    assert candidate["rule"]["volume_baseline_days"] == 30
    assert candidate["rule"]["gross_exposure"] == 1.0
    assert candidate["rule"]["leverage"] == 1.0
    assert candidate["rule"]["transaction_cost_bps_per_side_on_actual_turnover"] == 10.0
    assert d2["status"] == "FROZEN_BEFORE_D2_RESULT"
    assert d2["data"]["volume_semantic_locked_before_result"] is True
    assert d2["data"]["no_alternative_quote_or_taker_volume_field_after_result"] is True
    assert "base-asset volume" in d2["data"]["kline_volume_semantic"]
    assert d2["claims"]["retuning_allowed"] is False


def test_candidate_has_next_open_timing_and_one_x_gross():
    frames, funding = _fixtures()
    run = run_volume_momentum_candidate(
        frames, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=30, fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0,
    )
    expected_first_start = frames["BTC_USDT"].index[46]
    expected_first_end = frames["BTC_USDT"].index[47]
    assert run.observations.index[0] == expected_first_start
    assert run.observations.iloc[0]["end_timestamp"] == expected_first_end
    assert np.allclose(run.observations["active_gross"].to_numpy(float), 1.0)
    assert (run.weights.abs().sum(axis=1) <= 1.0 + 1e-12).all()
    assert np.allclose(run.weights.sum(axis=1).to_numpy(float), 0.0)


def test_future_data_change_does_not_change_prior_weights():
    frames, funding = _fixtures()
    first = run_volume_momentum_candidate(
        frames, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=30, fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0,
    )
    changed = {k: v.copy() for k, v in frames.items()}
    cutoff = changed["BTC_USDT"].index[70]
    for symbol in SYMBOLS:
        changed[symbol].loc[changed[symbol].index > cutoff, "close"] *= 4.0
        changed[symbol].loc[changed[symbol].index > cutoff, "volume"] *= 10.0
    second = run_volume_momentum_candidate(
        changed, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=30, fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0,
    )
    common = first.weights.index[first.weights.index <= cutoff]
    pd.testing.assert_frame_equal(first.weights.loc[common], second.weights.loc[common])


def test_reversed_control_has_identical_timing_and_opposite_weights():
    frames, funding = _fixtures()
    normal = run_volume_momentum_candidate(
        frames, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=30, fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0, reverse=False,
    )
    reversed_run = run_volume_momentum_candidate(
        frames, symbols=SYMBOLS, funding_frames=funding,
        volume_baseline_days=30, fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0, reverse=True,
    )
    assert normal.observations.index.equals(reversed_run.observations.index)
    assert normal.observations["end_timestamp"].equals(reversed_run.observations["end_timestamp"])
    assert np.allclose(normal.weights.to_numpy(float), -reversed_run.weights.to_numpy(float))

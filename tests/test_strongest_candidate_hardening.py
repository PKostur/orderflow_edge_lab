from __future__ import annotations

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import _to_ms
from orderflow_edge_lab.strongest_candidate_hardening import (
    evaluate_cross_sectional_panel,
    evaluate_trend_panel,
)


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


def _trend_candidate() -> dict:
    return {
        "specification": {
            "symbols": SYMBOLS,
            "fast_ema": 3,
            "slow_ema": 8,
            "atr_period": 3,
            "min_atr_spread": 0.05,
        }
    }


def _xs_candidate() -> dict:
    return {
        "specification": {
            "symbols": SYMBOLS,
            "lookback_days": 30,
            "holding_days": 7,
            "quantile_fraction": 0.25,
        }
    }


def _trend_frames() -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2025-01-01", periods=720, freq="8h", tz="UTC")
    out = {}
    for i, symbol in enumerate(SYMBOLS):
        slope = 0.0008 + i * 0.00003
        close = 100.0 * np.exp(np.arange(len(idx)) * slope)
        open_ = close * 0.9995
        out[symbol] = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.002,
                "low": np.minimum(open_, close) * 0.998,
                "close": close,
                "volume": np.ones(len(idx)),
            },
            index=idx,
        )
    return out


def _daily_frames() -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2024-01-01", periods=620, freq="D", tz="UTC")
    out = {}
    slopes = np.linspace(-0.0025, 0.0030, len(SYMBOLS))
    for symbol, slope in zip(SYMBOLS, slopes):
        close = 100.0 * np.exp(np.arange(len(idx)) * slope)
        open_ = close * 0.9998
        out[symbol] = pd.DataFrame(
            {"open": open_, "close": close, "high": close * 1.001, "low": close * 0.999},
            index=idx,
        )
    return out


def _empty_funding(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {
        symbol: pd.DataFrame(
            columns=["funding_rate"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        for symbol in frames
    }


def test_binance_timestamp_normalizer_accepts_aware_iso() -> None:
    assert _to_ms("2026-09-12T00:00:00Z") == 1789171200000


def test_trend_hardening_discriminates_original_from_reversal() -> None:
    frames = _trend_frames()
    report = evaluate_trend_panel(
        frames,
        _empty_funding(frames),
        _trend_candidate(),
        cost_bps=20.0,
        fold_days=60,
        regime_return_days=30,
        regime_vol_days=10,
    )
    original = report["modes"]["frozen_original"]
    reversed_ = report["modes"]["exact_signal_reversal"]
    assert original["net_return"] > 0
    assert reversed_["net_return"] < original["net_return"]
    assert report["leave_one_out_all_positive"] is True
    assert original["independent_folds"] >= 3


def test_cross_sectional_signal_beats_random_rank_placebo_on_structured_panel() -> None:
    frames = _daily_frames()
    report = evaluate_cross_sectional_panel(
        frames,
        _empty_funding(frames),
        _xs_candidate(),
        cost_bps=20.0,
        fold_days=120,
        placebo_permutations=60,
        placebo_seed=20260920,
    )
    actual = report["actual"]["net_return"]
    placebo = report["random_rank_placebo"]
    assert actual > 0
    assert actual > placebo["median_net_return"]
    assert placebo["one_sided_empirical_p"] <= 0.10

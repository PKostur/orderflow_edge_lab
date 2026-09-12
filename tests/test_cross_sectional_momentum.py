from __future__ import annotations

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_sectional_momentum import backtest_cross_sectional_momentum, build_signal_weights


def _frames():
    idx = pd.date_range("2025-01-01", periods=260, freq="D", tz="UTC")
    frames = {}
    slopes = {"A": 0.0030, "B": 0.0020, "C": 0.0010, "D": -0.0002, "E": -0.0010, "F": -0.0020}
    for symbol, slope in slopes.items():
        close = 100.0 * np.exp(np.arange(len(idx)) * slope)
        open_ = close * (1.0 + 0.0001)
        frames[symbol] = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.001,
                "low": np.minimum(open_, close) * 0.999,
                "close": close,
                "volume": np.ones(len(idx)),
            },
            index=idx,
        )
    return frames


def test_signal_ranks_past_returns_without_future_data():
    frames = _frames()
    closes = pd.concat({k: v["close"] for k, v in frames.items()}, axis=1)
    weights = build_signal_weights(closes, lookback_days=30, holding_days=7, quantile_fraction=0.25, variant="long_only_top")
    # Six symbols with q=0.25 selects exactly one winner. At the first rebalance the strongest trailing asset is A.
    assert weights.iloc[30]["A"] == 1.0
    assert float(weights.iloc[30].abs().sum()) == 1.0
    assert weights.iloc[29].abs().sum() == 0.0


def test_costs_reduce_causal_portfolio_result():
    frames = _frames()
    low = backtest_cross_sectional_momentum(
        frames,
        lookback_days=30,
        holding_days=7,
        quantile_fraction=0.25,
        variant="dollar_neutral_top_bottom",
        round_trip_cost_bps=0.0,
        fold_days=60,
    )
    high = backtest_cross_sectional_momentum(
        frames,
        lookback_days=30,
        holding_days=7,
        quantile_fraction=0.25,
        variant="dollar_neutral_top_bottom",
        round_trip_cost_bps=20.0,
        fold_days=60,
    )
    assert low["rebalances"] > 20
    assert low["net_return"] > 0
    assert high["net_return"] < low["net_return"]
    assert high["fold_observations"] >= 3

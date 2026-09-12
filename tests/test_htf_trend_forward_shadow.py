from __future__ import annotations

from hashlib import sha256
import json

import numpy as np
import pandas as pd

from orderflow_edge_lab.htf_trend_forward_shadow import (
    build_execution_targets,
    build_forward_report,
    verify_candidate_spec,
)


def _candidate(symbols, start: pd.Timestamp, *, cost_bps: float = 20.0):
    value = {
        "schema_version": 1,
        "candidate_id": "test-trend",
        "frozen_at_utc": (start - pd.Timedelta(hours=1)).isoformat(),
        "forward_signal_start_utc": start.isoformat(),
        "selection_provenance": {},
        "specification": {
            "symbols": list(symbols),
            "fast_ema": 2,
            "slow_ema": 4,
            "atr_period": 2,
            "min_atr_spread": 0.0,
            "round_trip_cost_bps": cost_bps,
            "gross_portfolio_exposure_cap": 1.0,
            "leverage": 1.0,
        },
        "forward_protocol": {"minimum_completed_forward_trades_for_edge_review": 20},
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    value["spec_sha256"] = sha256(raw).hexdigest()
    return value


def _frame(index: pd.DatetimeIndex, slope: float = 0.01):
    close = 100.0 * np.exp(np.arange(len(index)) * slope)
    open_ = close * (1.0 + 0.0001)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": np.ones(len(index)),
        },
        index=index,
    )


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

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
    open_ = close * 0.999
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


def test_candidate_hash_and_first_execution_are_causal():
    idx = pd.date_range("2026-08-01", periods=140, freq="8h", tz="UTC")
    start = idx[110]
    candidate = _candidate(["A"], start)
    assert verify_candidate_spec(candidate)
    as_of = idx[115] + pd.Timedelta(hours=2)
    targets = build_execution_targets(_frame(idx), candidate, as_of_utc=as_of)
    assert len(targets) > 0
    assert targets.index.min() == start + pd.Timedelta(hours=8)
    assert not (targets.index <= start).any()


def test_positive_funding_debits_long_forward_portfolio():
    idx = pd.date_range("2026-08-01", periods=140, freq="8h", tz="UTC")
    start = idx[110]
    symbols = ["A", "B", "C", "D"]
    candidate = _candidate(symbols, start, cost_bps=20.0)
    frames = {symbol: _frame(idx, 0.004 + i * 0.0001) for i, symbol in enumerate(symbols)}
    as_of = idx[116] + pd.Timedelta(hours=4)
    empty_funding = {
        symbol: pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC"))
        for symbol in symbols
    }
    baseline = build_forward_report(frames, empty_funding, candidate, as_of_utc=as_of)

    funding_index = pd.DatetimeIndex([start + pd.Timedelta(hours=16), start + pd.Timedelta(hours=24)])
    positive_funding = {
        symbol: pd.DataFrame({"funding_rate": [0.001, 0.001]}, index=funding_index)
        for symbol in symbols
    }
    charged = build_forward_report(frames, positive_funding, candidate, as_of_utc=as_of)
    assert baseline["metrics"]["net_return"] > charged["metrics"]["net_return"]
    assert any(row["funding_return"] < 0 for row in charged["portfolio_intervals"])
    assert charged["claims"]["live_order_transmission_supported"] is False
    assert charged["claims"]["profitable_edge_established"] is False

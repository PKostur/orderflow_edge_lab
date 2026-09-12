from __future__ import annotations

import json
from hashlib import sha256

import pandas as pd

from orderflow_edge_lab.cross_sectional_forward_shadow import (
    build_forward_report,
    build_rebalance_weights,
    verify_candidate_spec,
)


def _candidate(start: str = "2026-09-13T00:00:00Z") -> dict:
    payload = {
        "schema_version": 1,
        "candidate_id": "test_xs",
        "frozen_at_utc": "2026-09-12T18:20:42Z",
        "forward_signal_start_utc": start,
        "selection_provenance": {},
        "specification": {
            "symbols": [f"S{i}_USDT" for i in range(8)],
            "lookback_days": 30,
            "holding_days": 7,
            "quantile_fraction": 0.25,
            "round_trip_cost_bps": 20.0,
            "gross_portfolio_exposure_cap": 1.0,
            "leverage": 1.0,
        },
        "forward_protocol": {
            "first_possible_execution_utc": "2026-09-14T00:00:00Z",
            "minimum_completed_forward_rebalances_for_edge_review": 10,
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    payload["spec_sha256"] = sha256(raw).hexdigest()
    return payload


def _frames() -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2026-07-20", "2026-09-16", freq="1D", tz="UTC")
    out = {}
    for i in range(8):
        base = 100.0 + i * 3.0
        slope = (i - 3.5) * 0.002
        closes = [base * (1.0 + slope * j) for j in range(len(idx))]
        opens = [v * 0.999 for v in closes]
        out[f"S{i}_USDT"] = pd.DataFrame({"open": opens, "close": closes}, index=idx)
    return out


def test_candidate_hash_and_forward_boundary() -> None:
    candidate = _candidate()
    assert verify_candidate_spec(candidate)
    frames = _frames()
    before = build_rebalance_weights(frames, candidate, as_of_utc="2026-09-13T23:00:00Z")
    assert before == {}
    after = build_rebalance_weights(frames, candidate, as_of_utc="2026-09-14T01:00:00Z")
    assert list(after) == [pd.Timestamp("2026-09-14T00:00:00Z")]
    weights = next(iter(after.values()))
    assert abs(float(weights.abs().sum()) - 1.0) < 1e-12
    assert abs(float(weights.sum())) < 1e-12


def test_report_is_paper_only_and_cost_aware() -> None:
    candidate = _candidate()
    frames = _frames()
    funding = {symbol: pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC")) for symbol in frames}
    report = build_forward_report(frames, funding, candidate, as_of_utc="2026-09-15T12:00:00Z")
    assert report["status"] == "collecting"
    assert report["metrics"]["executed_rebalances"] == 1
    assert report["metrics"]["open_symbol_positions"] == 4
    assert report["economics"]["round_trip_cost_bps"] == 20.0
    assert report["claims"]["paper_shadow_only"] is True
    assert report["claims"]["profitable_edge_established"] is False
    assert report["claims"]["live_order_transmission_supported"] is False

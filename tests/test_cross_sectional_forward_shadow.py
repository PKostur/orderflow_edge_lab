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
    assert "symbol_diagnostics" in report
    assert set(report["symbol_diagnostics"]) == set(frames)
    total_symbol_net = sum(
        row["arithmetic_net_contribution_sum"]
        for row in report["symbol_diagnostics"].values()
    )
    total_interval_net = sum(row["net_return"] for row in report["portfolio_intervals"])
    assert abs(total_symbol_net - total_interval_net) < 1e-12
    assert sum(
        row["allocated_trading_cost_return_sum"]
        for row in report["symbol_diagnostics"].values()
    ) < 0.0
    concentration = report["contribution_concentration"]
    assert concentration["active_contributor_count"] == 4
    assert concentration["absolute_contribution_hhi"] is not None
    assert concentration["largest_absolute_contributor"] is not None
    assert len(concentration["contributor_removal_stress"]) == 4
    top = concentration["largest_absolute_contributor"]
    assert abs(
        concentration["arithmetic_net_without_largest_absolute_contributor"]
        - (total_symbol_net - top["contribution"])
    ) < 1e-12
    if total_symbol_net > 0.0:
        assert (
            concentration["positive_net_survives_removing_largest_absolute_contributor"]
            == (
                concentration["arithmetic_net_without_largest_absolute_contributor"]
                > 0.0
            )
        )
    assert abs(
        concentration["arithmetic_net_contribution_sum"] - total_symbol_net
    ) < 1e-12
    assert report["claims"]["paper_shadow_only"] is True
    assert report["claims"]["contribution_concentration_diagnostics_are_non_gating"] is True
    assert report["claims"]["contributor_removal_stress_is_attribution_not_counterfactual_strategy"] is True
    assert report["claims"]["profitable_edge_established"] is False
    assert report["claims"]["live_order_transmission_supported"] is False


def test_completed_holding_period_decomposition_reconciles() -> None:
    candidate = _candidate()
    frames = _frames()
    funding = {
        symbol: pd.DataFrame(
            columns=["funding_rate"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        for symbol in frames
    }
    report = build_forward_report(
        frames,
        funding,
        candidate,
        as_of_utc="2026-09-22T12:00:00Z",
    )
    assert report["metrics"]["completed_holding_periods"] == 1
    assert len(report["completed_holding_periods"]) == 1
    period = report["completed_holding_periods"][0]
    assert period["daily_interval_count"] == 7
    matching = [
        row["net_return"]
        for row in report["portfolio_intervals"]
        if pd.Timestamp(row["start"]) >= pd.Timestamp(period["start"])
        and pd.Timestamp(row["end"]) <= pd.Timestamp(period["end"])
    ]
    expected = 1.0
    for value in matching:
        expected *= 1.0 + value
    expected -= 1.0
    assert abs(period["net_return"] - expected) < 1e-12
    symbol_sum = sum(period["symbol_arithmetic_net_contributions"].values())
    interval_sum = sum(matching)
    assert abs(symbol_sum - interval_sum) < 1e-12
    period_concentration = period["contribution_concentration"]
    assert abs(
        period_concentration["arithmetic_net_contribution_sum"] - interval_sum
    ) < 1e-12
    assert period_concentration["largest_absolute_contributor"] is not None
    assert period_concentration["contributor_removal_stress"]
    top = period_concentration["largest_absolute_contributor"]
    assert abs(
        period_concentration["arithmetic_net_without_largest_absolute_contributor"]
        - (interval_sum - top["contribution"])
    ) < 1e-12

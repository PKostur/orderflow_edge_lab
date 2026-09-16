from __future__ import annotations

import pandas as pd
import pytest

from orderflow_edge_lab.cross_exchange_funding import (
    FundingDispersionSpec,
    build_symbol_daily_returns,
)


def _prices(values, start="2026-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="1D", tz="UTC")
    return pd.DataFrame({
        "open": values,
        "high": values,
        "low": values,
        "close": values,
        "volume": [1.0] * len(values),
    }, index=idx)


def _funding(daily_values, start="2025-12-20"):
    rows = []
    for day, value in enumerate(daily_values):
        base = pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=day)
        for hour in (8, 16, 23):
            rows.append((base + pd.Timedelta(hours=hour), float(value) / 3.0))
    return pd.DataFrame(rows, columns=["timestamp", "funding_rate"]).set_index("timestamp")


def test_positive_mexc_funding_spread_selects_short_mexc_long_binance():
    mexc_prices = _prices([100.0] * 6)
    binance_prices = _prices([100.0] * 6)
    mexc_funding = _funding([0.003] * 30)
    binance_funding = _funding([0.0] * 30)
    spec = FundingDispersionSpec(
        funding_lookback_days=7,
        minimum_history_days=5,
        break_even_projection_days=7,
        safety_multiple_over_cost=1.0,
        gross_exposure=1.0,
        round_trip_pair_cost_bps=20.0,
    )
    result = build_symbol_daily_returns(mexc_prices, binance_prices, mexc_funding, binance_funding, spec)
    assert (result["side"] == 1).any()
    active = result[result["side"] == 1]
    assert (active["funding_component"] > 0).all()


def test_cross_venue_price_divergence_is_included_not_ignored():
    mexc_prices = _prices([100.0, 110.0, 110.0, 110.0, 110.0, 110.0])
    binance_prices = _prices([100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    mexc_funding = _funding([0.003] * 30)
    binance_funding = _funding([0.0] * 30)
    spec = FundingDispersionSpec(
        funding_lookback_days=7,
        minimum_history_days=5,
        break_even_projection_days=7,
        safety_multiple_over_cost=1.0,
        gross_exposure=1.0,
        round_trip_pair_cost_bps=20.0,
    )
    result = build_symbol_daily_returns(mexc_prices, binance_prices, mexc_funding, binance_funding, spec)
    active = result[result["side"] == 1]
    assert len(active) > 0
    # Short MEXC / long Binance loses when MEXC rises relative to Binance.
    if active.iloc[0]["mexc_open_return"] > active.iloc[0]["binance_open_return"]:
        assert active.iloc[0]["price_component"] < 0


def test_future_funding_cannot_change_earlier_signal():
    mexc_prices = _prices([100.0] * 8)
    binance_prices = _prices([100.0] * 8)
    base_mexc = _funding([0.003] * 30)
    binance = _funding([0.0] * 30)
    spec = FundingDispersionSpec(
        funding_lookback_days=7,
        minimum_history_days=5,
        break_even_projection_days=7,
        safety_multiple_over_cost=1.0,
        gross_exposure=1.0,
        round_trip_pair_cost_bps=20.0,
    )
    first = build_symbol_daily_returns(mexc_prices, binance_prices, base_mexc, binance, spec)
    changed = base_mexc.copy()
    cutoff = pd.Timestamp("2026-01-04", tz="UTC")
    changed.loc[changed.index >= cutoff, "funding_rate"] = -1.0
    second = build_symbol_daily_returns(mexc_prices, binance_prices, changed, binance, spec)
    earlier = first.index < cutoff
    pd.testing.assert_series_equal(first.loc[earlier, "side"], second.loc[earlier, "side"])


def test_reverse_control_flips_side_but_keeps_gate_timing():
    mexc_prices = _prices([100.0] * 8)
    binance_prices = _prices([100.0] * 8)
    mexc_funding = _funding([0.003] * 30)
    binance_funding = _funding([0.0] * 30)
    spec = FundingDispersionSpec(
        funding_lookback_days=7,
        minimum_history_days=5,
        break_even_projection_days=7,
        safety_multiple_over_cost=1.0,
        gross_exposure=1.0,
        round_trip_pair_cost_bps=20.0,
    )
    normal = build_symbol_daily_returns(mexc_prices, binance_prices, mexc_funding, binance_funding, spec)
    reverse = build_symbol_daily_returns(mexc_prices, binance_prices, mexc_funding, binance_funding, spec, reverse_control=True)
    assert (normal["side"] == -reverse["side"]).all()
    assert (normal["side"].ne(0) == reverse["side"].ne(0)).all()


def test_open_and_close_cost_sum_to_round_trip_pair_cost():
    mexc_prices = _prices([100.0] * 6)
    binance_prices = _prices([100.0] * 6)
    mexc_funding = _funding([0.003] * 30)
    binance_funding = _funding([0.0] * 30)
    spec = FundingDispersionSpec(
        funding_lookback_days=7,
        minimum_history_days=5,
        break_even_projection_days=7,
        safety_multiple_over_cost=1.0,
        gross_exposure=1.0,
        round_trip_pair_cost_bps=30.0,
    )
    result = build_symbol_daily_returns(mexc_prices, binance_prices, mexc_funding, binance_funding, spec)
    if (result["side"] != 0).any():
        assert result["transition_cost"].sum() == pytest.approx(30.0 / 10_000.0)

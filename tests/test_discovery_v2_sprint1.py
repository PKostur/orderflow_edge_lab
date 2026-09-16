from __future__ import annotations

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint1 import (
    VariantRun,
    btc_residual_shock_reversal,
    dispersion_conditioned_xs_momentum,
    evaluate_family,
    funding_extreme_reversal,
)


def _daily_frames(days: int = 280) -> dict[str, pd.DataFrame]:
    index = pd.date_range("2025-01-01", periods=days, freq="1D", tz="UTC")
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]
    out = {}
    x = np.arange(days, dtype=float)
    for j, symbol in enumerate(symbols):
        close = 100.0 * np.exp(0.0005 * x + 0.025 * np.sin(x / (7.0 + j * 0.2) + j))
        open_ = close * (1.0 + 0.002 * np.sin(x / 5.0 + j / 3.0))
        out[symbol] = pd.DataFrame({"open": open_, "close": close}, index=index)
    return out


def _zero_funding(index: pd.DatetimeIndex, symbols: list[str]) -> dict[str, pd.DataFrame]:
    settlement = pd.date_range(index.min(), index.max(), freq="8h", tz="UTC")
    return {s: pd.DataFrame({"funding_rate": np.zeros(len(settlement))}, index=settlement) for s in symbols}


def test_daily_families_produce_causal_completed_observations() -> None:
    frames = _daily_frames()
    symbols = list(frames)
    funding = _zero_funding(next(iter(frames.values())).index, symbols)
    dispersion = dispersion_conditioned_xs_momentum(
        frames,
        symbols=symbols,
        funding_frames=funding,
        dispersion_lookback_days=60,
        momentum_lookback_days=30,
        holding_days=7,
        side_cost_bps=10.0,
    )
    residual = btc_residual_shock_reversal(
        frames,
        symbols=symbols,
        funding_frames=funding,
        beta_lookback_days=30,
        side_cost_bps=10.0,
    )
    assert not dispersion.observations.empty
    assert not residual.observations.empty
    assert (pd.to_datetime(dispersion.observations["end_timestamp"], utc=True) > dispersion.observations.index).all()
    assert (pd.to_datetime(residual.observations["end_timestamp"], utc=True) > residual.observations.index).all()
    assert float(dispersion.observations["active_gross"].max()) <= 1.0 + 1e-12
    assert float(residual.observations["active_gross"].max()) <= 1.0 + 1e-12


def test_funding_future_rate_changes_economics_not_entry_activity() -> None:
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT"]
    hourly_index = pd.date_range("2025-01-01", periods=24 * 70, freq="1h", tz="UTC")
    hourly = {}
    for j, symbol in enumerate(symbols):
        price = 100.0 + np.arange(len(hourly_index), dtype=float) * (0.001 + j * 0.0001)
        hourly[symbol] = pd.DataFrame({"open": price, "close": price}, index=hourly_index)
    settlements = pd.date_range("2025-01-01", periods=200, freq="8h", tz="UTC")
    base = 0.00005 * np.sin(np.arange(len(settlements)) / 3.0)
    base[40] = 0.0025
    funding_a = {s: pd.DataFrame({"funding_rate": base.copy()}, index=settlements) for s in symbols}
    funding_b = {s: frame.copy() for s, frame in funding_a.items()}
    # Change only the rate paid at the settlement AFTER the known extreme signal.
    for symbol in symbols:
        funding_b[symbol].iloc[41, 0] += 0.003
    run_a = funding_extreme_reversal(hourly, funding_a, symbols=symbols, lookback_settlements=20, z_threshold_abs=2.0)
    run_b = funding_extreme_reversal(hourly, funding_b, symbols=symbols, lookback_settlements=20, z_threshold_abs=2.0)
    row_a = run_a.observations.loc[settlements[40]]
    row_b = run_b.observations.loc[settlements[40]]
    assert int(row_a["active_symbols"]) == int(row_b["active_symbols"]) == len(symbols)
    assert float(row_a["gross_return_bps"]) != float(row_b["gross_return_bps"])


def _variant_run(mean_gross: float, mean_cost: float, symbols: list[str]) -> VariantRun:
    timestamps = pd.date_range("2020-01-05", periods=120, freq="7D", tz="UTC")
    wave = 2.0 * np.sin(np.arange(len(timestamps)) / 5.0)
    gross = mean_gross + wave
    cost = np.full(len(timestamps), mean_cost)
    net = gross - cost
    obs = pd.DataFrame(
        {
            "gross_return_bps": gross,
            "cost_bps": cost,
            "net_return_bps": net,
            "end_timestamp": timestamps + pd.Timedelta(days=7),
        },
        index=timestamps,
    )
    contributions = []
    for ts, value in zip(timestamps, net):
        for symbol in symbols:
            contributions.append({"timestamp": ts, "symbol": symbol, "net_contribution_bps": float(value) / len(symbols)})
    return VariantRun(obs, pd.DataFrame(contributions))


def test_family_gate_requires_breadth_neighborhood_control_and_concentration() -> None:
    symbols = ["A", "B", "C", "D"]
    variants = {
        "v1": _variant_run(30.0, 10.0, symbols),
        "v2": _variant_run(31.0, 10.0, symbols),
        "v3": _variant_run(32.0, 10.0, symbols),
        "v4": _variant_run(33.0, 10.0, symbols),
    }
    controls = {f"reverse_{v}": _variant_run(4.0, 10.0, symbols) for v in variants}
    evaluation = {
        "statistics": {
            "block_bootstrap_resamples": 200,
            "block_bootstrap_length": 5,
            "confidence_level": 0.95,
            "cscv_partitions": 8,
            "minimum_variants_for_pbo": 4,
            "deflated_sharpe_min_probability": 0.95,
            "pbo_max": 0.2,
            "reality_check_max_p": 0.1,
        },
        "economics": {"cost_multipliers": [1.0, 1.5, 2.0], "minimum_break_even_to_base_cost_ratio": 1.5},
        "concentration": {
            "maximum_best_symbol_positive_pnl_share": 0.5,
            "maximum_best_calendar_month_positive_pnl_share": 0.5,
            "maximum_top5_positive_pnl_share": 0.5,
            "leave_one_symbol_out_expectancy_must_remain_positive": True,
        },
    }
    report = evaluate_family(
        variants,
        controls,
        ordered_variant_ids=["v1", "v2", "v3", "v4"],
        evaluation_config=evaluation,
        principal_control_for_variant={v: f"reverse_{v}" for v in variants},
    )
    assert report["state"] == "REPLICATION_PENDING"
    assert all(report["hard_checks"].values())
    assert report["selected_variant_if_survived"] == "v3"

from __future__ import annotations

import numpy as np
import pandas as pd

from orderflow_edge_lab.volume_momentum_forward import observations_sha256, simulate_forward


SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fixtures(days: int = 90):
    idx = pd.date_range("2026-07-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2026-07-01", periods=days * 3, freq="8h", tz="UTC")
    frames = {}
    funding = {}
    for j, symbol in enumerate(SYMBOLS):
        t = np.arange(days, dtype=float)
        close = 100.0 * np.exp((j - 4.5) * 0.0003 * t + 0.012 * np.sin(t / (3.0 + j * 0.12)))
        open_ = close * (1.0 + 0.001 * np.cos(t / 4.0 + j))
        volume = 1000.0 + 30.0 * j + 120.0 * (1.0 + np.sin(t / (4.0 + j * 0.08)))
        frames[symbol] = pd.DataFrame({"open": open_, "close": close, "volume": volume}, index=idx)
        funding[symbol] = pd.DataFrame({"funding_rate": np.full(len(fidx), (j - 4.5) * 1e-6)}, index=fidx)
    return frames, funding


def test_no_pre_start_pnl_and_flat_forward_boundary():
    frames, funding = _fixtures()
    forward_start = pd.Timestamp("2026-08-20T00:00:00Z")
    before = simulate_forward(
        frames, funding, symbols=SYMBOLS, volume_baseline_days=30,
        forward_start=forward_start, asof=pd.Timestamp("2026-08-19T23:59:59Z"),
        side_cost_bps=10.0,
    )
    assert before["observations"].empty
    assert before["open_position"] is None

    after = simulate_forward(
        frames, funding, symbols=SYMBOLS, volume_baseline_days=30,
        forward_start=forward_start, asof=pd.Timestamp("2026-08-22T00:00:00Z"),
        side_cost_bps=10.0,
    )
    assert not after["observations"].empty
    assert after["observations"].index.min() >= forward_start
    assert float(after["observations"].iloc[0]["cost_bps"]) == 10.0


def test_no_terminal_liquidation_cost():
    frames, funding = _fixtures()
    forward_start = pd.Timestamp("2026-08-20T00:00:00Z")
    run = simulate_forward(
        frames, funding, symbols=SYMBOLS, volume_baseline_days=30,
        forward_start=forward_start, asof=pd.Timestamp("2026-08-23T12:00:00Z"),
        side_cost_bps=10.0,
    )
    assert run["open_position"] is not None
    assert run["open_position"]["entry_cost_bps"] >= 0.0
    assert (run["observations"]["cost_bps"] <= 20.0 + 1e-12).all()


def test_later_data_does_not_change_completed_forward_prefix():
    frames, funding = _fixtures()
    forward_start = pd.Timestamp("2026-08-20T00:00:00Z")
    earlier_asof = pd.Timestamp("2026-08-25T00:00:00Z")
    first = simulate_forward(
        frames, funding, symbols=SYMBOLS, volume_baseline_days=30,
        forward_start=forward_start, asof=earlier_asof, side_cost_bps=10.0,
    )
    changed = {k: v.copy() for k, v in frames.items()}
    for symbol in SYMBOLS:
        changed[symbol].loc[changed[symbol].index > earlier_asof, "close"] *= 3.0
        changed[symbol].loc[changed[symbol].index > earlier_asof, "volume"] *= 9.0
    second = simulate_forward(
        changed, funding, symbols=SYMBOLS, volume_baseline_days=30,
        forward_start=forward_start, asof=earlier_asof + pd.Timedelta(days=4), side_cost_bps=10.0,
    )
    prefix = second["observations"].loc[second["observations"]["end_timestamp"] <= earlier_asof]
    pd.testing.assert_frame_equal(first["observations"], prefix)
    assert observations_sha256(first["observations"]) == observations_sha256(prefix)


def test_reversed_control_has_same_forward_timing():
    frames, funding = _fixtures()
    kwargs = dict(
        frames=frames, funding_frames=funding, symbols=SYMBOLS,
        volume_baseline_days=30, forward_start=pd.Timestamp("2026-08-20T00:00:00Z"),
        asof=pd.Timestamp("2026-08-28T00:00:00Z"), side_cost_bps=10.0,
    )
    exact = simulate_forward(reverse=False, **kwargs)
    control = simulate_forward(reverse=True, **kwargs)
    assert exact["observations"].index.equals(control["observations"].index)
    assert exact["observations"]["end_timestamp"].equals(control["observations"]["end_timestamp"])

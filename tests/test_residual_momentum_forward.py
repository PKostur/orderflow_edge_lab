import numpy as np
import pandas as pd

from orderflow_edge_lab.residual_momentum_forward import simulate_forward


def _frames(days=70):
    idx = pd.date_range("2026-07-01", periods=days, freq="D", tz="UTC")
    symbols = ["BTC_USDT", "A_USDT", "B_USDT", "C_USDT", "D_USDT"]
    out = {}
    for j, s in enumerate(symbols):
        ret = 0.001*np.sin(np.arange(days)/3 + j) + 0.0003*j
        close = 100*np.cumprod(1+ret)
        out[s] = pd.DataFrame({"open": close*(1-0.0002), "close": close}, index=idx)
    return symbols, out


def test_forward_start_has_no_backfill_and_completed_history_is_stable():
    symbols, frames = _frames()
    funding = {s: pd.DataFrame({"funding_rate": []}, index=pd.DatetimeIndex([], tz="UTC")) for s in symbols}
    start = pd.Timestamp("2026-08-25", tz="UTC")
    a = simulate_forward(frames, funding, symbols=symbols, lookback=20, forward_start=start,
                         asof=pd.Timestamp("2026-09-03T12:00:00Z"), side_cost_bps=10, reverse=True)
    b = simulate_forward(frames, funding, symbols=symbols, lookback=20, forward_start=start,
                         asof=pd.Timestamp("2026-09-04T12:00:00Z"), side_cost_bps=10, reverse=True)
    assert not a["observations"].empty
    assert a["observations"].index.min() >= start
    common = a["observations"].index.intersection(b["observations"].index)
    pd.testing.assert_frame_equal(a["observations"].loc[common], b["observations"].loc[common])

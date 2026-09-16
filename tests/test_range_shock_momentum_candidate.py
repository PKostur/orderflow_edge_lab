from __future__ import annotations

import numpy as np
import pandas as pd

from orderflow_edge_lab.range_shock_momentum_candidate import run_range_shock_momentum_candidate

SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fixtures(days: int = 100):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2026-01-01", periods=days*3, freq="8h", tz="UTC")
    t = np.arange(days, dtype=float); daily, funding = {}, {}
    for j, s in enumerate(SYMBOLS):
        close = 100*np.exp((j-4.5)*0.0002*t + 0.02*np.sin(t/(4+j*0.1)+j))
        open_ = close*(1+0.003*np.cos(t/5+j))
        width = 0.008+0.004*(1+np.sin(t/7+j))
        high = np.maximum(open_, close)*(1+width); low = np.minimum(open_, close)*(1-width)
        daily[s] = pd.DataFrame({"open":open_,"high":high,"low":low,"close":close}, index=idx)
        funding[s] = pd.DataFrame({"funding_rate": np.full(days*3, (j-4.5)*0.000001)}, index=fidx)
    return daily, funding


def test_candidate_next_open_and_one_x():
    daily, funding = _fixtures()
    run = run_range_shock_momentum_candidate(daily, symbols=SYMBOLS, funding_frames=funding, range_baseline_days=30, fixed_evaluation_warmup_days=45, side_cost_bps=10.0)
    assert len(run.observations) == 53
    assert (run.observations["active_gross"] <= 1.0 + 1e-12).all()
    assert (pd.to_datetime(run.observations["end_timestamp"]) > run.observations.index).all()
    assert np.isfinite(run.observations["net_return_bps"]).all()
    assert np.allclose(run.weights.abs().sum(axis=1).to_numpy(), 1.0)
    assert np.allclose(run.weights.sum(axis=1).to_numpy(), 0.0)


def test_reversed_control_has_same_timing():
    daily, funding = _fixtures()
    kwargs = dict(daily_frames=daily, symbols=SYMBOLS, funding_frames=funding, range_baseline_days=30, fixed_evaluation_warmup_days=45, side_cost_bps=10.0)
    a = run_range_shock_momentum_candidate(**kwargs, reverse=False)
    b = run_range_shock_momentum_candidate(**kwargs, reverse=True)
    assert a.observations.index.equals(b.observations.index)
    assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"])
    assert np.allclose(a.weights.to_numpy(), -b.weights.to_numpy())

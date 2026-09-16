from __future__ import annotations
import numpy as np, pandas as pd
from orderflow_edge_lab.range_shock_momentum_forward import simulate_forward, summarize

SYMBOLS=["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT","BNB_USDT","ADA_USDT","LINK_USDT","SUI_USDT","ENA_USDT"]

def _fixtures(days=80):
    idx=pd.date_range("2026-07-01",periods=days,freq="1D",tz="UTC"); fidx=pd.date_range("2026-07-01",periods=days*3,freq="8h",tz="UTC"); t=np.arange(days,dtype=float); d={}; f={}
    for j,s in enumerate(SYMBOLS):
        close=100*np.exp((j-4.5)*.0002*t+.015*np.sin(t/(4+j*.1)+j)); open_=close*(1+.003*np.cos(t/5+j)); w=.008+.003*(1+np.sin(t/7+j)); high=np.maximum(open_,close)*(1+w); low=np.minimum(open_,close)*(1-w)
        d[s]=pd.DataFrame({"open":open_,"high":high,"low":low,"close":close},index=idx); f[s]=pd.DataFrame({"funding_rate":np.zeros(days*3)},index=fidx)
    return d,f

def test_no_pre_start_pnl():
    d,f=_fixtures(); start=pd.Timestamp("2026-09-17T00:00:00Z"); r=simulate_forward(d,f,symbols=SYMBOLS,range_baseline_days=30,forward_start=start,asof=pd.Timestamp("2026-09-16T18:00:00Z"),side_cost_bps=10.0)
    s=summarize(r); assert s["completed_periods"]==0; assert s["pnl_per_1000"]==0.0; assert s["open_position"] is None

def test_completed_periods_start_at_frozen_boundary_and_no_terminal_liquidation():
    d,f=_fixtures(); start=pd.Timestamp("2026-08-15T00:00:00Z"); r=simulate_forward(d,f,symbols=SYMBOLS,range_baseline_days=30,forward_start=start,asof=pd.Timestamp("2026-09-10T12:00:00Z"),side_cost_bps=10.0)
    s=summarize(r); assert s["completed_periods"]>0; assert pd.Timestamp(s["start"])>=start; assert s["open_position"] is not None; assert float(r["observations"].iloc[-1]["cost_bps"])<=20.0+1e-12

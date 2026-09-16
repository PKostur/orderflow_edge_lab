from __future__ import annotations

import json
from pathlib import Path
import numpy as np, pandas as pd
from orderflow_edge_lab.discovery_v2_sprint6 import wick_rejection_followthrough, return_efficiency_continuation, realized_semivariance_balance

SYMBOLS=["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT","BNB_USDT","ADA_USDT","LINK_USDT","SUI_USDT","ENA_USDT"]

def _fixtures(days=100):
    idx=pd.date_range("2026-01-01",periods=days,freq="1D",tz="UTC"); fidx=pd.date_range("2026-01-01",periods=days*3,freq="8h",tz="UTC"); t=np.arange(days,dtype=float); daily={}; funding={}
    for j,s in enumerate(SYMBOLS):
        close=100*np.exp((j-4.5)*0.0002*t+0.018*np.sin(t/(4+j*.1)+j)); open_=close*(1+0.004*np.cos(t/6+j)); spread=.008+.003*(1+np.sin(t/7+j)); high=np.maximum(open_,close)*(1+spread); low=np.minimum(open_,close)*(1-spread)
        daily[s]=pd.DataFrame({"open":open_,"high":high,"low":low,"close":close},index=idx); funding[s]=pd.DataFrame({"funding_rate":np.full(days*3,(j-4.5)*1e-6)},index=fidx)
    return daily,funding

def test_protocol_frozen_and_trial_count():
    p=json.loads(Path("config/discovery_v2_sprint6_v1.json").read_text()); assert p["status"]=="FROZEN_BEFORE_MARKET_RESULTS"; assert p["execution"]["leverage"]==1.0; assert p["trial_accounting"]["directional_candidate_variants_added_this_sprint"]==12; assert p["trial_accounting"]["sequential_discovery_debt_acknowledged"] is True; assert p["trial_accounting"]["no_grid_expansion_after_results"] is True; assert p["claims"]["persistent_edge_established"] is False

def test_engines_emit_next_open_one_x():
    d,f=_fixtures(); runs=[
      wick_rejection_followthrough(d,symbols=SYMBOLS,funding_frames=f,lookback_days=5,common_warmup_days=10,side_cost_bps=10.0),
      return_efficiency_continuation(d,symbols=SYMBOLS,funding_frames=f,lookback_days=20,common_warmup_days=40,side_cost_bps=10.0),
      realized_semivariance_balance(d,symbols=SYMBOLS,funding_frames=f,lookback_days=20,common_warmup_days=40,side_cost_bps=10.0)]
    for r in runs:
        assert len(r.observations)>20; assert (r.observations["active_gross"]<=1.0+1e-12).all(); assert np.isfinite(r.observations["net_return_bps"]).all(); assert (pd.to_datetime(r.observations["end_timestamp"])>r.observations.index).all()

def test_reverse_preserves_timing():
    d,f=_fixtures(); kw=dict(daily_frames=d,symbols=SYMBOLS,funding_frames=f,lookback_days=5,common_warmup_days=10,side_cost_bps=10.0); a=wick_rejection_followthrough(**kw,reverse=False); b=wick_rejection_followthrough(**kw,reverse=True); assert a.observations.index.equals(b.observations.index); assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"])

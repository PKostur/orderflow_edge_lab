from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint13 import run_payoff_meta

SYMBOLS=["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT","BNB_USDT","ADA_USDT","LINK_USDT","SUI_USDT","ENA_USDT"]

def _fixtures(days=285):
    idx=pd.date_range("2026-01-01",periods=days,freq="1D",tz="UTC"); fidx=pd.date_range("2025-12-15",periods=(days+20)*3,freq="8h",tz="UTC"); t=np.arange(days,dtype=float); daily={}; funding={}
    for j,s in enumerate(SYMBOLS):
        factor=0.0045*np.sin(t/7.0)+0.0025*np.cos(t/17.0); idio=0.007*np.sin(t/(2.3+0.11*j)+0.73*j)+0.003*np.cos(t/(5.5+0.2*j)+j); regime=np.where((t.astype(int)//35)%2==0,1.0,-0.65); ret=factor*(0.7+0.04*j)+idio*regime+(j-4.5)*0.00008; close=(80+7*j)*np.cumprod(1+ret); open_=close*(1+0.002*np.sin(t/3+0.4*j)); daily[s]=pd.DataFrame({"open":open_,"high":np.maximum(open_,close)*1.01,"low":np.minimum(open_,close)*0.99,"close":close},index=idx); k=np.arange(len(fidx),dtype=float); funding[s]=pd.DataFrame({"funding_rate":2e-5*np.sin(k/(11+j))+(j-4.5)*1.5e-6},index=fidx)
    return daily,funding

def test_protocol_is_single_frozen_payoff_rule():
    p=json.loads(Path("config/discovery_v2_sprint13_payoff_meta_v1.json").read_text()); assert p["status"]=="FROZEN_BEFORE_MARKET_RESULTS"; assert p["walk_forward_model"]["ridge_alpha"]==10.0; assert p["walk_forward_model"]["training_window_prior_primary_setups"]==80; assert p["walk_forward_model"]["minimum_prior_primary_setups"]==60; assert p["walk_forward_model"]["trade_if_predicted_standalone_net_bps_greater_than"]==0.0; assert p["trial_accounting"]["directional_candidate_rules_added_this_sprint"]==1; assert p["trial_accounting"]["Sprint12_remains_closed"] is True

def test_payoff_meta_is_causal_and_one_x():
    d,f=_fixtures(); r=run_payoff_meta(d,symbols=SYMBOLS,funding_frames=f,side_cost_bps=10.0,ridge_alpha=10.0,training_window=80,minimum_training=60,trade_threshold_bps=0.0); p=pd.to_numeric(r.predictions["predicted_standalone_net_bps"],errors="coerce"); assert p.notna().sum()>20; q=r.predictions.loc[p.notna()]; assert (q["trade"].to_numpy()==(q["predicted_standalone_net_bps"].to_numpy()>0.0)).all(); assert r.candidate.observations.index.equals(r.reversed_same_decisions.observations.index); assert (r.candidate.observations["active_gross"]<=1.0+1e-12).all(); assert np.isfinite(r.candidate.observations["net_return_bps"]).all()

def test_same_open_previous_outcome_does_not_change_current_prediction():
    d,f=_fixtures(); base=run_payoff_meta(d,symbols=SYMBOLS,funding_frames=f,side_cost_bps=10.0); finite=base.predictions.loc[np.isfinite(pd.to_numeric(base.predictions["predicted_standalone_net_bps"],errors="coerce"))]; row=finite.iloc[min(5,len(finite)-1)]; entry=pd.Timestamp(row["start_timestamp"]); changed={k:v.copy() for k,v in d.items()}
    for j,s in enumerate(SYMBOLS): changed[s].loc[entry,"open"]*=0.82+0.04*j
    alt=run_payoff_meta(changed,symbols=SYMBOLS,funding_frames=f,side_cost_bps=10.0); a=base.predictions.loc[pd.to_datetime(base.predictions["start_timestamp"],utc=True)==entry].iloc[0]; b=alt.predictions.loc[pd.to_datetime(alt.predictions["start_timestamp"],utc=True)==entry].iloc[0]; assert np.isclose(float(a["predicted_standalone_net_bps"]),float(b["predicted_standalone_net_bps"]),atol=1e-12,rtol=0.0); assert bool(a["trade"])==bool(b["trade"])

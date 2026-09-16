from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint11 import (
    selective_trend_acceleration_5d,
    selective_low_skew_90d,
    selective_funding_carry_14d,
)

SYMBOLS=["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT","BNB_USDT","ADA_USDT","LINK_USDT","SUI_USDT","ENA_USDT"]


def _fixtures(days=260):
    idx=pd.date_range("2026-01-01",periods=days,freq="1D",tz="UTC")
    fidx=pd.date_range("2026-01-01",periods=days*6,freq="4h",tz="UTC")
    t=np.arange(days,dtype=float); daily={}; funding={}
    for j,s in enumerate(SYMBOLS):
        ret=0.008*np.sin(t/(3.1+0.13*j)+j)+0.004*np.cos(t/(11+0.4*j))+(j-4.5)*0.00010
        close=(90+7*j)*np.cumprod(1+ret)
        open_=close*(1+0.0018*np.cos(t/5+j))
        high=np.maximum(open_,close)*(1.01+0.002*np.sin(t/9+j)**2)
        low=np.minimum(open_,close)*(0.99-0.002*np.cos(t/8+j)**2)
        daily[s]=pd.DataFrame({"open":open_,"high":high,"low":low,"close":close},index=idx)
        ft=np.arange(len(fidx),dtype=float)
        fr=(j-4.5)*2e-6+5e-6*np.sin(ft/(15+j)+j)
        funding[s]=pd.DataFrame({"funding_rate":fr},index=fidx)
    return daily,funding


def test_protocol_freezes_selectivity_without_threshold_grid():
    p=json.loads(Path("config/discovery_v2_sprint11_selective_v1.json").read_text())
    assert p["status"]=="FROZEN_BEFORE_MARKET_RESULTS"
    assert p["trial_accounting"]["directional_candidate_variants_added_this_sprint"]==3
    assert p["opportunity_gate"]["quality_percentile"]==0.75
    assert p["opportunity_gate"]["no_threshold_grid"] is True
    assert p["d0_research_candidate_gate"]["bootstrap_95pct_lower_bound"]=="diagnostic_only_at_D0"
    assert p["post_freeze_validation_gate"]["bootstrap_95pct_lower_bound_positive"] is True
    assert p["claims"]["live_execution_supported"] is False


def _check_selective(fn,warmup):
    d,f=_fixtures()
    kw=dict(daily_frames=d,symbols=SYMBOLS,funding_frames=f,quality_history_days=60,quality_percentile=0.75,common_warmup_days=warmup,side_cost_bps=10.0)
    a=fn(**kw,reverse=False,selective=True)
    r=fn(**kw,reverse=True,selective=True)
    p=fn(**kw,reverse=False,selective=False)
    assert len(a.observations)>60
    assert a.observations.index.equals(r.observations.index)
    assert a.observations["end_timestamp"].equals(r.observations["end_timestamp"])
    assert (a.observations["active_gross"]<=1.0+1e-12).all()
    assert set(np.round(a.observations["active_gross"],8).unique()).issubset({0.0,1.0})
    assert (a.observations["active_gross"]>0).any()
    assert (a.observations["active_gross"]==0).any()
    assert int((a.observations["active_gross"]>0).sum()) <= int((p.observations["active_gross"]>0).sum())
    assert np.isfinite(a.observations["net_return_bps"]).all()


def test_selective_engines_abstain_and_keep_reverse_timing():
    _check_selective(selective_trend_acceleration_5d,10)
    _check_selective(selective_low_skew_90d,90)
    _check_selective(selective_funding_carry_14d,14)


def test_funding_at_execution_boundary_cannot_change_current_setup():
    d,f=_fixtures(); kw=dict(daily_frames=d,symbols=SYMBOLS,funding_frames=f,quality_history_days=60,quality_percentile=0.75,common_warmup_days=14,side_cost_bps=10.0,reverse=False,selective=True)
    base=selective_funding_carry_14d(**kw)
    first_active=base.observations.index[base.observations["active_gross"]>0][0]
    changed={k:v.copy() for k,v in f.items()}
    for s in SYMBOLS:
        changed[s].loc[first_active,"funding_rate"]=0.25
    alt=selective_funding_carry_14d(daily_frames=d,symbols=SYMBOLS,funding_frames=changed,quality_history_days=60,quality_percentile=0.75,common_warmup_days=14,side_cost_bps=10.0,reverse=False,selective=True)
    assert float(base.observations.loc[first_active,"active_gross"])==float(alt.observations.loc[first_active,"active_gross"])
    assert abs(float(base.observations.loc[first_active,"net_return_bps"])-float(alt.observations.loc[first_active,"net_return_bps"]))<1e-10


def test_future_price_mutation_does_not_rewrite_prior_selectivity():
    d,f=_fixtures(); kw=dict(symbols=SYMBOLS,funding_frames=f,quality_history_days=60,quality_percentile=0.75,common_warmup_days=90,side_cost_bps=10.0,reverse=False,selective=True)
    base=selective_low_skew_90d(daily_frames=d,**kw)
    cutoff=base.observations.index[len(base.observations)//2]
    changed={k:v.copy() for k,v in d.items()}
    for s in SYMBOLS:
        mask=changed[s].index>=cutoff
        changed[s].loc[mask,"close"]*=1.7
    alt=selective_low_skew_90d(daily_frames=changed,**kw)
    left=base.observations.loc[base.observations.index<cutoff,"active_gross"]
    right=alt.observations.loc[alt.observations.index<cutoff,"active_gross"]
    pd.testing.assert_series_equal(left,right)

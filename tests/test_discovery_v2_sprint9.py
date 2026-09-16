from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_sprint9 import (
    cross_sectional_funding_carry,
    adaptive_ar1_forecast,
    cross_sectional_low_btc_beta,
)

SYMBOLS=["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT","BNB_USDT","ADA_USDT","LINK_USDT","SUI_USDT","ENA_USDT"]
ALTS=SYMBOLS[1:]


def _fixtures(days=210):
    idx=pd.date_range("2026-01-01",periods=days,freq="1D",tz="UTC"); t=np.arange(days,dtype=float)
    btc_ret=0.008*np.sin(t/4.1)+0.003*np.cos(t/11.0)+0.0008; btc_close=100*np.cumprod(1+btc_ret)
    daily={}; funding={}
    for j,s in enumerate(SYMBOLS):
        own=btc_ret if j==0 else (0.35+0.08*j)*btc_ret+0.004*np.sin(t/(2.7+0.1*j)+j)+(j-4.5)*0.00015
        close=btc_close if j==0 else (70+8*j)*np.cumprod(1+own); open_=close*(1+0.0015*np.cos(t/6+j)); high=np.maximum(open_,close)*1.01; low=np.minimum(open_,close)*0.99
        daily[s]=pd.DataFrame({"open":open_,"high":high,"low":low,"close":close},index=idx)
        freq="4h" if s=="ENA_USDT" else "8h"; fidx=pd.date_range("2026-01-01",periods=(days*6 if freq=="4h" else days*3),freq=freq,tz="UTC")
        rate=(j-4.5)*5e-6; funding[s]=pd.DataFrame({"funding_rate":np.full(len(fidx),rate)},index=fidx)
    return daily,funding


def test_protocol_frozen_and_trial_accounting():
    p=json.loads(Path("config/discovery_v2_sprint9_v1.json").read_text())
    assert p["status"]=="FROZEN_BEFORE_MARKET_RESULTS"
    assert p["execution"]["common_comparison_warmup_days"]==100
    assert p["execution"]["leverage"]==1.0
    assert p["trial_accounting"]["directional_candidate_variants_added_this_sprint"]==12
    assert p["trial_accounting"]["all_12_variants_count"] is True
    assert p["data"]["no_2025_data_for_discovery"] is True
    assert p["claims"]["persistent_edge_established"] is False


def test_all_engines_next_open_one_x_and_reverse_timing():
    d,f=_fixtures()
    pairs=[
        (cross_sectional_funding_carry,dict(daily_frames=d,symbols=SYMBOLS,funding_frames=f,lookback_calendar_days=7,common_warmup_days=100,side_cost_bps=10.0)),
        (adaptive_ar1_forecast,dict(daily_frames=d,symbols=SYMBOLS,funding_frames=f,lookback_pairs=60,common_warmup_days=100,side_cost_bps=10.0)),
        (cross_sectional_low_btc_beta,dict(daily_frames=d,symbols=SYMBOLS,alt_symbols=ALTS,funding_frames=f,lookback_days=45,common_warmup_days=100,side_cost_bps=10.0)),
    ]
    for fn,kw in pairs:
        a=fn(**kw,reverse=False); b=fn(**kw,reverse=True)
        assert len(a.observations)>50
        assert a.observations.index.equals(b.observations.index)
        assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"])
        assert (a.observations["active_gross"]<=1.0+1e-12).all()
        assert np.isfinite(a.observations["net_return_bps"]).all()
        assert (pd.to_datetime(a.observations["end_timestamp"])>a.observations.index).all()


def test_funding_score_excludes_event_exactly_at_execution_open():
    d,f=_fixtures(); execution=d["BTC_USDT"].index[101]
    base=cross_sectional_funding_carry(daily_frames=d,symbols=SYMBOLS,funding_frames=f,lookback_calendar_days=3,common_warmup_days=100,side_cost_bps=10.0)
    altered={k:v.copy() for k,v in f.items()}
    for j,s in enumerate(SYMBOLS):
        altered[s].loc[execution,"funding_rate"]=(j+1)*0.25
        altered[s]=altered[s].sort_index()
    changed=cross_sectional_funding_carry(daily_frames=d,symbols=SYMBOLS,funding_frames=altered,lookback_calendar_days=3,common_warmup_days=100,side_cost_bps=10.0)
    assert base.observations.index[0]==execution
    assert changed.observations.index[0]==execution
    assert np.isclose(base.observations.iloc[0]["net_return_bps"],changed.observations.iloc[0]["net_return_bps"],atol=1e-12)


def test_low_beta_never_trades_btc():
    d,f=_fixtures()
    run=cross_sectional_low_btc_beta(daily_frames=d,symbols=SYMBOLS,alt_symbols=ALTS,funding_frames=f,lookback_days=60,common_warmup_days=100,side_cost_bps=10.0)
    btc=run.contributions.loc[run.contributions["symbol"]=="BTC_USDT","net_contribution_bps"]
    assert len(btc)==len(run.observations)
    assert np.allclose(btc.to_numpy(float),0.0,atol=1e-12)

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from orderflow_edge_lab.discovery_v2_sprint10 import historical_max_return_momentum,historical_skewness_premium,historical_kurtosis_premium

SYMBOLS=["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT","BNB_USDT","ADA_USDT","LINK_USDT","SUI_USDT","ENA_USDT"]

def _fixtures(days=210):
    idx=pd.date_range("2026-01-01",periods=days,freq="1D",tz="UTC"); fidx=pd.date_range("2026-01-01",periods=days*3,freq="8h",tz="UTC"); t=np.arange(days,dtype=float); daily={}; funding={}
    for j,s in enumerate(SYMBOLS):
        ret=0.006*np.sin(t/(2.5+0.12*j)+j)+0.003*np.cos(t/(8+j*0.2))+(j-4.5)*0.00012; close=(90+6*j)*np.cumprod(1+ret); open_=close*(1+0.0015*np.cos(t/6+j)); daily[s]=pd.DataFrame({"open":open_,"high":np.maximum(open_,close)*1.01,"low":np.minimum(open_,close)*0.99,"close":close},index=idx); funding[s]=pd.DataFrame({"funding_rate":np.full(len(fidx),(j-4.5)*1e-6)},index=fidx)
    return daily,funding

def test_protocol_frozen_with_literature_directions():
    p=json.loads(Path("config/discovery_v2_sprint10_literature_v1.json").read_text()); assert p["status"]=="FROZEN_BEFORE_MARKET_RESULTS"; assert p["trial_accounting"]["directional_candidate_variants_added_this_sprint"]==12; assert p["trial_accounting"]["published_direction_does_not_relax_internal_gates"] is True; assert p["data"]["no_2025_data_for_discovery"] is True; assert p["claims"]["paper_replication_claimed"] is False

def test_all_characteristics_next_open_one_x_and_reverse_same_timing():
    d,f=_fixtures(); specs=[(historical_max_return_momentum,30),(historical_skewness_premium,30),(historical_kurtosis_premium,30)]
    for fn,n in specs:
        kw=dict(daily_frames=d,symbols=SYMBOLS,funding_frames=f,lookback_days=n,common_warmup_days=100,side_cost_bps=10.0); a=fn(**kw,reverse=False); b=fn(**kw,reverse=True); assert len(a.observations)>50; assert a.observations.index.equals(b.observations.index); assert a.observations["end_timestamp"].equals(b.observations["end_timestamp"]); assert (a.observations["active_gross"]<=1.0+1e-12).all(); assert np.isfinite(a.observations["net_return_bps"]).all()

def test_future_price_change_does_not_change_first_signal_timing():
    d,f=_fixtures(); base=historical_max_return_momentum(daily_frames=d,symbols=SYMBOLS,funding_frames=f,lookback_days=30,common_warmup_days=100,side_cost_bps=10.0); changed={k:v.copy() for k,v in d.items()}; exec_ts=base.observations.index[0]
    for s in SYMBOLS: changed[s].loc[exec_ts,"close"]*=1.5
    alt=historical_max_return_momentum(daily_frames=changed,symbols=SYMBOLS,funding_frames=f,lookback_days=30,common_warmup_days=100,side_cost_bps=10.0); assert alt.observations.index[0]==exec_ts

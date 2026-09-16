from __future__ import annotations

import hashlib
from typing import Mapping, Sequence
import numpy as np, pandas as pd


def _align(frames: Mapping[str,pd.DataFrame], symbols: Sequence[str]):
    mats={f:pd.concat({s:pd.to_numeric(frames[s][f],errors="coerce") for s in symbols},axis=1,join="inner").sort_index() for f in ("open","high","low","close")}
    idx=mats["open"].index
    for f in ("high","low","close"): idx=idx.intersection(mats[f].index)
    mats={f:m.loc[idx].astype(float) for f,m in mats.items()}; valid=pd.Series(True,index=idx)
    for m in mats.values(): valid &= ~m.isna().any(axis=1)
    return tuple(mats[f].loc[valid] for f in ("open","high","low","close"))

def _fund(frame,start,end):
    if frame is None or frame.empty: return 0.0
    x=pd.to_numeric(frame["funding_rate"],errors="coerce").dropna(); return float(x.loc[(x.index>start)&(x.index<end)].sum())

def _target(score,reverse=False):
    r=pd.to_numeric(score,errors="coerce").replace([np.inf,-np.inf],np.nan).dropna().sort_values(); out=pd.Series(0.0,index=score.index,dtype=float)
    if len(r)<6: return out
    low,high=list(r.index[:2]),list(r.index[-2:])
    if reverse: out.loc[low]=0.25; out.loc[high]=-0.25
    else: out.loc[high]=0.25; out.loc[low]=-0.25
    return out

def simulate_forward(frames, funding_frames, *, symbols, range_baseline_days, forward_start, asof, side_cost_bps, reverse=False):
    opens,highs,lows,closes=_align(frames,symbols); prev_close=closes.shift(1)
    tr=pd.DataFrame(np.maximum.reduce([(highs-lows).to_numpy(float),(highs-prev_close).abs().to_numpy(float),(lows-prev_close).abs().to_numpy(float)]),index=opens.index,columns=opens.columns)
    direction=closes/opens-1.0; signals=[]
    for i in range(int(range_baseline_days),len(opens)):
        # Daily bar t must itself be complete before its signal can exist.
        if opens.index[i]+pd.Timedelta(days=1)>asof: continue
        baseline=tr.iloc[i-int(range_baseline_days):i].median(axis=0).replace(0.0,np.nan); score=direction.iloc[i]*(tr.iloc[i]/baseline)
        signals.append((i,_target(score,reverse=reverse).reindex(opens.columns,fill_value=0.0)))
    previous=pd.Series(0.0,index=opens.columns,dtype=float); rows=[]; legs=[]; weights=[]; widx=[]; open_position=None
    for i,target in signals:
        start_i=i+1
        if start_i>=len(opens): continue
        start=opens.index[start_i]
        if start<forward_start: continue
        entry_cost=(target-previous).abs()*float(side_cost_bps)/10000.0
        end_i=start_i+1
        if end_i>=len(opens) or opens.index[end_i]>asof:
            open_position={"entry_time":start.isoformat(),"weights":{s:float(target[s]) for s in opens.columns if abs(float(target[s]))>1e-12},"entry_cost_bps":float(entry_cost.sum()*10000.0)}
            break
        end=opens.index[end_i]; px=opens.loc[end]/opens.loc[start]-1.0; gross=0.0; cost=float(entry_cost.sum())
        for s in opens.columns:
            w=float(target[s]); leg_gross=w*(float(px[s])-_fund(funding_frames.get(s),start,end)); gross+=leg_gross
            legs.append({"timestamp":start,"symbol":s,"net_contribution_bps":(leg_gross-float(entry_cost[s]))*10000.0})
        rows.append({"timestamp":start,"end_timestamp":end,"gross_return_bps":gross*10000.0,"cost_bps":cost*10000.0,"net_return_bps":(gross-cost)*10000.0,"active_gross":float(target.abs().sum())})
        weights.append(target.copy()); widx.append(start); previous=target
    obs=pd.DataFrame(rows)
    if not obs.empty: obs=obs.set_index("timestamp")
    return {"observations":obs,"contributions":pd.DataFrame(legs),"weights":pd.DataFrame(weights,index=pd.DatetimeIndex(widx,name="timestamp")) if weights else pd.DataFrame(),"open_position":open_position}

def summarize(run,cost_multipliers=(1.0,1.5,2.0)):
    obs=run["observations"]
    if obs.empty: return {"completed_periods":0,"start":None,"end":None,"pnl_per_1000":0.0,"max_drawdown":None,"cost_cases":{},"open_position":run["open_position"],"observations_sha256":hashlib.sha256(b"").hexdigest()}
    base=obs["gross_return_bps"].astype(float); costs=obs["cost_bps"].astype(float); cases={}
    for m in cost_multipliers:
        r=(base-costs*float(m))/10000.0; eq=(1+r).cumprod(); dd=eq/eq.cummax()-1; cases[str(float(m))]={"mean_net_bps":float((r*10000).mean()),"pnl_per_1000":float((eq.iloc[-1]-1)*1000),"max_drawdown":float(dd.min())}
    canonical=obs.sort_index().to_csv(index=True,float_format="%.12g").encode()
    return {"completed_periods":int(len(obs)),"start":obs.index.min().isoformat(),"end":pd.Timestamp(obs["end_timestamp"].max()).isoformat(),"pnl_per_1000":cases["1.0"]["pnl_per_1000"],"max_drawdown":cases["1.0"]["max_drawdown"],"cost_cases":cases,"open_position":run["open_position"],"observations_sha256":hashlib.sha256(canonical).hexdigest()}

from __future__ import annotations
import hashlib,itertools,json,math
from collections import Counter
from pathlib import Path
from typing import Any,Mapping,Sequence
import numpy as np
import pandas as pd
from orderflow_edge_lab.universal_backtest import ExecutionModel,legacy_strategy,run_canonical_backtest
from orderflow_edge_lab.universal_existing_validation import load_protocol,load_snapshot

class RegimeV1Error(ValueError): pass

LABELS={
 "trend":("CHOP","MIXED","TREND"),"volatility":("LOW","MID","HIGH"),
 "coupling":("LOW","MID","HIGH"),"shock":("NORMAL","SHOCK"),
 "drawdown":("NEAR_HIGH","CORRECTION","DEEP_DRAWDOWN"),
}
def _f(x):
    try: y=float(x)
    except (TypeError,ValueError): return None
    return y if math.isfinite(y) else None
def _utc(x):
    t=pd.Timestamp(x); return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

def kaufman_er(close:pd.Series,n:int)->pd.Series:
    if n<=0: raise RegimeV1Error("bad Kaufman window")
    c=close.astype(float); ch=(c-c.shift(n)).abs()
    path=c.diff().abs().rolling(n,min_periods=n).sum()
    out=ch/path.replace(0,np.nan)
    return out.where(~((path==0)&(ch==0)),0.0).clip(0,1)

def garman_klass(frame:pd.DataFrame,n:int)->pd.Series:
    if n<=0: raise RegimeV1Error("bad GK window")
    o,h,l,c=(frame[k].astype(float) for k in ("open","high","low","close"))
    if ((o<=0)|(h<=0)|(l<=0)|(c<=0)).any(): raise RegimeV1Error("nonpositive OHLC")
    v=(.5*np.log(h/l)**2-(2*math.log(2)-1)*np.log(c/o)**2).clip(lower=0)
    return np.sqrt(v.rolling(n,min_periods=n).mean())

def market_coupling(frames:Mapping[str,pd.DataFrame],n:int,min_pairs:int)->pd.Series:
    panel=pd.DataFrame({s:np.log(f["close"].astype(float)/f["close"].astype(float).shift(1)) for s,f in frames.items()}).sort_index()
    pairs=[]
    for i,a in enumerate(sorted(panel)):
        for b in sorted(panel)[i+1:]:
            pairs.append(panel[a].rolling(n,min_periods=n).corr(panel[b]))
    if not pairs: raise RegimeV1Error("coupling requires >=2 symbols")
    p=pd.concat(pairs,axis=1); return p.mean(axis=1).where(p.notna().sum(axis=1)>=min_pairs)

def percentile_bucket(x:pd.Series,h:int,qlo:float,qhi:float):
    prior=x.shift(1); lo=prior.rolling(h,min_periods=h).quantile(qlo); hi=prior.rolling(h,min_periods=h).quantile(qhi)
    raw=pd.Series("UNKNOWN",index=x.index,dtype=object); ok=x.notna()&lo.notna()&hi.notna()
    raw.loc[ok&(x<=lo)]="LOW"; raw.loc[ok&(x>=hi)]="HIGH"; raw.loc[ok&(x>lo)&(x<hi)]="MID"
    return raw,lo,hi

def persist(raw:pd.Series,n:int,remap:Mapping[str,str]|None=None)->pd.Series:
    if n<=0: raise RegimeV1Error("bad persistence")
    out=[]; stable=candidate=None; count=0
    for value in raw.astype(str):
        if value=="UNKNOWN":
            candidate=None; count=0; out.append(stable or "UNKNOWN"); continue
        if stable is None: stable=value; candidate=None; count=0
        elif value==stable: candidate=None; count=0
        else:
            if candidate!=value: candidate=value; count=1
            else: count+=1
            if count>=n: stable=candidate; candidate=None; count=0
        out.append(stable)
    s=pd.Series(out,index=raw.index,dtype=object)
    return s.map(lambda z:(remap or {}).get(z,z))

def shock(close:pd.Series,h:int,sigma:float,active:int):
    r=np.log(close.astype(float)/close.astype(float).shift(1))
    sd=r.shift(1).rolling(h,min_periods=h).std(ddof=1)
    event=(sd>0)&(r.abs()>=sigma*sd)
    state=event.astype(int).rolling(active,min_periods=1).max().astype(bool)
    return event.fillna(False),state.fillna(False)

def build_states(frames:Mapping[str,pd.DataFrame],cfg:Mapping[str,Any])->dict[str,pd.DataFrame]:
    L=cfg["labels"]; cc=L["market_coupling"]
    cp=market_coupling(frames,int(cc["window_bars"]),int(cc["minimum_pair_count"]))
    cr,clo,chi=percentile_bucket(cp,int(cc["percentile_history_bars"]),float(cc["lower_quantile"]),float(cc["upper_quantile"]))
    cs=persist(cr,int(cc["persistence_bars"]))
    out={}
    for sym,f in frames.items():
        tc,vc,sc,dc=L["trend_efficiency"],L["volatility"],L["shock"],L["drawdown"]
        er=kaufman_er(f["close"],int(tc["window_bars"]))
        tr,tlo,thi=percentile_bucket(er,int(tc["percentile_history_bars"]),float(tc["lower_quantile"]),float(tc["upper_quantile"]))
        ts=persist(tr,int(tc["persistence_bars"]),{"LOW":"CHOP","MID":"MIXED","HIGH":"TREND"})
        gv=garman_klass(f,int(vc["window_bars"]))
        vr,vlo,vhi=percentile_bucket(gv,int(vc["percentile_history_bars"]),float(vc["lower_quantile"]),float(vc["upper_quantile"]))
        vs=persist(vr,int(vc["persistence_bars"]))
        ev,act=shock(f["close"],int(sc["sigma_history_bars"]),float(sc["sigma_threshold"]),int(sc["active_bars_including_event"]))
        dd=f["close"].astype(float)/f["high"].astype(float).rolling(int(dc["lookback_bars"]),min_periods=int(dc["lookback_bars"])).max()-1
        dr=pd.Series("UNKNOWN",index=f.index,dtype=object); ok=dd.notna(); near=float(dc["near_high_threshold"]); deep=float(dc["deep_drawdown_threshold"])
        dr.loc[ok&(dd>=near)]="NEAR_HIGH"; dr.loc[ok&(dd<near)&(dd>deep)]="CORRECTION"; dr.loc[ok&(dd<=deep)]="DEEP_DRAWDOWN"
        ds=persist(dr,int(dc["persistence_bars"]))
        z=pd.DataFrame(index=f.index)
        z["trend_efficiency"],z["trend_state"]=er,ts; z["trend_lo"],z["trend_hi"]=tlo,thi
        z["gk_volatility"],z["volatility_state"]=gv,vs; z["vol_lo"],z["vol_hi"]=vlo,vhi
        z["market_coupling"],z["coupling_state"]=cp.reindex(f.index),cs.reindex(f.index).fillna("UNKNOWN")
        z["coupling_lo"],z["coupling_hi"]=clo.reindex(f.index),chi.reindex(f.index)
        z["shock_event"],z["shock_state"]=ev,np.where(act,"SHOCK","NORMAL")
        z["drawdown"],z["drawdown_state"]=dd,ds
        out[sym]=z
    return out

def state_at_entry(z:pd.DataFrame,entry:Any)->dict[str,Any]:
    before=z.index<_utc(entry)
    if not before.any(): return {"state_timestamp":None,"trend_state":"UNKNOWN","volatility_state":"UNKNOWN","coupling_state":"UNKNOWN","shock_state":"NORMAL","drawdown_state":"UNKNOWN"}
    t=z.index[before][-1]; r=z.loc[t]
    return {"state_timestamp":t.isoformat(),"trend_state":str(r.trend_state),"volatility_state":str(r.volatility_state),
            "coupling_state":str(r.coupling_state),"shock_state":str(r.shock_state),"drawdown_state":str(r.drawdown_state),
            "trend_efficiency":_f(r.trend_efficiency),"garman_klass_volatility":_f(r.gk_volatility),
            "market_coupling":_f(r.market_coupling),"drawdown_from_540bar_high":_f(r.drawdown),"shock_event":bool(r.shock_event)}

def cell_ids():
    return ["|".join((f"TREND={a}",f"VOL={b}",f"COUPLING={c}",f"SHOCK={d}",f"DRAWDOWN={e}"))
            for a,b,c,d,e in itertools.product(*LABELS.values())]
def cell_key(r):
    vals=(r["trend_state"],r["volatility_state"],r["coupling_state"],r["shock_state"],r["drawdown_state"])
    if any(v not in allowed for v,allowed in zip(vals,LABELS.values())): return None
    return "|".join((f"TREND={vals[0]}",f"VOL={vals[1]}",f"COUPLING={vals[2]}",f"SHOCK={vals[3]}",f"DRAWDOWN={vals[4]}"))

def summary(rows:Sequence[Mapping[str,Any]])->dict[str,Any]:
    net=[float(r["net_bps"]) for r in rows if _f(r.get("net_bps")) is not None]
    gross=[float(r["gross_bps"]) for r in rows if _f(r.get("gross_bps")) is not None]
    mfe=[float(r["mfe_bps"]) for r in rows if _f(r.get("mfe_bps")) is not None]; mae=[abs(float(r["mae_bps"])) for r in rows if _f(r.get("mae_bps")) is not None]
    cmfe=[float(r["mfe_bps"]) for r in rows if _f(r.get("gross_bps")) is not None and float(r["gross_bps"])>0 and _f(r.get("mfe_bps")) is not None]
    by={}
    for r in rows: by.setdefault(str(r["symbol"]),[]).append(r)
    sr={}
    for s,rr in by.items():
        eq=1.0
        for r in sorted(rr,key=lambda x:str(x["entry"])): eq*=1+float(r["net_bps"])/10000
        sr[s]=eq-1
    pos=sum(x for x in net if x>0); neg=abs(sum(x for x in net if x<0))
    return {"trade_count":len(rows),"expectancy_bps":float(np.mean(net)) if net else None,"median_net_bps":float(np.median(net)) if net else None,
            "win_rate":sum(x>0 for x in net)/len(net) if net else None,"profit_factor":pos/neg if neg>0 else None,
            "correct_direction_rate":sum(x>0 for x in gross)/len(gross) if gross else None,
            "median_mfe_bps":float(np.median(mfe)) if mfe else None,"median_correct_direction_mfe_bps":float(np.median(cmfe)) if cmfe else None,
            "median_abs_mae_bps":float(np.median(mae)) if mae else None,"observed_symbol_count":len(by),
            "per_symbol_compounded_return":sr,"median_symbol_compounded_return":float(np.median(list(sr.values()))) if sr else None,
            "positive_symbol_fraction":sum(x>0 for x in sr.values())/len(sr) if sr else None}

def _samples(blocks,replicates,seed):
    if not blocks:return []
    rng=np.random.default_rng(seed); a=np.asarray(blocks,dtype=int)
    return [Counter(int(x) for x in rng.choice(a,size=len(a),replace=True)) for _ in range(replicates)]
def boot(rows,samples,ci):
    vals=[float(r["net_bps"]) for r in rows]
    if not vals:return {"ci_lower":None,"ci_upper":None,"two_sided_centered_bootstrap_p":None,"valid_replicates":0}
    obs=float(np.mean(vals)); reps=[]
    for w in samples:
        v=[]
        for r in rows:v.extend([float(r["net_bps"])]*int(w.get(int(r["_block_id"]),0)))
        if v:reps.append(float(np.mean(v)))
    if not reps:return {"ci_lower":None,"ci_upper":None,"two_sided_centered_bootstrap_p":None,"valid_replicates":0}
    p=(1+sum(abs(x-obs)>=abs(obs) for x in reps))/(len(reps)+1)
    return {"ci_lower":float(np.quantile(reps,ci[0])),"ci_upper":float(np.quantile(reps,ci[1])),"two_sided_centered_bootstrap_p":float(p),"valid_replicates":len(reps)}
def bh(ps):
    n=len(ps); out=[1.]*n; run=1.
    for rev,i in enumerate(reversed(sorted(range(n),key=lambda j:ps[j])),1):
        rank=n-rev+1; run=min(run,min(1.,ps[i]*n/rank)); out[i]=run
    return out
def holm(ps):
    n=len(ps); out=[1.]*n; run=0.
    for rank,i in enumerate(sorted(range(n),key=lambda j:ps[j])):
        run=max(run,min(1.,(n-rank)*ps[i])); out[i]=run
    return out

def build_report(source:Mapping[str,Any],frames:Mapping[str,pd.DataFrame],cfg:Mapping[str,Any])->dict[str,Any]:
    if cfg.get("protocol_name")!="universal-descriptive-regime-labels-v1":raise RegimeV1Error("wrong protocol")
    cost=float(cfg["primary_cost_bps"]); states=build_states(frames,cfg); by_strategy={}
    for spec in source["strategies"]:
        sid=str(spec["audit_id"]); rows=[]
        for sym in sorted(frames):
            can=run_canonical_backtest(frames[sym],legacy_strategy(str(spec["family"])),dict(spec["parameters"]),ExecutionModel(round_trip_cost_bps=cost))
            for tr in can.get("trades_ledger") or []:
                if tr.get("terminal_liquidation"):continue
                e=_utc(tr["entry"]); rows.append({"strategy_id":sid,"symbol":sym,"entry":e.isoformat(),"exit":str(tr["exit"]),
                    "net_bps":float(tr["net_bps"]),"gross_bps":float(tr["gross_bps"]),"mfe_bps":_f(tr.get("mfe_bps")),"mae_bps":_f(tr.get("mae_bps")),**state_at_entry(states[sym],e)})
        by_strategy[sid]=rows
    allr=[r for rr in by_strategy.values() for r in rr]; B=cfg["bootstrap"]
    if allr:
        origin=min(_utc(r["entry"]) for r in allr).normalize(); delta=pd.Timedelta(days=int(B["block_days"]))
        for r in allr:r["_block_id"]=int((_utc(r["entry"])-origin)//delta)
        blocks=sorted({r["_block_id"] for r in allr})
    else:origin=None;blocks=[]
    samples=_samples(blocks,int(B["replicates"]),int(B["seed"])); ids=cell_ids(); alpha=float(cfg["multiplicity"]["alpha"]); reports=[]
    for spec in source["strategies"]:
        sid=str(spec["audit_id"]); rows=by_strategy[sid]; buckets={x:[] for x in ids}; un=0
        for r in rows:
            k=cell_key(r)
            if k is None:un+=1
            else:buckets[k].append(r)
        cells=[]; positions=[]; ps=[]
        for cid in ids:
            rr=buckets[cid]; s=summary(rr); u=boot(rr,samples,B["confidence_interval"])
            cell={"cell_id":cid,**s,"sample_warning":s["trade_count"]<20,"bootstrap_expectancy":u,
                  "bh_fdr_q":None,"holm_fwer_p":None,"bh_fdr_10pct":False,"holm_fwer_10pct":False}
            if u["two_sided_centered_bootstrap_p"] is not None:positions.append(len(cells));ps.append(float(u["two_sided_centered_bootstrap_p"]))
            cells.append(cell)
        for p,q,h in zip(positions,bh(ps),holm(ps)):
            cells[p]["bh_fdr_q"]=q;cells[p]["holm_fwer_p"]=h;cells[p]["bh_fdr_10pct"]=q<=alpha;cells[p]["holm_fwer_10pct"]=h<=alpha
        reports.append({"audit_id":sid,"family":str(spec["family"]),"parameters":dict(spec["parameters"]),"all_completed_nonterminal_trades":summary(rows),
                        "classified_trade_count":len(rows)-un,"unclassified_trade_count":un,"joint_cells":cells,
                        "trades":[{k:v for k,v in r.items() if not k.startswith("_")} for r in rows]})
    coverage={s:{"bars":int(len(z)),**{f"{col}_counts":{str(k):int(v) for k,v in z[col].value_counts().items()}
             for col in ("trend_state","volatility_state","coupling_state","shock_state","drawdown_state")}} for s,z in states.items()}
    contract={"label_order":LABELS,"cell_ids":ids}; sha=hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"schema_version":1,"analysis":"universal_descriptive_regime_labels_v1","protocol_name":cfg["protocol_name"],"source_protocol_name":source["protocol_name"],
            "primary_cost_bps":cost,"timeframe":cfg["timeframe"],"state_semantics":{"trade_entry_uses_latest_completed_bar_strictly_before_entry":True,
            "percentile_thresholds_use_feature_history_ending_one_bar_before_state_bar":True,"shock_state_is_event_driven_and_not_delayed_by_persistence":True},
            "label_configuration":cfg["labels"],"state_coverage":coverage,"bootstrap":{**B,"calendar_block_origin":origin.isoformat() if origin is not None else None,
            "calendar_block_count":len(blocks),"shared_resamples_across_symbols_strategies_and_cells":True},"multiplicity":cfg["multiplicity"],
            "fixed_joint_cell_count_per_strategy":len(ids),"joint_cell_set_sha256":sha,"strategies":reports,"claims":cfg["claims"],"literature_basis":cfg.get("literature_basis",[])}

def run_from_paths(source_protocol_path:str|Path,regime_config_path:str|Path,data_dir:str|Path)->dict[str,Any]:
    source=load_protocol(source_protocol_path); cfg=json.loads(Path(regime_config_path).read_text()); frames,snapshot=load_snapshot(source,data_dir)
    r=build_report(source,frames,cfg); r["source_snapshot"]=snapshot
    r["source_protocol_sha256"]=hashlib.sha256(Path(source_protocol_path).read_bytes()).hexdigest()
    r["regime_config_sha256"]=hashlib.sha256(Path(regime_config_path).read_bytes()).hexdigest(); return r

from __future__ import annotations
import argparse, itertools, json
from pathlib import Path
import numpy as np
import pandas as pd

START = pd.Timestamp("2025-09-01", tz="UTC")
DEV_END = pd.Timestamp("2026-08-01", tz="UTC")
DEV_FOLDS = set(range(15))
SYMS = ["BTC","ETH","SOL","XRP","DOGE","BNB","ADA","LINK","SUI","ENA"]
SINGLE_COSTS = {"low":11.0,"primary":18.0,"high":25.0}
XSEC_COSTS = {"low":12.0,"primary":16.0,"high":20.0}

def rho(a,b):
    a=np.asarray(a,float); b=np.asarray(b,float)
    m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<20: return np.nan
    return float(pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank()))

def pfv(a):
    a=np.asarray(a,float)
    p=a[a>0].sum(); n=-a[a<0].sum()
    return 999.0 if n<=0 and p>0 else (0.0 if n<=0 else float(p/n))

def load(data_dir: Path):
    D={}
    for s in SYMS:
        fut=pd.read_csv(data_dir/f"{s}_futures_1h.csv",parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        spot=pd.read_csv(data_dir/f"{s}_spot_1h.csv",parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        fund=pd.read_csv(data_dir/f"{s}_funding.csv",parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        idx=fut.index.intersection(spot.index)
        x=pd.DataFrame(index=idx)
        for c in ["open","close"]:
            x[f"fut_{c}"]=fut.loc[idx,c].astype(float)
            x[f"spot_{c}"]=spot.loc[idx,c].astype(float)
        x["basis"]=(x.fut_close/x.spot_close-1)*1e4
        x["latest_funding"]=fund.funding_rate.reindex(idx,method="ffill").astype(float)
        fr=pd.Series(0.0,index=idx)
        common=fr.index.intersection(fund.index)
        fr.loc[common]=fund.loc[common,"funding_rate"].values
        x["funding_settle"]=fr
        x["funding_cum"]=fr.cumsum()
        x["fold"]=np.floor((idx-START)/pd.Timedelta(days=21)).astype(int)
        D[s]=(x,fund)
    return D

def eval_single(D,family,p):
    state_rows=[]; trade_rows=[]
    hold=p["hold"]
    for s,(x,fund) in D.items():
        n=len(x); valid=np.arange(n); exit_state=valid+hold; exit_trade=valid+1+hold
        mask=(x.index>=START)&(x.index<DEV_END)&x["fold"].isin(DEV_FOLDS).values
        mask &= (exit_trade<n)
        basis=x.basis.to_numpy(); f=x.latest_funding.to_numpy(); fold=x["fold"].to_numpy()
        esc=np.minimum(exit_state,n-1); et=np.minimum(exit_trade,n-1)
        mask &= fold[et]==fold
        if family=="positive":
            active=(f>=p["fund_thr"])&(basis>=p["basis_min"]); score=f.copy()
            fc=x.funding_cum.to_numpy(); target=fc[esc]-fc
        elif family=="basis":
            active=(basis>=p["basis_thr"])
            if p["req_nonneg"]: active &= f>=0
            score=basis.copy(); target=basis-basis[esc]
        elif family=="hybrid":
            active=(f>=p["fund_thr"])&(basis>=p["basis_thr"])
            score=basis+f*1e4*(hold/8)
            fc=x.funding_cum.to_numpy(); target=(basis-basis[esc])+(fc[esc]-fc)*1e4
        elif family=="persistence":
            fs=fund.funding_rate.astype(float); nsett=p["nsett"]
            mean=fs.rolling(nsett,min_periods=nsett).mean().reindex(x.index,method="ffill").to_numpy()
            pos=(fs.gt(0).rolling(nsett,min_periods=nsett).sum()).reindex(x.index,method="ffill").to_numpy()
            active=(pos>=nsett)&(mean>=p["mean_thr"]); score=mean
            fc=x.funding_cum.to_numpy(); target=fc[esc]-fc
        elif family=="reverse":
            active=f<=p["fund_thr"]; score=-f
            fc=x.funding_cum.to_numpy(); target=-(fc[esc]-fc)
        else: raise ValueError(family)
        m=mask&active&np.isfinite(score)&np.isfinite(target); ids=np.where(m)[0]
        for fid in np.unique(fold[ids]):
            ii=ids[fold[ids]==fid]
            if len(ii)>=20:
                r=rho(score[ii],target[ii])
                if np.isfinite(r): state_rows.append((int(fid),r,s))
        next_exit=-1; fc=x.funding_cum.to_numpy()
        for i in ids:
            if i<next_exit: continue
            j=i+1; k=i+1+hold
            spotret=(x.spot_open.iloc[k]/x.spot_open.iloc[j]-1)*1e4
            futret=(x.fut_open.iloc[k]/x.fut_open.iloc[j]-1)*1e4
            fundsum=(fc[k]-fc[j])*1e4
            gross=(0.5*futret-0.5*spotret-0.5*fundsum) if family=="reverse" else (0.5*spotret-0.5*futret+0.5*fundsum)
            trade_rows.append((s,int(fold[i]),float(gross))); next_exit=k
    byfold={}
    for fid,r,s in state_rows: byfold.setdefault(fid,[]).append(r)
    fr=[float(np.median(rs)) for fid,rs in sorted(byfold.items()) if rs]
    tr=pd.DataFrame(trade_rows,columns=["symbol","fold","gross"])
    out={"family":family,"params":p,"state_folds":len(fr),
         "state_median_rho":float(np.median(fr)) if fr else np.nan,
         "state_posfold":float(np.mean(np.array(fr)>0)) if fr else 0.0,
         "trades":len(tr),"symbol_count":int(tr.symbol.nunique()) if len(tr) else 0}
    for cname,cost in SINGLE_COSTS.items():
        if len(tr):
            vals=tr.gross-cost
            tmp=tr.assign(net=vals); fexp=tmp.groupby("fold").net.mean(); fpf=tmp.groupby("fold").net.apply(pfv)
            sexp=tmp.groupby("symbol").net.mean()
            out[f"{cname}_median_fold_net"]=float(fexp.median()); out[f"{cname}_median_fold_pf"]=float(fpf.median())
            out[f"{cname}_posfold"]=float((fexp>0).mean()); out[f"{cname}_possym"]=float((sexp>0).mean())
            out[f"{cname}_mean"]=float(vals.mean())
        else:
            for z in ["median_fold_net","median_fold_pf","posfold","possym","mean"]: out[f"{cname}_{z}"]=np.nan
    out["rev_mean"]=float((-tr.gross-SINGLE_COSTS["primary"]).mean()) if len(tr) else np.nan
    out["state_pass"]=bool(len(fr)>=10 and out["state_median_rho"]>0 and out["state_posfold"]>=.6)
    out["prelim_pass"]=bool(out["state_pass"] and len(tr)>=60 and out["primary_median_fold_net"]>0 and
        out["primary_median_fold_pf"]>1 and out["primary_posfold"]>=.6 and out["primary_possym"]>=.6 and
        out["high_median_fold_net"]>=0 and out["primary_mean"]>out["rev_mean"])
    return out

def prepare_xsec(D):
    idx=None
    for s in SYMS: idx=D[s][0].index if idx is None else idx.intersection(D[s][0].index)
    idx=idx.sort_values()
    rets=pd.DataFrame({s:D[s][0].fut_close.reindex(idx).pct_change() for s in SYMS})
    btc=rets["BTC"]; betas=pd.DataFrame(index=idx,columns=SYMS,dtype=float)
    for s in SYMS:
        betas[s]=(rets[s].rolling(192,min_periods=96).cov(btc)/btc.rolling(192,min_periods=96).var().replace(0,np.nan)).shift(1)
    fundmeans={}
    for nsett in [2,3,5]:
        fm=pd.DataFrame(index=idx,columns=SYMS,dtype=float)
        for s in SYMS:
            fs=D[s][1].funding_rate.astype(float)
            fm[s]=fs.rolling(nsett,min_periods=nsett).mean().reindex(idx,method="ffill")
        fundmeans[nsett]=fm
    return idx,betas,fundmeans

def eval_xsec(D,ctx,k,nsett,hold):
    idx,betas,fundmeans=ctx; T=len(idx); symi={s:i for i,s in enumerate(SYMS)}
    open_mat=np.column_stack([D[s][0].fut_open.reindex(idx).to_numpy(float) for s in SYMS])
    fcum_mat=np.column_stack([D[s][0].funding_cum.reindex(idx).to_numpy(float) for s in SYMS])
    beta_mat=betas[SYMS].to_numpy(float); fm=fundmeans[nsett][SYMS].to_numpy(float)
    fold=np.floor((idx-START)/pd.Timedelta(days=21)).astype(int)
    valid=np.isfinite(fm).all(axis=1)&np.isfinite(beta_mat).all(axis=1)
    order=np.argsort(fm,axis=1); lo=order[:,:k]; hi=order[:,-k:]
    w=np.zeros_like(fm); rows=np.arange(T)[:,None]; w[rows,lo]=0.5/k; w[rows,hi]=-0.5/k
    netbeta=np.nansum(w*beta_mat,axis=1); w[:,symi["BTC"]]-=netbeta
    norm=np.abs(w).sum(axis=1); w=w/np.where(norm>0,norm,np.nan)[:,None]
    score=np.take_along_axis(fm,hi,axis=1).mean(axis=1)-np.take_along_axis(fm,lo,axis=1).mean(axis=1)
    entry_shift=1; exit_shift=1+hold; max_i=T-exit_shift
    price_ret=np.full_like(open_mat,np.nan); fsum=np.full_like(fcum_mat,np.nan)
    price_ret[:max_i]=(open_mat[exit_shift:]/open_mat[entry_shift:T-hold]-1)*1e4
    fsum[:max_i]=(fcum_mat[exit_shift:]-fcum_mat[entry_shift:T-hold])*1e4
    price=np.nansum(w*price_ret,axis=1); funding=np.nansum(-w*fsum,axis=1); gross=price+funding
    m=(idx>=START)&(idx<DEV_END)&np.isin(fold,list(DEV_FOLDS))&valid&np.isfinite(score)&np.isfinite(funding)&(np.arange(T)<max_i)
    exfold=np.full(T,-999); exfold[:max_i]=fold[exit_shift:]; m &= exfold==fold; ids=np.where(m)[0]
    fr=[]
    for fid in np.unique(fold[ids]):
        ii=ids[fold[ids]==fid]; r=rho(score[ii],funding[ii])
        if np.isfinite(r): fr.append(r)
    chosen=[]; next_i=-1
    for i in ids:
        if i<next_i: continue
        chosen.append(i); next_i=i+exit_shift
    chosen=np.array(chosen,int)
    out={"family":"cross_sectional","params":{"k":k,"nsett":nsett,"hold":hold},"state_folds":len(fr),
         "state_median_rho":float(np.median(fr)) if fr else np.nan,
         "state_posfold":float(np.mean(np.array(fr)>0)) if fr else 0.0,
         "trades":len(chosen),"symbol_count":10}
    for cname,cost in XSEC_COSTS.items():
        vals=gross[chosen]-cost; tmp=pd.DataFrame({"fold":fold[chosen],"net":vals})
        fexp=tmp.groupby("fold").net.mean(); fpf=tmp.groupby("fold").net.apply(pfv)
        out[f"{cname}_median_fold_net"]=float(fexp.median()) if len(fexp) else np.nan
        out[f"{cname}_median_fold_pf"]=float(fpf.median()) if len(fpf) else np.nan
        out[f"{cname}_posfold"]=float((fexp>0).mean()) if len(fexp) else 0.0
        out[f"{cname}_mean"]=float(np.mean(vals)) if len(vals) else np.nan
    out["state_pass"]=bool(len(fr)>=10 and out["state_median_rho"]>0 and out["state_posfold"]>=.6)
    out["prelim_pass"]=bool(out["state_pass"] and len(chosen)>=60 and out["primary_median_fold_net"]>0 and
        out["primary_median_fold_pf"]>1 and out["primary_posfold"]>=.6 and out["high_median_fold_net"]>=0)
    return out

def clean(v):
    if isinstance(v,float) and not np.isfinite(v): return None
    if isinstance(v,dict): return {k:clean(x) for k,x in v.items()}
    if isinstance(v,list): return [clean(x) for x in v]
    return v

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data-dir",required=True); ap.add_argument("--output",required=True)
    args=ap.parse_args(); D=load(Path(args.data_dir))
    grids=[]
    for f,b,h in itertools.product([5e-5,1e-4,2e-4],[0,5,10],[8,24,72,168]): grids.append(("positive",{"fund_thr":f,"basis_min":b,"hold":h}))
    for b,h,r in itertools.product([10,20,40,80],[8,24,72,168],[True,False]): grids.append(("basis",{"basis_thr":b,"hold":h,"req_nonneg":r}))
    for f,b,h in itertools.product([5e-5,1e-4,2e-4],[10,20,40],[24,72,168]): grids.append(("hybrid",{"fund_thr":f,"basis_thr":b,"hold":h}))
    for n,m,h in itertools.product([2,3,5],[5e-5,1e-4],[24,72,168]): grids.append(("persistence",{"nsett":n,"mean_thr":m,"hold":h}))
    for f,h in itertools.product([-5e-5,-1e-4,-2e-4],[24,72,168]): grids.append(("reverse",{"fund_thr":f,"hold":h}))
    single=[eval_single(D,f,p) for f,p in grids]; ctx=prepare_xsec(D)
    xsec=[eval_xsec(D,ctx,k,n,h) for k,n,h in itertools.product([1,2],[2,3,5],[8,24,72])]
    bestx=max(xsec,key=lambda o:o["primary_median_fold_net"])
    payload={"schema_version":1,"protocol":"strategy-discovery-v4-funding-basis-carry",
      "single_symbol_cells":len(single),"cross_sectional_cells":len(xsec),
      "state_pass_single_symbol":sum(o["state_pass"] for o in single),
      "state_pass_cross_sectional":sum(o["state_pass"] for o in xsec),
      "preliminary_development_pass_single_symbol":sum(o["prelim_pass"] for o in single),
      "preliminary_development_pass_cross_sectional":sum(o["prelim_pass"] for o in xsec),
      "best_cross_sectional":bestx,
      "best_single_state_pass":max((o for o in single if o["state_pass"]),key=lambda o:o["primary_median_fold_net"]),
      "holdout_opened":False,"leverage_tested":False,
      "claims":{"verified_oos":False,"profitable_edge_established":False,"live_enabled":False},
      "all_single_symbol":single,"all_cross_sectional":xsec}
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(clean(payload),indent=2))
    print(json.dumps(clean({k:v for k,v in payload.items() if k not in ("all_single_symbol","all_cross_sectional")}),indent=2))

if __name__=="__main__": main()

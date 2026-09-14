from __future__ import annotations
import argparse,json,math
from pathlib import Path
import numpy as np,pandas as pd

K=3; HOLD=72; COSTS=[12.,16.,20.]; PRIMARY=16.

def pf(a):
    a=np.asarray(a,float); p=a[a>0].sum(); n=-a[a<0].sum(); return 999. if n<=0 and p>0 else (0. if n<=0 else float(p/n))
def rho(a,b):
    a=np.asarray(a,float); b=np.asarray(b,float); m=np.isfinite(a)&np.isfinite(b)
    return float(pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank())) if m.sum()>=20 else np.nan
def clean(v):
    if isinstance(v,(float,np.floating)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,(np.integer,)):return int(v)
    if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    return v

def load(root,s,idx):
    f=pd.read_csv(root/f'{s}_futures_1h.csv',parse_dates=['timestamp']).set_index('timestamp').sort_index(); f.index=pd.to_datetime(f.index,utc=True).floor('h'); f=f[~f.index.duplicated(keep='last')]
    u=pd.read_csv(root/f'{s}_funding.csv',parse_dates=['timestamp']).set_index('timestamp').sort_index(); u.index=pd.to_datetime(u.index,utc=True).floor('h') if len(u) else u.index
    raw=pd.to_numeric(u['funding_rate'],errors='coerce').groupby(u.index).sum().sort_index() if len(u) else pd.Series(dtype=float)
    settle=raw.reindex(idx,fill_value=0.).astype(float)
    return {'open':pd.to_numeric(f.open,errors='coerce').reindex(idx),'close':pd.to_numeric(f.close,errors='coerce').reindex(idx),'raw':raw,'fcum':settle.cumsum()}

def evaluate(root,cfg,nsett):
    st=pd.Timestamp(cfg['retrospective_temporal_diagnostic']['start']); en=pd.Timestamp(cfg['retrospective_temporal_diagnostic']['end_exclusive']); idx=pd.date_range(st,en,freq='h',inclusive='left'); alpha=cfg['universe']['alpha_symbols']; syms=['BTC']+alpha; D={s:load(root,s,idx) for s in syms}
    btc_ret=D['BTC']['close'].pct_change(); beta=pd.DataFrame(index=idx,columns=alpha,dtype=float)
    for s in alpha:
        r=D[s]['close'].pct_change(); beta[s]=(r.rolling(192,min_periods=96).cov(btc_ret)/btc_ret.rolling(192,min_periods=96).var().replace(0,np.nan)).shift(1)
    fm=pd.DataFrame(index=idx,columns=alpha,dtype=float)
    for s in alpha: fm[s]=D[s]['raw'].rolling(nsett,min_periods=nsett).mean().reindex(idx,method='ffill')
    cluster=np.floor((idx-st)/pd.Timedelta(days=7)).astype(int); state=[]; trades=[]; nxt=-1; T=len(idx); shift=1+HOLD
    for i in range(T-shift):
        if cluster[i]!=cluster[i+shift]:continue
        vals=fm.iloc[i]; br=beta.iloc[i]; eligible=[]
        for s in alpha:
            ent=D[s]['open'].iloc[i+1]; ex=D[s]['open'].iloc[i+shift]
            if np.isfinite(vals[s]) and np.isfinite(br[s]) and np.isfinite(ent) and np.isfinite(ex) and ent>0 and ex>0: eligible.append(s)
        be=D['BTC']['open'].iloc[i+1]; bx=D['BTC']['open'].iloc[i+shift]
        if len(eligible)<6 or not(np.isfinite(be) and np.isfinite(bx) and be>0 and bx>0):continue
        rank=sorted(eligible,key=lambda s:(float(vals[s]),s)); low=rank[:K]; high=rank[-K:]
        w={s:0. for s in alpha}
        for s in high:w[s]=.5/K
        for s in low:w[s]=-.5/K
        nb=sum(w[s]*float(br[s]) for s in alpha); bw=-nb; norm=sum(abs(v) for v in w.values())+abs(bw)
        if not np.isfinite(norm) or norm<=0:continue
        w={s:v/norm for s,v in w.items()}; bw/=norm; score=float(vals[high].mean()-vals[low].mean()); price=0.; fund=0.
        for s,ws in w.items():
            if not ws:continue
            ent=float(D[s]['open'].iloc[i+1]); ex=float(D[s]['open'].iloc[i+shift]); pr=(ex/ent-1)*1e4; fs=float(D[s]['fcum'].iloc[i+shift]-D[s]['fcum'].iloc[i+1])*1e4; price+=ws*pr; fund+=-ws*fs
        pr=(float(bx)/float(be)-1)*1e4; fs=float(D['BTC']['fcum'].iloc[i+shift]-D['BTC']['fcum'].iloc[i+1])*1e4; price+=bw*pr; fund+=-bw*fs
        state.append((int(cluster[i]),score,price))
        if i>=nxt:
            trades.append((int(cluster[i]),price+fund,price,fund)); nxt=i+shift
    sr=pd.DataFrame(state,columns=['cluster','score','price_target']); cr=[]
    for cid,g in sr.groupby('cluster'):
        r=rho(g.score,g.price_target)
        if np.isfinite(r):cr.append((int(cid),r))
    tr=pd.DataFrame(trades,columns=['cluster','gross','price','funding'])
    out={'nsett':nsett,'state_observations':len(sr),'state_clusters':len(cr),'state_median_spearman':float(np.median([r for _,r in cr])) if cr else np.nan,'state_positive_cluster_fraction':float(np.mean([r>0 for _,r in cr])) if cr else 0.,'completed_portfolios':len(tr),'cluster_rhos':[{'cluster':c,'rho':r} for c,r in cr]}
    for cost in COSTS:
        net=tr.gross-cost if len(tr) else pd.Series(dtype=float); rev=-tr.gross-cost if len(tr) else pd.Series(dtype=float); means=tr.assign(net=net).groupby('cluster').net.mean() if len(tr) else pd.Series(dtype=float); pfs=tr.assign(net=net).groupby('cluster').net.apply(pf) if len(tr) else pd.Series(dtype=float)
        out[f'net_{cost:g}_median_cluster_bps']=float(means.median()) if len(means) else np.nan; out[f'pf_{cost:g}_median_cluster']=float(pfs.median()) if len(pfs) else np.nan; out[f'positive_cluster_fraction_{cost:g}']=float((means>0).mean()) if len(means) else 0.; out[f'mean_net_{cost:g}_bps']=float(net.mean()) if len(net) else np.nan
        if cost==PRIMARY: out['opposite_carry_control_mean_net_16_bps']=float(rev.mean()) if len(rev) else np.nan
    out['diagnostic_support']=bool(out['state_clusters']>=4 and out['state_median_spearman']>0 and out['state_positive_cluster_fraction']>=.60 and out['completed_portfolios']>=8 and out['net_16_median_cluster_bps']>0 and out['pf_16_median_cluster']>1 and out['positive_cluster_fraction_16']>=.60 and out['net_20_median_cluster_bps']>=0 and out['mean_net_16_bps']>out['opposite_carry_control_mean_net_16_bps'])
    return clean(out)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--data-dir',required=True);ap.add_argument('--output',required=True);a=ap.parse_args();cfg=json.load(open(a.config));root=Path(a.data_dir);res=[evaluate(root,cfg,n) for n in [3,5]]; out={'schema_version':1,'protocol':cfg['protocol_name'],'evidence_class':'later_period_retrospective_diagnostic_not_oos','results':res,'shadow_launch_supported':all(r['diagnostic_support'] for r in res),'future_signal_boundary':cfg['future_shadow']['signal_boundary'],'claims':{'verified_oos':False,'profitable_edge_established':False,'live_enabled':False}};Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(clean(out),indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()

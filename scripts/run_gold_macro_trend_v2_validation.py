from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

COSTS=[2.0,5.0,10.0]
PRIMARY=5.0

def sha256(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def clean(v):
    if isinstance(v,(float,np.floating)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,dict): return {k:clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    return v

def pf(a):
    a=np.asarray(a,float); p=a[a>0].sum(); n=-a[a<0].sum()
    return 999.0 if n<=0 and p>0 else (0.0 if n<=0 else float(p/n))

def rho(a,b):
    a=np.asarray(a,float); b=np.asarray(b,float); m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<5:return np.nan
    return float(pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank()))

def load_price(path: Path):
    d=pd.read_csv(path); d.columns=[str(c).lower() for c in d.columns]
    d['date']=pd.to_datetime(d['date'],utc=True,errors='coerce'); d=d.dropna(subset=['date']).set_index('date').sort_index()
    for c in ['open','high','low','close']: d[c]=pd.to_numeric(d[c],errors='coerce')
    return d[['open','high','low','close']].dropna()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--data-dir',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    cfg=json.load(open(a.config)); root=Path(a.data_dir)
    observed={name:sha256(root/name) for name in cfg['source_hashes']}
    if observed!=cfg['source_hashes']:
        raise SystemExit(f'source hash mismatch: expected={cfg["source_hashes"]}, observed={observed}')
    g=load_price(root/'gold_stooq_daily.csv'); silver=load_price(root/'silver_stooq_daily.csv').close.reindex(g.index).ffill()
    start=pd.Timestamp(cfg['validation']['start']); end=pd.Timestamp(cfg['validation']['end_exclusive']); fold_days=int(cfg['validation']['calendar_fold_days'])
    p=cfg['candidate']; window=int(p['window']); z=float(p['entry_abs_z']); hold=int(p['hold_trading_bars'])
    ratio=g.close/silver; mu=ratio.rolling(window,min_periods=window).mean(); sd=ratio.rolling(window,min_periods=window).std(); zz=(ratio-mu)/sd.replace(0,np.nan)
    score=pd.Series(np.nan,index=g.index,dtype=float); active=zz.abs()>=z; score.loc[active]=zz.loc[active]
    idx=g.index; fold=np.floor((idx-start)/pd.Timedelta(days=fold_days)).astype(int); entry=g.open.shift(-1); exitp=g.open.shift(-(1+hold)); fwd=exitp/entry-1
    sc=score.to_numpy(float); fw=fwd.to_numpy(float); inside=(idx>=start)&(idx<end); pos=np.where(inside & np.isfinite(sc)&(sc!=0)&np.isfinite(fw))[0]
    exitpos=pos+1+hold; ok=exitpos<len(g); pos,exitpos=pos[ok],exitpos[ok]; ok=(idx[exitpos]<end)&(fold[pos]==fold[exitpos]); pos=pos[ok]
    state=[]
    for fid in np.unique(fold[pos]):
        pp=pos[fold[pos]==fid]
        if len(pp)>=5:
            r=rho(sc[pp],fw[pp])
            if np.isfinite(r): state.append((int(fid),r,len(pp)))
    chosen=[]; nxt=-1
    for i in pos:
        if i<nxt: continue
        chosen.append(i); nxt=i+1+hold
    chosen=np.asarray(chosen,dtype=int); gross=np.sign(sc[chosen])*fw[chosen]*1e4 if len(chosen) else np.asarray([]); bench=fw[chosen]*1e4 if len(chosen) else np.asarray([]); cf=fold[chosen] if len(chosen) else np.asarray([],dtype=int); direction=np.sign(sc[chosen]).astype(int) if len(chosen) else np.asarray([],dtype=int)
    out={'schema_version':1,'protocol':cfg['protocol_name'],'evidence_class':cfg['evidence_class'],'candidate':p,'source_hashes_verified':True,'state_observations':int(len(pos)),'state_folds':len(state),'state_median_spearman':float(np.median([r for _,r,_ in state])) if state else np.nan,'state_positive_fold_fraction':float(np.mean([r>0 for _,r,_ in state])) if state else 0.0,'state_fold_detail':[{'fold':f,'rho':r,'observations':n} for f,r,n in state],'trades':int(len(chosen)),'long_trades':int((direction>0).sum()),'short_trades':int((direction<0).sum())}
    for cost in COSTS:
        net=gross-cost; bnet=bench-cost; exps=[]; pfs=[]; rats=[]; brats=[]
        for fid in np.unique(cf):
            v=net[cf==fid]; bv=bnet[cf==fid]; exps.append(float(np.mean(v))); pfs.append(pf(v)); rats.append(float(np.mean(v)/(np.std(v,ddof=1)+1e-9)) if len(v)>1 else 0.0); brats.append(float(np.mean(bv)/(np.std(bv,ddof=1)+1e-9)) if len(bv)>1 else 0.0)
        out[f'net_{cost:g}_median_fold_bps']=float(np.median(exps)) if exps else np.nan; out[f'pf_{cost:g}_median_fold']=float(np.median(pfs)) if pfs else np.nan; out[f'positive_fold_fraction_{cost:g}']=float(np.mean(np.asarray(exps)>0)) if exps else 0.0; out[f'mean_net_{cost:g}_bps']=float(np.mean(net)) if len(net) else np.nan
        if cost==PRIMARY:
            out['median_fold_risk_adjusted']=float(np.median(rats)) if rats else np.nan; out['benchmark_median_fold_risk_adjusted']=float(np.median(brats)) if brats else np.nan; out['benchmark_mean_net_5_bps']=float(np.mean(bnet)) if len(bnet) else np.nan; out['reversed_mean_net_5_bps']=float(np.mean(-gross-cost)) if len(gross) else np.nan
            for label,mask in [('long',direction>0),('short',direction<0)]:
                vals=net[mask]; out[f'{label}_mean_net_5_bps']=float(np.mean(vals)) if len(vals) else np.nan; out[f'{label}_median_net_5_bps']=float(np.median(vals)) if len(vals) else np.nan; out[f'{label}_win_rate_5_bps']=float(np.mean(vals>0)) if len(vals) else np.nan
    gate=cfg['gate']; out['validation_pass']=bool(out['state_folds']>=cfg['validation']['minimum_state_folds'] and out['state_median_spearman']>gate['median_state_spearman_gt'] and out['state_positive_fold_fraction']>=gate['positive_state_fold_fraction_gte'] and out['trades']>=cfg['validation']['minimum_nonoverlapping_trades'] and out['net_5_median_fold_bps']>gate['median_fold_net_primary_gt_bps'] and out['pf_5_median_fold']>gate['median_fold_profit_factor_primary_gt'] and out['positive_fold_fraction_5']>=gate['positive_economic_fold_fraction_gte'] and out['net_10_median_fold_bps']>=gate['high_cost_median_fold_net_gte_bps'] and out['mean_net_5_bps']>out['reversed_mean_net_5_bps'] and out['median_fold_risk_adjusted']>out['benchmark_median_fold_risk_adjusted'])
    out['adversarial_warning_negative_short_side']=bool(out['short_trades']>0 and out['short_mean_net_5_bps']<0)
    out['claims']={'verified_oos':False,'profitable_edge_established':False,'live_enabled':False}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(clean(out),indent=2)); print(json.dumps(clean(out),indent=2))
if __name__=='__main__': main()

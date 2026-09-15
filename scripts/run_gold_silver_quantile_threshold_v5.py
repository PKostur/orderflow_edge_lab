from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd

def clean(v):
    if isinstance(v,(float,np.floating)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    return v

def rho(a,b):
    a=pd.Series(a,dtype=float); b=pd.Series(b,dtype=float)
    m=a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    return float(a[m].rank().corr(b[m].rank())) if int(m.sum())>=5 else float('nan')

def stable_seed(base,text):
    h=hashlib.sha256(text.encode()).digest(); return int((base+int.from_bytes(h[:4],'big'))%(2**32-1))

def sign_flip(rhos,epochs,seed):
    r=np.asarray(rhos,float); r=r[np.isfinite(r)]
    if not len(r): return float('nan')
    obs=float(np.median(r))
    if obs<=0: return 1.0
    rng=np.random.default_rng(seed); ar=np.abs(r); count=0; done=0
    while done<epochs:
        n=min(2000,epochs-done); signs=rng.choice(np.array([-1.,1.]),size=(n,len(ar)))
        count+=int(np.sum(np.median(signs*ar[None,:],axis=1)>=obs)); done+=n
    return float((count+1)/(epochs+1))

def bh(pvals):
    p=np.asarray(pvals,float); q=np.full(len(p),np.nan); valid=np.where(np.isfinite(p))[0]
    if not len(valid): return q.tolist()
    order=valid[np.argsort(p[valid])]; m=len(order); raw=np.empty(m)
    for rank,idx in enumerate(order,1): raw[rank-1]=p[idx]*m/rank
    adj=np.minimum.accumulate(raw[::-1])[::-1]; adj=np.minimum(adj,1.)
    for j,idx in enumerate(order): q[idx]=adj[j]
    return q.tolist()

def load_cash(path,prefix,min_tv):
    d=pd.read_csv(path); d.columns=[str(c).strip().lower() for c in d.columns]
    req=['time','open','high','low','close','tick_volume']; miss=[c for c in req if c not in d.columns]
    if miss: raise ValueError(f'{path}: missing {miss}')
    d['time']=pd.to_datetime(d['time'],utc=True,errors='coerce').dt.floor('D')
    for c in req[1:]: d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.dropna(subset=req); d=d[(d[['open','high','low','close']]>0).all(axis=1)]
    d=d[d['tick_volume']>=min_tv]; d=d[d['time'].dt.weekday<=4]
    d=d.drop_duplicates('time',keep='last').set_index('time').sort_index()
    return d[['open','high','low','close','tick_volume']].add_prefix(prefix+'_')

def model_state(d,i,lookback,cfg):
    if i<lookback: return None
    y=np.log(d['gold_close'].iloc[i-lookback:i].to_numpy(float)); x=np.log(d['silver_close'].iloc[i-lookback:i].to_numpy(float))
    X=np.column_stack([np.ones(lookback),x]); theta,*_=np.linalg.lstsq(X,y,rcond=None)
    resid=y-X@theta; sd=float(np.std(resid,ddof=0))
    if not np.isfinite(sd) or sd<float(cfg['relationship_model']['minimum_residual_std']): return None
    beta=float(theta[1])
    if not (float(cfg['relationship_model']['beta_gt'])<beta<float(cfg['relationship_model']['beta_lt'])): return None
    cur=float(np.log(d['gold_close'].iloc[i])-theta[0]-beta*np.log(d['silver_close'].iloc[i]))
    return {'alpha':float(theta[0]),'beta':beta,'resid':cur,'sd':sd,'hist_resid':resid}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--gold',required=True); ap.add_argument('--silver',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    cfg=json.loads(Path(a.config).read_text()); mtv=int(cfg['data_admission']['minimum_tick_volume_each_leg'])
    gold=load_cash(Path(a.gold),'gold',mtv); silver=load_cash(Path(a.silver),'silver',mtv); common=gold.join(silver,how='inner').dropna().sort_index()
    dev=cfg['periods']['development']; start=pd.Timestamp(dev['start'],tz='UTC'); end=pd.Timestamp(dev['end_exclusive'],tz='UTC'); d=common.loc[(common.index>=start)&(common.index<end)].copy()
    lb=int(cfg['relationship_model']['lookback_trading_days']); h=int(cfg['state_target']['horizon_trading_bars']); cdays=int(cfg['state_first']['dependence_cluster_calendar_days'])
    fold=np.floor((d.index-start)/pd.Timedelta(days=cdays)).astype(int); lgg=np.log(d['gold_close'].to_numpy(float)); lss=np.log(d['silver_close'].to_numpy(float))
    rows=[]
    for i in range(lb,len(d)-h):
        s=model_state(d,i,lb,cfg)
        if s is None: continue
        j=i+h
        if fold[j]!=fold[i]: continue
        future=float(lgg[j]-s['alpha']-s['beta']*lss[j]); cur=s['resid']; sd=s['sd']
        for hp in cfg['tail_hypotheses']:
            q=float(hp['tail_quantile']); threshold=float(np.quantile(s['hist_resid'],q)); side=str(hp['side'])
            active=(side=='long_spread' and cur<=threshold) or (side=='short_spread' and cur>=threshold)
            if not active: continue
            depth=(threshold-cur)/sd if side=='long_spread' else (cur-threshold)/sd
            target=(future-cur)/sd if side=='long_spread' else (cur-future)/sd
            rows.append({'timestamp':str(d.index[i]),'fold':int(fold[i]),'hypothesis_id':hp['name'],'side':side,'tail_quantile':q,'predictor':float(depth),'target':float(target),'residual':cur,'threshold':threshold,'sd':sd})
    ev=pd.DataFrame(rows); results=[]; sf=cfg['state_first']
    for hp in cfg['tail_hypotheses']:
        hid=hp['name']; g=ev[ev['hypothesis_id']==hid].copy() if not ev.empty else pd.DataFrame()
        folds=[]
        if not g.empty:
            for fid,f in g.groupby('fold'):
                if len(f)<int(sf['minimum_events_per_state_fold']): continue
                r=rho(f['predictor'],f['target'])
                if not np.isfinite(r): continue
                folds.append({'fold':int(fid),'events':int(len(f)),'rho':float(r),'median_target':float(f['target'].median()),'mean_target':float(f['target'].mean())})
        rhos=[x['rho'] for x in folds]; mts=[x['median_target'] for x in folds]
        results.append({'hypothesis_id':hid,'side':hp['side'],'tail_quantile':float(hp['tail_quantile']),'events':int(len(g)),'state_folds':int(len(folds)),'folds':folds,'median_fold_spearman':float(np.median(rhos)) if rhos else np.nan,'positive_spearman_fold_fraction':float(np.mean(np.asarray(rhos)>0)) if rhos else 0.0,'median_fold_target':float(np.median(mts)) if mts else np.nan,'positive_target_fold_fraction':float(np.mean(np.asarray(mts)>0)) if mts else 0.0,'sign_flip_p':sign_flip(rhos,int(sf['sign_flip_epochs']),stable_seed(int(sf['sign_flip_seed']),hid))})
    qs=bh([x.get('sign_flip_p',np.nan) for x in results])
    for x,q in zip(results,qs):
        x['bh_fdr_q']=q
        x['state_pass']=bool(x['state_folds']>=int(sf['minimum_scorable_state_folds']) and x.get('median_fold_spearman',-np.inf)>float(sf['minimum_median_fold_spearman']) and x.get('positive_spearman_fold_fraction',0)>=float(sf['minimum_positive_spearman_fold_fraction']) and x.get('median_fold_target',-np.inf)>float(sf['minimum_median_fold_target']) and x.get('positive_target_fold_fraction',0)>=float(sf['minimum_positive_target_fold_fraction']) and x.get('bh_fdr_q',1)<=float(sf['maximum_bh_fdr_q']))
    passed=[x for x in results if x.get('state_pass')]; passed.sort(key=lambda x:(float(x.get('bh_fdr_q',1)),-float(x.get('median_fold_spearman',-np.inf)),-float(x.get('positive_target_fold_fraction',0)),-float(x.get('median_fold_target',-np.inf)),x['hypothesis_id']))
    selected=passed[:int(sf['maximum_state_tails_to_freeze'])]
    payload={'schema_version':1,'protocol':cfg['protocol_name'],'evidence_class':cfg['evidence_class'],'development_period':dev,'data_integrity':{'common_rows_all_source':int(len(common)),'development_rows':int(len(d)),'development_first_bar':str(d.index.min()),'development_last_bar':str(d.index.max())},'grid':{'hypotheses':int(len(results)),'state_passes':int(sum(bool(x.get('state_pass')) for x in results))},'selected_state_tails_for_separate_freeze':[x['hypothesis_id'] for x in selected],'pnl_tested':False,'locked_internal_validation_opened':False,'retrospective_extension_opened':False,'leverage_tested':False,'claims':cfg['claims'],'hypotheses':results}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(clean(payload),indent=2))
    print(json.dumps(clean({'hypotheses':payload['grid']['hypotheses'],'state_passes':payload['grid']['state_passes'],'selected':payload['selected_state_tails_for_separate_freeze'],'pnl_tested':False,'locked_internal_validation_opened':False}),indent=2))
if __name__=='__main__': main()

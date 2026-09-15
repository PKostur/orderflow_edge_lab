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

def stable_seed(base,text):
    h=hashlib.sha256(text.encode()).digest(); return int((base+int.from_bytes(h[:4],'big'))%(2**32-1))

def sign_flip(vals,epochs,seed):
    x=np.asarray(vals,float); x=x[np.isfinite(x)]
    if not len(x): return float('nan')
    obs=float(np.median(x))
    if obs<=0: return 1.0
    rng=np.random.default_rng(seed); ax=np.abs(x); count=0; done=0
    while done<epochs:
        n=min(2000,epochs-done); signs=rng.choice(np.array([-1.,1.]),size=(n,len(ax)))
        count+=int(np.sum(np.median(signs*ax[None,:],axis=1)>=obs)); done+=n
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

def model_state(d,i,lb,cfg):
    if i<lb: return None
    y=np.log(d['gold_close'].iloc[i-lb:i].to_numpy(float)); x=np.log(d['silver_close'].iloc[i-lb:i].to_numpy(float))
    X=np.column_stack([np.ones(lb),x]); theta,*_=np.linalg.lstsq(X,y,rcond=None)
    resid=y-X@theta; sd=float(np.std(resid,ddof=0)); beta=float(theta[1])
    if not np.isfinite(sd) or sd<float(cfg['relationship_model']['minimum_residual_std']): return None
    if not (float(cfg['relationship_model']['beta_gt'])<beta<float(cfg['relationship_model']['beta_lt'])): return None
    cur=float(np.log(d['gold_close'].iloc[i])-theta[0]-beta*np.log(d['silver_close'].iloc[i]))
    return float(theta[0]),beta,resid,sd,cur

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--gold',required=True); ap.add_argument('--silver',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    cfg=json.loads(Path(a.config).read_text()); mtv=int(cfg['data_admission']['minimum_tick_volume_each_leg'])
    gold=load_cash(Path(a.gold),'gold',mtv); silver=load_cash(Path(a.silver),'silver',mtv); common=gold.join(silver,how='inner').dropna().sort_index()
    dev=cfg['periods']['development']; start=pd.Timestamp(dev['start'],tz='UTC'); end=pd.Timestamp(dev['end_exclusive'],tz='UTC'); d=common.loc[(common.index>=start)&(common.index<end)].copy()
    lb=int(cfg['relationship_model']['lookback_trading_days']); h=int(cfg['state_target']['horizon_trading_bars']); cdays=int(cfg['state_first']['dependence_cluster_calendar_days'])
    fold=np.floor((d.index-start)/pd.Timedelta(days=cdays)).astype(int); lg=np.log(d['gold_close'].to_numpy(float)); ls=np.log(d['silver_close'].to_numpy(float))
    rows=[]
    for i in range(lb,len(d)-h):
        s=model_state(d,i,lb,cfg)
        if s is None: continue
        alpha,beta,hist,sd,cur=s; j=i+h
        if fold[j]!=fold[i]: continue
        fut=float(lg[j]-alpha-beta*ls[j])
        for hp in cfg['tail_hypotheses']:
            side=str(hp['side']); q=float(hp['tail_quantile']); threshold=float(np.quantile(hist,q))
            same_side=(cur<0) if side=='long_spread' else (cur>0)
            if not same_side: continue
            is_tail=(cur<=threshold) if side=='long_spread' else (cur>=threshold)
            target=(fut-cur)/sd if side=='long_spread' else (cur-fut)/sd
            rows.append({'fold':int(fold[i]),'hypothesis_id':hp['name'],'side':side,'is_tail':bool(is_tail),'target':float(target)})
    ev=pd.DataFrame(rows); sf=cfg['state_first']; results=[]
    for hp in cfg['tail_hypotheses']:
        hid=hp['name']; g=ev[ev['hypothesis_id']==hid].copy() if not ev.empty else pd.DataFrame(); fr=[]
        if not g.empty:
            for fid,f in g.groupby('fold'):
                tail=f[f['is_tail']]; base=f[~f['is_tail']]
                if len(tail)<int(sf['minimum_tail_events_per_fold']) or len(base)<int(sf['minimum_baseline_events_per_fold']): continue
                mt=float(tail['target'].median()); mb=float(base['target'].median()); delta=mt-mb
                fr.append({'fold':int(fid),'tail_events':int(len(tail)),'baseline_events':int(len(base)),'tail_median_target':mt,'baseline_median_target':mb,'tail_effect':float(delta)})
        effects=[x['tail_effect'] for x in fr]; targets=[x['tail_median_target'] for x in fr]
        results.append({'hypothesis_id':hid,'side':hp['side'],'tail_quantile':float(hp['tail_quantile']),'same_side_events':int(len(g)),'tail_events':int(g['is_tail'].sum()) if not g.empty else 0,'state_folds':int(len(fr)),'folds':fr,'median_fold_tail_effect':float(np.median(effects)) if effects else np.nan,'positive_tail_effect_fold_fraction':float(np.mean(np.asarray(effects)>0)) if effects else 0.0,'median_fold_tail_target':float(np.median(targets)) if targets else np.nan,'positive_tail_target_fold_fraction':float(np.mean(np.asarray(targets)>0)) if targets else 0.0,'sign_flip_p':sign_flip(effects,int(sf['sign_flip_epochs']),stable_seed(int(sf['sign_flip_seed']),hid))})
    qs=bh([x.get('sign_flip_p',np.nan) for x in results])
    for x,q in zip(results,qs):
        x['bh_fdr_q']=q
        x['state_pass']=bool(x['state_folds']>=int(sf['minimum_scorable_folds']) and x.get('median_fold_tail_effect',-np.inf)>float(sf['minimum_median_tail_effect']) and x.get('positive_tail_effect_fold_fraction',0)>=float(sf['minimum_positive_tail_effect_fold_fraction']) and x.get('median_fold_tail_target',-np.inf)>float(sf['minimum_median_tail_target']) and x.get('positive_tail_target_fold_fraction',0)>=float(sf['minimum_positive_tail_target_fold_fraction']) and x.get('bh_fdr_q',1)<=float(sf['maximum_bh_fdr_q']))
    passed=[x for x in results if x.get('state_pass')]; passed.sort(key=lambda x:(float(x.get('bh_fdr_q',1)),-float(x.get('median_fold_tail_effect',-np.inf)),-float(x.get('positive_tail_effect_fold_fraction',0)),-float(x.get('median_fold_tail_target',-np.inf)),x['hypothesis_id']))
    selected=passed[:int(sf['maximum_state_tails_to_freeze'])]
    payload={'schema_version':1,'protocol':cfg['protocol_name'],'evidence_class':cfg['evidence_class'],'development_period':dev,'data_integrity':{'common_rows_all_source':int(len(common)),'development_rows':int(len(d)),'development_first_bar':str(d.index.min()),'development_last_bar':str(d.index.max())},'grid':{'hypotheses':int(len(results)),'state_passes':int(sum(bool(x.get('state_pass')) for x in results))},'selected_state_tails_for_separate_freeze':[x['hypothesis_id'] for x in selected],'pnl_tested':False,'locked_internal_validation_opened':False,'retrospective_extension_opened':False,'leverage_tested':False,'claims':cfg['claims'],'hypotheses':results}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(clean(payload),indent=2))
    print(json.dumps(clean({'hypotheses':payload['grid']['hypotheses'],'state_passes':payload['grid']['state_passes'],'selected':payload['selected_state_tails_for_separate_freeze'],'pnl_tested':False}),indent=2))
if __name__=='__main__': main()

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def clean(v):
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def pf(values):
    x = np.asarray(values, float)
    p = float(x[x > 0].sum())
    n = float(-x[x < 0].sum())
    return 999.0 if n <= 0 and p > 0 else (0.0 if n <= 0 else p / n)


def rho(a, b):
    a = pd.Series(a, dtype=float); b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 5:
        return float('nan')
    return float(a[m].rank().corr(b[m].rank()))


def stable_seed(base, text):
    h = hashlib.sha256(text.encode()).digest()
    return int((base + int.from_bytes(h[:4], 'big')) % (2**32 - 1))


def sign_flip_pvalue(rhos, epochs, seed):
    r = np.asarray(rhos, float); r = r[np.isfinite(r)]
    if len(r) == 0: return float('nan')
    obs = float(np.median(r))
    if obs <= 0: return 1.0
    rng = np.random.default_rng(seed); ar = np.abs(r); count = 0; done = 0
    while done < epochs:
        n = min(2000, epochs-done)
        null = np.median(rng.choice(np.array([-1.0,1.0]), size=(n,len(ar))) * ar[None,:], axis=1)
        count += int(np.sum(null >= obs)); done += n
    return float((count+1)/(epochs+1))


def bh_qvalues(pvals):
    p=np.asarray(pvals,float); q=np.full(len(p),np.nan); valid=np.where(np.isfinite(p))[0]
    if len(valid)==0:return q.tolist()
    order=valid[np.argsort(p[valid])]; m=len(order); raw=np.empty(m)
    for rank,idx in enumerate(order,1): raw[rank-1]=p[idx]*m/rank
    adj=np.minimum.accumulate(raw[::-1])[::-1]; adj=np.minimum(adj,1.0)
    for j,idx in enumerate(order): q[idx]=adj[j]
    return q.tolist()


def load_gold(path, min_tv):
    d=pd.read_csv(path); d.columns=[str(c).strip().lower() for c in d.columns]
    req=['time','open','high','low','close','tick_volume']
    d['time']=pd.to_datetime(d['time'],utc=True,errors='coerce').dt.floor('D')
    for c in req[1:]:d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.dropna(subset=req); d=d[(d[['open','high','low','close']]>0).all(axis=1)]
    d=d[d['tick_volume']>=min_tv]; d=d[d['time'].dt.weekday<=4]
    return d.drop_duplicates('time',keep='last').set_index('time').sort_index()[['open','high','low','close','tick_volume']]


def load_fred(path, series):
    d=pd.read_csv(path); dc='observation_date' if 'observation_date' in d.columns else ('DATE' if 'DATE' in d.columns else d.columns[0]); vc=series if series in d.columns else d.columns[-1]
    idx=pd.to_datetime(d[dc],utc=True,errors='coerce').dt.floor('D'); val=pd.to_numeric(d[vc].replace('.',np.nan),errors='coerce')
    s=pd.Series(val.to_numpy(float),index=idx,name=series).dropna(); return s[~s.index.duplicated(keep='last')].sort_index()


def align(index,s,lag,tol):
    return s.reindex(index,method='ffill',tolerance=pd.Timedelta(days=tol)).shift(lag)


def build_score(d,vix,usd,ry,cfg):
    lag=int(cfg['data_admission']['macro_observation_lag_trading_bars']); tol=int(cfg['data_admission']['macro_asof_forward_fill_max_calendar_days'])
    w=int(cfg['shock_model']['standardization_window_trading_bars']); mp=int(cfg['shock_model']['standardization_min_periods'])
    x=pd.DataFrame(index=d.index)
    x['vix']=align(d.index,vix,lag,tol); x['usd']=align(d.index,usd,lag,tol); x['ry']=align(d.index,ry,lag,tol)
    x['dvix']=np.log(x['vix']/x['vix'].shift(1)); x['dusd']=np.log(x['usd']/x['usd'].shift(1)); x['dry']=x['ry']-x['ry'].shift(1)
    for c in ['dvix','dusd','dry']:
        mu=x[c].rolling(w,min_periods=mp).mean(); sd=x[c].rolling(w,min_periods=mp).std(ddof=1).replace(0,np.nan); x['z_'+c]=(x[c]-mu)/sd
    x['composite']=(x['z_dvix']-x['z_dusd']-x['z_dry'])/math.sqrt(3.0)
    return x


def median_fold_ra(df,col):
    vals=[]
    for _,g in df.groupby('fold'):
        a=g[col].to_numpy(float)
        if len(a)<2:continue
        sd=float(np.std(a,ddof=1))
        if sd>0 and np.isfinite(sd):vals.append(float(np.mean(a)/sd))
    return float(np.median(vals)) if vals else float('nan')


def dir_stats(df,col,side):
    g=df[df['side']==side]
    if g.empty:return {'trades':0,'mean_net_bps':np.nan,'median_net_bps':np.nan,'win_rate':np.nan}
    a=g[col].to_numpy(float); return {'trades':int(len(g)),'mean_net_bps':float(a.mean()),'median_net_bps':float(np.median(a)),'win_rate':float(np.mean(a>0))}


def hid(mode,threshold,horizon):return f"{mode}__abs{str(threshold).replace('.','p')}__h{horizon}"


def evaluate(d,score,start,cfg,mode,threshold,horizon):
    name=hid(mode,threshold,horizon); cluster=int(cfg['state_first']['dependence_cluster_calendar_days']); fold=np.floor((d.index-start)/pd.Timedelta(days=cluster)).astype(int)
    close_ret=d['close'].shift(-horizon)/d['close']-1.0
    pred=score['composite'] if mode=='continuation' else -score['composite']
    valid=np.isfinite(pred.to_numpy(float)) & (np.abs(score['composite'].to_numpy(float))>=threshold) & np.isfinite(close_ret.to_numpy(float))
    pos=np.arange(len(d)); end=pos+horizon; safe=np.minimum(end,len(d)-1); valid &= end<len(d); valid &= fold[safe]==fold
    ids=np.where(valid)[0]
    fr=[]; min_events=int(cfg['state_first']['minimum_events_per_state_fold'])
    for f in np.unique(fold[ids]):
        ii=ids[fold[ids]==f]
        if len(ii)<min_events:continue
        r=rho(pred.iloc[ii],close_ret.iloc[ii])
        if np.isfinite(r):fr.append({'fold':int(f),'rho':r,'events':int(len(ii))})
    rhos=[x['rho'] for x in fr]
    out={'hypothesis':name,'mode':mode,'threshold':float(threshold),'horizon':int(horizon),'state_events':int(len(ids)),'state_folds':int(len(fr)),'state_fold_rhos':fr,'state_median_spearman':float(np.median(rhos)) if rhos else np.nan,'state_positive_fold_fraction':float(np.mean(np.asarray(rhos)>0)) if rhos else 0.0,'state_sign_flip_p':sign_flip_pvalue(rhos,int(cfg['state_first']['sign_flip_epochs']),stable_seed(int(cfg['state_first']['sign_flip_seed']),name))}
    chosen=[]; next_allowed=-1
    for i in ids:
        if i<next_allowed:continue
        chosen.append(int(i)); next_allowed=int(i+1+horizon)
    rows=[]
    for i in chosen:
        side=int(np.sign(float(pred.iloc[i]))); entry=i+1; exitp=i+1+horizon
        if side==0 or exitp>=len(d) or fold[exitp]!=fold[i]:continue
        gross=side*(float(d['open'].iloc[exitp]/d['open'].iloc[entry]-1.0))*10000.0
        long_gold=(float(d['open'].iloc[exitp]/d['open'].iloc[entry]-1.0))*10000.0
        rows.append({'signal_time':str(d.index[i]),'fold':int(fold[i]),'side':side,'composite':float(score['composite'].iloc[i]),'gross_bps':float(gross),'equal_timing_long_gold_gross_bps':float(long_gold)})
    tr=pd.DataFrame(rows); out['trades']=int(len(tr))
    if tr.empty:return out
    costs=[float(x) for x in cfg['execution']['round_trip_cost_bps']]; primary=float(cfg['execution']['primary_cost_bps'])
    for cost in costs:
        k=f"{cost:g}"; col=f'net_{k}'; tr[col]=tr['gross_bps']-cost; fn=tr.groupby('fold')[col].mean(); fp=tr.groupby('fold')[col].apply(pf)
        out[f'net_{k}_median_fold_bps']=float(fn.median()); out[f'pf_{k}_median_fold']=float(fp.median()); out[f'positive_fold_fraction_{k}']=float((fn>0).mean()); out[f'mean_net_{k}_bps']=float(tr[col].mean())
    pk=f"{primary:g}"; pc=f'net_{pk}'; tr['long_gold_net_primary']=tr['equal_timing_long_gold_gross_bps']-primary
    out['reversed_mean_net_primary_bps']=float((-tr['gross_bps']-primary).mean()); out['strategy_median_fold_risk_adjusted_primary']=median_fold_ra(tr,pc); out['equal_timing_long_gold_median_fold_risk_adjusted_primary']=median_fold_ra(tr,'long_gold_net_primary'); out['long']=dir_stats(tr,pc,1); out['short']=dir_stats(tr,pc,-1); out['trade_rows']=tr.to_dict(orient='records')
    return out


def apply_gates(cells,cfg):
    qs=bh_qvalues([c['state_sign_flip_p'] for c in cells]); s=cfg['state_first']; e=cfg['economic_gate']; pk=f"{float(cfg['execution']['primary_cost_bps']):g}"; hk=f"{float(cfg['execution']['high_cost_bps']):g}"
    for c,q in zip(cells,qs):
        c['state_bh_q']=q; c['state_pass']=bool(c['state_folds']>=int(s['minimum_scorable_state_folds']) and c['state_median_spearman']>float(s['minimum_median_fold_spearman']) and c['state_positive_fold_fraction']>=float(s['minimum_positive_state_fold_fraction']) and q<=float(s['maximum_bh_fdr_q']))
        c['economic_pass']=bool(c['state_pass'] and c.get('trades',0)>=int(e['minimum_non_overlapping_trades']) and c.get(f'net_{pk}_median_fold_bps',-np.inf)>float(e['minimum_primary_median_fold_net_bps']) and c.get(f'pf_{pk}_median_fold',0)>=float(e['minimum_primary_median_fold_pf']) and c.get(f'positive_fold_fraction_{pk}',0)>=float(e['minimum_primary_positive_fold_fraction']) and c.get(f'net_{hk}_median_fold_bps',-np.inf)>=float(e['minimum_high_cost_median_fold_net_bps']) and c.get(f'mean_net_{pk}_bps',-np.inf)>float(e['minimum_overall_mean_primary_net_bps']) and c.get(f'mean_net_{pk}_bps',-np.inf)>c.get('reversed_mean_net_primary_bps',np.inf) and np.isfinite(c.get('strategy_median_fold_risk_adjusted_primary',np.nan)) and np.isfinite(c.get('equal_timing_long_gold_median_fold_risk_adjusted_primary',np.nan)) and c.get('strategy_median_fold_risk_adjusted_primary',-np.inf)>c.get('equal_timing_long_gold_median_fold_risk_adjusted_primary',np.inf) and c.get('long',{}).get('trades',0)>=int(e['minimum_long_trades']) and c.get('short',{}).get('trades',0)>=int(e['minimum_short_trades']) and c.get('long',{}).get('mean_net_bps',-np.inf)>0 and c.get('short',{}).get('mean_net_bps',-np.inf)>0)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--gold',required=True); ap.add_argument('--vix',required=True); ap.add_argument('--usd',required=True); ap.add_argument('--real-yield',dest='real_yield',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    cfg=json.loads(Path(a.config).read_text()); d=load_gold(Path(a.gold),int(cfg['data_admission']['minimum_tick_volume'])); dev=cfg['periods']['development']; start=pd.Timestamp(dev['start'],tz='UTC'); end=pd.Timestamp(dev['end_exclusive'],tz='UTC'); d=d.loc[(d.index>=start)&(d.index<end)].copy()
    score=build_score(d,load_fred(Path(a.vix),'VIXCLS'),load_fred(Path(a.usd),'DTWEXBGS'),load_fred(Path(a.real_yield),'DFII10'),cfg)
    cells=[]
    for mode in cfg['state_first']['modes']:
        for th in cfg['shock_model']['event_abs_composite_gte']:
            for h in cfg['state_first']['forward_horizons_trading_bars']:
                cells.append(evaluate(d,score,start,cfg,str(mode),float(th),int(h)))
    apply_gates(cells,cfg); passed=[c for c in cells if c['economic_pass']]; passed.sort(key=lambda c:(-c.get('state_median_spearman',-np.inf),-c.get('net_5_median_fold_bps',-np.inf),c['hypothesis'])); selected=passed[:int(cfg['candidate_selection']['maximum_candidates'])]
    payload={'schema_version':1,'protocol':cfg['protocol_name'],'evidence_class':cfg['evidence_class'],'development_period':dev,'data_integrity':{'development_rows':int(len(d)),'first_bar':str(d.index.min()),'last_bar':str(d.index.max()),'complete_macro_score_rows':int(score['composite'].notna().sum())},'grid':{'hypotheses':int(len(cells)),'state_passes':int(sum(c['state_pass'] for c in cells)),'economic_passes':int(len(passed))},'selected_candidates_for_separate_freeze':[c['hypothesis'] for c in selected],'cells':cells,'locked_internal_validation_opened':False,'retrospective_extension_opened':False,'leverage_tested':False,'claims':cfg['claims']}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(clean(payload),indent=2)); print(json.dumps({'state_passes':payload['grid']['state_passes'],'economic_passes':payload['grid']['economic_passes'],'selected':payload['selected_candidates_for_separate_freeze']},indent=2))

if __name__=='__main__':main()

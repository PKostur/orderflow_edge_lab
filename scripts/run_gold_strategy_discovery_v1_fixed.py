from __future__ import annotations
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

SRC=Path(__file__).with_name('run_gold_strategy_discovery_v1.py')
spec=importlib.util.spec_from_file_location('goldv1',SRC); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def evaluate_vectorized(df,family,p,hold):
    score,eligible=m.score_family(df,family,p)
    entry=df['open'].shift(-1); exit_=df['open'].shift(-(1+hold)); fwd=exit_/entry-1
    x=pd.DataFrame({'score':score,'eligible':eligible,'fwd':fwd},index=df.index)
    start=pd.Timestamp(m.START,tz='UTC'); end=pd.Timestamp(m.DEV_END,tz='UTC')
    mask=(x.index>=start)&(x.index<end)&x['eligible'].fillna(False)&x['score'].notna()&x['fwd'].notna()
    x=x.loc[mask].copy()
    if x.empty:return None
    pos=df.index.get_indexer(x.index); exit_pos=pos+1+int(hold); valid=(pos>=0)&(exit_pos<len(df)); same=np.zeros(len(x),dtype=bool)
    if valid.any():
        ef=np.asarray(m.fold_ids(x.index[valid]),dtype=int); xf=np.asarray(m.fold_ids(df.index[exit_pos[valid]]),dtype=int); same[valid]=ef==xf
    x=x.iloc[np.flatnonzero(same)].copy()
    if x.empty:return None
    x['fold']=np.asarray(m.fold_ids(x.index),dtype=int)
    fold_rho=[]
    for _,g in x.groupby('fold'):
        rho=m.spearman(g['score'],g['fwd'])
        if np.isfinite(rho):fold_rho.append(float(rho))
    state_med=float(np.median(fold_rho)) if fold_rho else np.nan; pos_frac=float(np.mean(np.asarray(fold_rho)>0)) if fold_rho else 0.0
    positions=df.index.get_indexer(x.index); scores=x['score'].to_numpy(float); fwds=x['fwd'].to_numpy(float); folds=x['fold'].to_numpy(int)
    keep=[]; next_pos=-1
    for i,p0 in enumerate(positions):
        if p0<next_pos:continue
        keep.append(i); next_pos=p0+1+int(hold)
    if not keep:return None
    k=np.asarray(keep,dtype=int); gross=np.sign(scores[k])*fwds[k]*1e4; tr=pd.DataFrame({'fold':folds[k],'gross':gross},index=x.index[k])
    out={'family':family,'params':p|{'hold':hold},'events':int(len(x)),'trades':int(len(tr)),'state_median_rho':state_med,'state_positive_fold_fraction':pos_frac}
    for cost in m.COSTS:
        vals=tr['gross']-cost; exps=[]; pfs=[]
        for _,g in tr.assign(net=vals).groupby('fold'):
            exps.append(float(g['net'].mean())); pfs.append(m.pf(g['net']))
        out[f'net_{cost:g}_median_fold']=float(np.median(exps)) if exps else np.nan; out[f'pf_{cost:g}_median_fold']=float(np.median(pfs)) if pfs else np.nan; out[f'posfold_{cost:g}']=float(np.mean(np.asarray(exps)>0)) if exps else 0.0; out[f'mean_{cost:g}']=float(vals.mean())
    out['reversed_mean_primary']=float((-tr['gross']-m.PRIMARY).mean())
    out['dev_prelim_pass']=bool(len(fold_rho)>=12 and state_med>0 and pos_frac>=.60 and len(tr)>=80 and out['net_5_median_fold']>0 and out['pf_5_median_fold']>1 and out['posfold_5']>=.60 and out['net_10_median_fold']>=0 and out['mean_5']>out['reversed_mean_primary'])
    return out

m.evaluate_fixed=evaluate_vectorized
m.main()

from __future__ import annotations
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd

SRC=Path(__file__).with_name('run_gold_social_claims_v1_1.py')
spec=importlib.util.spec_from_file_location('socialv11',SRC); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def evaluate_fixed(df,silver,family,p,hold):
    s,eligible=m.score(df,silver,family,p)
    entry=df.open.shift(-1); ex=df.open.shift(-(1+hold)); fwd=ex/entry-1
    q=pd.DataFrame({'score':s,'eligible':eligible,'fwd':fwd},index=df.index)
    mask=(q.index>=m.START)&(q.index<m.DEV_END)&q['eligible'].fillna(False)&q['score'].notna()&q['fwd'].notna()
    q=q.loc[mask].copy()
    if q.empty: return None
    pos=df.index.get_indexer(q.index)
    exit_pos=pos+1+int(hold)
    valid=(pos>=0)&(exit_pos<len(df))
    same=np.zeros(len(q),dtype=bool)
    if valid.any():
        entry_folds=np.asarray(m.fold_ids(q.index[valid]),dtype=int)
        exit_times=df.index[exit_pos[valid]]
        exit_folds=np.asarray(m.fold_ids(exit_times),dtype=int)
        same[valid]=entry_folds==exit_folds
    q=q.iloc[np.flatnonzero(same)].copy()
    if q.empty:return None
    q['fold']=np.asarray(m.fold_ids(q.index),dtype=int)
    rhos=[]
    for _,g in q.groupby('fold'):
        r=m.goldv1.spearman(g['score'],g['fwd'])
        if np.isfinite(r):rhos.append(float(r))
    if not rhos:return None
    positions=df.index.get_indexer(q.index); scores=q['score'].to_numpy(float); fwds=q['fwd'].to_numpy(float); folds=q['fold'].to_numpy(int)
    keep=[]; next_pos=-1
    for i,p0 in enumerate(positions):
        if p0<next_pos: continue
        keep.append(i); next_pos=p0+1+int(hold)
    k=np.asarray(keep,dtype=int)
    if len(k)==0:return None
    gross=np.sign(scores[k])*fwds[k]*1e4
    tr=pd.DataFrame({'fold':folds[k],'gross':gross},index=q.index[k])
    out={'family':family,'params':p|{'hold':hold},'events':int(len(q)),'trades':int(len(tr)),'state_folds':len(rhos),'state_median_rho':float(np.median(rhos)),'state_posfold':float(np.mean(np.asarray(rhos)>0))}
    for cost in m.COSTS:
        vals=tr['gross']-cost; exps=[]; pfs=[]
        for _,g in tr.assign(net=vals).groupby('fold'):
            exps.append(float(g['net'].mean())); pfs.append(m.goldv1.pf(g['net']))
        out[f'net_{cost:g}']=float(np.median(exps)); out[f'pf_{cost:g}']=float(np.median(pfs)); out[f'pos_{cost:g}']=float(np.mean(np.asarray(exps)>0)); out[f'mean_{cost:g}']=float(vals.mean())
    out['rev_mean_5']=float((-tr['gross']-m.PRIMARY).mean())
    out['prelim_pass']=bool(out['state_folds']>=12 and out['state_median_rho']>0 and out['state_posfold']>=.60 and len(tr)>=80 and out['net_5']>0 and out['pf_5']>1 and out['pos_5']>=.60 and out['net_10']>=0 and out['mean_5']>out['rev_mean_5'])
    return out

m.evaluate=evaluate_fixed
m.main()

from __future__ import annotations
import argparse, itertools, json, math
from pathlib import Path
import numpy as np
import pandas as pd

START=pd.Timestamp('2010-01-01',tz='UTC')
END=pd.Timestamp('2021-01-01',tz='UTC')
FOLD_DAYS=126
COSTS=[2.0,5.0,10.0]
PRIMARY=5.0
MIN_STATE_FOLDS=12


def pf(a):
    a=np.asarray(a,float); p=a[a>0].sum(); n=-a[a<0].sum()
    return 999.0 if n<=0 and p>0 else (0.0 if n<=0 else float(p/n))

def rho(a,b):
    a=np.asarray(a,float); b=np.asarray(b,float); m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<10:return np.nan
    return float(pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank()))

def clean(v):
    if isinstance(v,(float,np.floating)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,dict): return {k:clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    return v

def load_price(path: Path):
    d=pd.read_csv(path); d.columns=[c.lower() for c in d.columns]
    d['date']=pd.to_datetime(d['date'],utc=True,errors='coerce'); d=d.dropna(subset=['date']).set_index('date').sort_index()
    for c in ['open','high','low','close']: d[c]=pd.to_numeric(d[c],errors='coerce')
    return d[['open','high','low','close']].dropna()

def load_fred(path: Path):
    d=pd.read_csv(path)
    dates=pd.to_datetime(d.iloc[:,0],utc=True,errors='coerce')
    vals=pd.to_numeric(d.iloc[:,1].replace('.',np.nan),errors='coerce')
    s=pd.Series(vals.to_numpy(float),index=pd.DatetimeIndex(dates),name=str(d.columns[1]))
    s=s[~s.index.isna()].sort_index()
    return s[~s.index.duplicated(keep='last')]

def atr(d,n=20):
    pc=d.close.shift(1); tr=pd.concat([(d.high-d.low),(d.high-pc).abs(),(d.low-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(n,min_periods=n).mean()

def residual_z(ret, usd_ret, ry_chg, silver_ret, window):
    idx=ret.index; out=pd.Series(np.nan,index=idx,dtype=float)
    X=pd.concat([usd_ret,ry_chg,silver_ret],axis=1); X.columns=['usd','ry','silver']
    for i in range(window+5,len(idx)):
        hist=pd.concat([ret.iloc[i-window:i],X.iloc[i-window:i]],axis=1).dropna()
        if len(hist)<max(80,int(window*.7)): continue
        y=hist.iloc[:,0].to_numpy(float); xx=hist.iloc[:,1:].to_numpy(float); xx=np.column_stack([np.ones(len(xx)),xx])
        try: beta=np.linalg.lstsq(xx,y,rcond=None)[0]
        except np.linalg.LinAlgError: continue
        xr=X.iloc[i]
        if xr.isna().any() or not np.isfinite(ret.iloc[i]): continue
        pred=float(np.dot(np.r_[1.0,xr.to_numpy(float)],beta)); resid=float(ret.iloc[i]-pred)
        hist_pred=xx@beta; hist_res=y-hist_pred; sd=float(np.std(hist_res,ddof=1))
        if sd>0 and np.isfinite(sd): out.iloc[i]=resid/sd
    return out

def cells_and_scores(d, silver, ry, usd):
    c=d.close; o=d.open; ret=c.pct_change(); silver_ret=silver.pct_change(); usd_ret=usd.pct_change(); ry_chg=ry.diff(); A=atr(d,20)
    cells=[]
    for lb,h in itertools.product([63,126,252],[21,42,63]):
        cells.append(('time_series_momentum',{'lookback':lb,'hold':h},c/c.shift(lb)-1))
    for lb,h in itertools.product([55,120,252],[21,42,63]):
        hi=d.high.rolling(lb,min_periods=lb).max().shift(1); lo=d.low.rolling(lb,min_periods=lb).min().shift(1)
        sc=pd.Series(np.nan,index=d.index); sc[c>hi]=(c/hi-1)[c>hi]; sc[c<lo]=-(lo/c-1)[c<lo]
        cells.append(('donchian_breakout',{'lookback':lb,'hold':h},sc))
    for (f,s),h in itertools.product([(20,100),(50,200),(100,300)],[21,42,63]):
        ef=c.ewm(span=f,adjust=False,min_periods=f).mean(); es=c.ewm(span=s,adjust=False,min_periods=s).mean(); sc=(ef-es)/A.replace(0,np.nan)
        cells.append(('ema_trend',{'fast':f,'slow':s,'hold':h},sc))
    rng=(d.high-d.low)/A.replace(0,np.nan); mu=rng.rolling(126,min_periods=126).mean().shift(1); sd=rng.rolling(126,min_periods=126).std().shift(1); rz=(rng-mu)/sd.replace(0,np.nan)
    for z,h in itertools.product([1.0,1.5,2.0],[10,21,42]):
        sc=pd.Series(np.nan,index=d.index); active=rz>=z; sc[active]=np.sign(c-o)[active]*rz[active]
        cells.append(('volatility_breakout',{'entry_z':z,'hold':h},sc))
    for ryl,gtd,h in itertools.product([20,63,126],[63,126],[21,42,63]):
        gt=c/c.shift(gtd)-1; rc=ry-ry.shift(ryl); agree=(np.sign(gt)==-np.sign(rc))&(gt!=0)&(rc!=0)
        sc=pd.Series(np.nan,index=d.index); sc[agree]=gt[agree].abs()*np.sign(gt[agree])
        cells.append(('real_yield_gold_state',{'real_yield_days':ryl,'gold_trend_days':gtd,'hold':h},sc))
    for md,gtd,h in itertools.product([20,63],[63,126],[21,42,63]):
        gt=c/c.shift(gtd)-1; uc=usd/usd.shift(md)-1; rc=ry-ry.shift(md); agree=(np.sign(gt)==-np.sign(uc))&(np.sign(gt)==-np.sign(rc))&(gt!=0)&(uc!=0)&(rc!=0)
        sc=pd.Series(np.nan,index=d.index); sc[agree]=np.sign(gt[agree])*(gt[agree].abs()+uc[agree].abs()+rc[agree].abs()/100)
        cells.append(('usd_real_yield_confluence',{'macro_days':md,'gold_trend_days':gtd,'hold':h},sc))
    ratio=c/silver
    for win,z,mode,h in itertools.product([126,252],[1.0,1.5,2.0],['gold_relative_momentum','gold_relative_reversion'],[21,42,63]):
        mu=ratio.rolling(win,min_periods=win).mean(); sd=ratio.rolling(win,min_periods=win).std(); zz=(ratio-mu)/sd.replace(0,np.nan); active=zz.abs()>=z
        sign=np.sign(zz) if mode=='gold_relative_momentum' else -np.sign(zz); sc=pd.Series(np.nan,index=d.index); sc[active]=(sign*zz.abs())[active]
        cells.append(('gold_silver_ratio_state',{'window':win,'z':z,'mode':mode,'hold':h},sc))
    resids={w:residual_z(ret,usd_ret,ry_chg,silver_ret,w) for w in [126,252]}
    for win,z,mode,h in itertools.product([126,252],[1.0,1.5,2.0],['residual_momentum','residual_reversion'],[21,42,63]):
        zz=resids[win]; active=zz.abs()>=z; sign=np.sign(zz) if mode=='residual_momentum' else -np.sign(zz); sc=pd.Series(np.nan,index=d.index); sc[active]=(sign*zz.abs())[active]
        cells.append(('macro_residual_gold',{'window':win,'z':z,'mode':mode,'hold':h},sc))
    return cells

def evaluate(d, family, params, score):
    hold=int(params['hold']); idx=d.index; fold=np.floor((idx-START)/pd.Timedelta(days=FOLD_DAYS)).astype(int); T=len(idx)
    entry=d.open.shift(-1); exitp=d.open.shift(-(1+hold)); fwd=exitp/entry-1
    sc=score.to_numpy(float); fw=fwd.to_numpy(float); in_dev=(idx>=START)&(idx<END); pos=np.where(in_dev & np.isfinite(sc) & (sc!=0) & np.isfinite(fw))[0]
    exitpos=pos+1+hold; ok=exitpos<T; pos,exitpos=pos[ok],exitpos[ok]; ok=fold[pos]==fold[exitpos]; pos=pos[ok]
    fr=[]
    for f in np.unique(fold[pos]):
        pp=pos[fold[pos]==f]
        if len(pp)>=10:
            r=rho(sc[pp],fw[pp])
            if np.isfinite(r): fr.append((int(f),r))
    chosen=[]; nxt=-1
    for p in pos:
        if p<nxt: continue
        chosen.append(p); nxt=p+1+hold
    chosen=np.array(chosen,int); gross=np.sign(sc[chosen])*fw[chosen]*1e4 if len(chosen) else np.array([]); bench=fw[chosen]*1e4 if len(chosen) else np.array([]); cf=fold[chosen] if len(chosen) else np.array([],int)
    out={'family':family,'params':params,'events':int(len(pos)),'trades':int(len(chosen)),'state_folds':len(fr),'state_median_spearman':float(np.median([x[1] for x in fr])) if fr else np.nan,'state_positive_fold_fraction':float(np.mean([x[1]>0 for x in fr])) if fr else 0.0}
    for cost in COSTS:
        net=gross-cost; bnet=bench-cost; exps=[]; pfs=[]; ratios=[]; brats=[]
        for f in np.unique(cf):
            v=net[cf==f]; bv=bnet[cf==f]; exps.append(float(np.mean(v))); pfs.append(pf(v))
            ratios.append(float(np.mean(v)/(np.std(v,ddof=1)+1e-9)) if len(v)>1 else 0.0); brats.append(float(np.mean(bv)/(np.std(bv,ddof=1)+1e-9)) if len(bv)>1 else 0.0)
        out[f'net_{cost:g}_median_fold_bps']=float(np.median(exps)) if exps else np.nan; out[f'pf_{cost:g}_median_fold']=float(np.median(pfs)) if pfs else np.nan; out[f'posfold_{cost:g}']=float(np.mean(np.array(exps)>0)) if exps else 0.0
        if cost==PRIMARY:
            out['risk_adjusted_median_fold']=float(np.median(ratios)) if ratios else np.nan; out['benchmark_risk_adjusted_median_fold']=float(np.median(brats)) if brats else np.nan; out['mean_net_5_bps']=float(np.mean(net)) if len(net) else np.nan; out['reversed_mean_net_5_bps']=float(np.mean(-gross-cost)) if len(gross) else np.nan
    out['state_pass']=bool(out['state_folds']>=MIN_STATE_FOLDS and out['state_median_spearman']>0 and out['state_positive_fold_fraction']>=.60)
    out['economic_prepass']=bool(out['state_pass'] and out['trades']>=60 and out['net_5_median_fold_bps']>0 and out['pf_5_median_fold']>1 and out['posfold_5']>=.60 and out['net_10_median_fold_bps']>=0 and out['mean_net_5_bps']>out['reversed_mean_net_5_bps'] and out['risk_adjusted_median_fold']>max(0.0,out['benchmark_risk_adjusted_median_fold']))
    return out

def adjacent(a,b):
    if a['family']!=b['family']: return False
    pa,pb=a['params'],b['params']; keys=sorted(set(pa)|set(pb)); dif=[k for k in keys if pa.get(k)!=pb.get(k)]
    return len(dif)==1

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--data-dir',required=True); ap.add_argument('--output',required=True); args=ap.parse_args(); root=Path(args.data_dir)
    g=load_price(root/'gold_stooq_daily.csv'); s=load_price(root/'silver_stooq_daily.csv').close.reindex(g.index).ffill()
    ry=load_fred(root/'real_yield_DFII10.csv').reindex(g.index).ffill().shift(1); usd=load_fred(root/'broad_usd_DTWEXBGS.csv').reindex(g.index).ffill().shift(1)
    nominal=load_fred(root/'nominal_yield_DGS10.csv').reindex(g.index).ffill().shift(1)
    common=g.index[(g.index>=START)&(g.index<END)]; integrity={'gold_rows_dev':int(len(common)),'silver_nonnull_dev':int(s.reindex(common).notna().sum()),'real_yield_nonnull_dev':int(ry.reindex(common).notna().sum()),'broad_usd_nonnull_dev':int(usd.reindex(common).notna().sum()),'nominal_yield_nonnull_dev':int(nominal.reindex(common).notna().sum())}
    if integrity['gold_rows_dev']<2500 or min(integrity[k] for k in integrity if k!='gold_rows_dev')<2200: raise SystemExit(f'insufficient development data: {integrity}')
    cells=cells_and_scores(g,s,ry,usd); results=[]
    for family,params,score in cells: results.append(evaluate(g,family,params,score))
    for r in results:
        neigh=[x for x in results if adjacent(r,x) and x['state_pass'] and x['net_5_median_fold_bps'] is not None and x['net_5_median_fold_bps']>0 and x['pf_5_median_fold'] is not None and x['pf_5_median_fold']>1 and x['net_10_median_fold_bps'] is not None and x['net_10_median_fold_bps']>=0]
        r['neighborhood_support_count']=len(neigh); r['development_pass']=bool(r['economic_prepass'] and len(neigh)>=1)
    passes=[r for r in results if r['development_pass']]
    reps=[]
    for fam in sorted(set(r['family'] for r in passes)):
        rr=[r for r in passes if r['family']==fam]; rr.sort(key=lambda x:(x['state_median_spearman'],x['trades']),reverse=True); reps.append(rr[0])
    reps.sort(key=lambda x:(x['state_median_spearman'],x['trades']),reverse=True); reps=reps[:4]
    freeze=[{'family':r['family'],'params':r['params'],'state_median_spearman':r['state_median_spearman'],'trades':r['trades']} for r in reps]
    out={'schema_version':1,'protocol':'gold-macro-trend-v2','stage':'development_only','integrity':integrity,'cells':len(results),'state_passes':sum(r['state_pass'] for r in results),'economic_prepasses':sum(r['economic_prepass'] for r in results),'development_passes':len(passes),'candidate_freeze':freeze,'locked_internal_validation_opened':False,'claims':{'verified_oos':False,'profitable_edge_established':False,'live_enabled':False},'all_results':results}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_text(json.dumps(clean(out),indent=2))
    print(json.dumps({k:out[k] for k in ['integrity','cells','state_passes','economic_prepasses','development_passes','candidate_freeze','locked_internal_validation_opened']},indent=2))
if __name__=='__main__': main()

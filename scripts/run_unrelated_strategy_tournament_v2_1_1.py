from __future__ import annotations

import argparse, hashlib, itertools, json, math, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

SYMBOLS=['BTC_USDT','ETH_USDT','SOL_USDT','XRP_USDT','DOGE_USDT','BNB_USDT','ADA_USDT','LINK_USDT','SUI_USDT','ENA_USDT']
ALTS=SYMBOLS[1:]
START='2026-03-01'; END='2026-09-14'; COSTS=[12.,16.,20.]; PRIMARY=16.
INTERVALS={'5m':('Min5',5),'15m':('Min15',15),'1h':('Min60',60)}
FAMILIES=['sma_crossover','keltner_breakout','williams_reversal','macd_impulse','volume_shock_continuation','opening_range_breakout','cmo_reversal','atr_expansion_breakout']


def fetch(symbol,mexc_interval,minutes):
    start=int(pd.Timestamp(START,tz='UTC').timestamp()); end=int(pd.Timestamp(END,tz='UTC').timestamp()); step=minutes*60; cur=start; rows={}
    while cur<end:
        ce=min(end-1,cur+step*900); q=urlencode({'interval':mexc_interval,'start':cur,'end':ce})
        req=Request(f'https://api.mexc.com/api/v1/contract/kline/{symbol}?{q}',headers={'User-Agent':'orderflow-edge-lab/1.0'})
        with urlopen(req,timeout=30) as r: payload=json.loads(r.read().decode())
        d=payload.get('data',{})
        for i,t in enumerate(d.get('time',[])):
            t=int(t)
            if start<=t<end: rows[t]={k:float(d[k][i]) for k in ['open','high','low','close','vol']}
        cur=ce+step; time.sleep(.08)
    x=pd.DataFrame.from_dict(rows,orient='index').sort_index(); x.index=pd.to_datetime(x.index,unit='s',utc=True); x=x.rename(columns={'vol':'volume'})
    minimum=max(1000,int(60*24/minutes*30))
    if len(x)<minimum: raise RuntimeError(f'insufficient {symbol} {mexc_interval}: {len(x)}')
    return x


def atr(x,n=14):
    pc=x.close.shift(); tr=pd.concat([(x.high-x.low),(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1); return tr.rolling(n).mean()


def cmo(s,n):
    d=s.diff(); up=d.clip(lower=0).rolling(n).sum(); dn=(-d.clip(upper=0)).rolling(n).sum(); return 100*(up-dn)/(up+dn)


def willr(x,n):
    hi=x.high.rolling(n).max(); lo=x.low.rolling(n).min(); return -100*(hi-x.close)/(hi-lo)


def fold_id(idx): return pd.Series(((idx-pd.Timestamp(START,tz='UTC')).days//21).astype(int),index=idx)


def spearman(a,b):
    z=pd.concat([a,b],axis=1).dropna(); return float(z.iloc[:,0].corr(z.iloc[:,1],method='spearman')) if len(z)>=30 else math.nan


def opening_range(x,bars):
    day=x.index.floor('D'); pos=pd.Series(x.groupby(day).cumcount(),index=x.index); inside=pos<bars; p=x.loc[inside]; pdays=p.index.floor('D')
    hi=p.high.groupby(pdays).max(); lo=p.low.groupby(pdays).min(); rh=pd.Series(day.map(hi),index=x.index,dtype=float); rl=pd.Series(day.map(lo),index=x.index,dtype=float)
    complete=pos>=(bars-1); tradable=pos>=bars; return rh.where(complete),rl.where(complete),tradable


def variants(x,interval,minutes):
    A=atr(x); out=[]
    for f,s in itertools.product([10,20,40],[50,100,200]):
        if f<s: out.append(('sma_crossover',{'fast':f,'slow':s},(x.close.rolling(f).mean()-x.close.rolling(s).mean())/A,20,{}))
    for n,m,h in itertools.product([20,40],[1.5,2.,2.5],[20,40]):
        ema=x.close.ewm(span=n,adjust=False).mean(); out.append(('keltner_breakout',{'ema':n,'atr':14,'mult':m,'max_hold':h},(x.close-ema)/(A*m),h,{'ema':ema}))
    for n,os,ob,h in itertools.product([14,28],[-90,-80],[-20,-10],[6,12]):
        w=willr(x,n); out.append(('williams_reversal',{'period':n,'oversold':os,'overbought':ob,'max_hold':h},-(w+50)/50,h,{'wr':w}))
    for f,s,sg,h in itertools.product([8,12],[21,26],[5,9],[20,40]):
        if f>=s: continue
        mac=x.close.ewm(span=f,adjust=False).mean()-x.close.ewm(span=s,adjust=False).mean(); hist=mac-mac.ewm(span=sg,adjust=False).mean()
        out.append(('macd_impulse',{'fast':f,'slow':s,'signal':sg,'max_hold':h},hist/hist.rolling(96).std(),h,{'hist':hist}))
    for vw,vz,lb,h in itertools.product([48,96],[1.5,2.],[1,3],[6,12]):
        lv=np.log1p(x.volume); z=(lv-lv.rolling(vw).mean())/lv.rolling(vw).std(); ret=np.log(x.close/x.close.shift(lb))
        out.append(('volume_shock_continuation',{'volume_window':vw,'volume_z':vz,'return_lookback':lb,'max_hold':h},ret*z.clip(lower=0),h,{'volume_z_series':z,'lookback_return':ret}))
    for n,t,h in itertools.product([14,28],[40,50,60],[6,12]):
        c=cmo(x.close,n); out.append(('cmo_reversal',{'period':n,'threshold':t,'max_hold':h},-c/100,h,{'cmo':c}))
    for b,q,h in itertools.product([20,40],[.60,.75],[20,40]):
        ph=x.high.shift().rolling(b).max(); pl=x.low.shift().rolling(b).min(); d=pd.Series(np.where(x.close>ph,1,np.where(x.close<pl,-1,0)),index=x.index); flt=A>A.rolling(96).quantile(q)
        score=pd.Series(np.where(d>0,(x.close-ph)/A,np.where(d<0,(x.close-pl)/A,0)),index=x.index).where(flt,0)
        out.append(('atr_expansion_breakout',{'breakout':b,'atr_period':14,'atr_window':96,'atr_quantile':q,'max_hold':h},score,h,{'direction':d,'filter':flt}))
    bph=60//minutes
    for rh,hh in itertools.product([1,2,4],[4,8,12]):
        bars=rh*bph; hold=hh*bph; hi,lo,tradable=opening_range(x,bars); score=pd.Series(np.where(x.close>hi,(x.close-hi)/A,np.where(x.close<lo,(x.close-lo)/A,0)),index=x.index).where(tradable,0)
        out.append(('opening_range_breakout',{'range_hours':rh,'max_hold_hours':hh},score,hold,{'range_high':hi,'range_low':lo,'tradable':tradable}))
    return out


def entries(fam,p,score,aux):
    if fam=='sma_crossover': return np.sign(score).fillna(0).astype(int)
    if fam=='keltner_breakout': return pd.Series(np.where(score>=1,1,np.where(score<=-1,-1,0)),index=score.index)
    if fam=='williams_reversal':
        w=aux['wr']; return pd.Series(np.where(w<=p['oversold'],1,np.where(w>=p['overbought'],-1,0)),index=score.index)
    if fam=='macd_impulse':
        h=aux['hist']; return pd.Series(np.where((h>0)&(h.shift(1)<=0),1,np.where((h<0)&(h.shift(1)>=0),-1,0)),index=score.index)
    if fam=='volume_shock_continuation':
        z=aux['volume_z_series']; r=aux['lookback_return']; active=z>=p['volume_z']; return pd.Series(np.where(active&(r>0),1,np.where(active&(r<0),-1,0)),index=score.index)
    if fam=='cmo_reversal':
        c=aux['cmo']; t=p['threshold']; return pd.Series(np.where(c<=-t,1,np.where(c>=t,-1,0)),index=score.index)
    if fam=='atr_expansion_breakout': return aux['direction'].where(aux['filter'],0).fillna(0).astype(int)
    if fam=='opening_range_breakout':
        raw=pd.Series(np.where(aux['tradable']&(score>0),1,np.where(aux['tradable']&(score<0),-1,0)),index=score.index); day=score.index.floor('D'); first=pd.Series(0,index=score.index,dtype=int)
        for _,idx in raw.groupby(day).groups.items():
            nz=raw.loc[idx]; nz=nz[nz!=0]
            if not nz.empty: first.loc[nz.index[0]]=int(nz.iloc[0])
        return first
    raise ValueError(fam)


def should_exit(fam,p,side,i,score,aux,x):
    if fam=='sma_crossover':
        v=score.iloc[i]; return bool(np.isfinite(v) and np.sign(v)==-side)
    if fam=='keltner_breakout': return bool((side>0 and x.close.iloc[i]<=aux['ema'].iloc[i]) or (side<0 and x.close.iloc[i]>=aux['ema'].iloc[i]))
    if fam=='williams_reversal':
        w=aux['wr'].iloc[i]; return bool((side>0 and w>=-50) or (side<0 and w<=-50))
    if fam=='macd_impulse':
        h=aux['hist'].iloc[i]; return bool((side>0 and h<0) or (side<0 and h>0))
    if fam=='volume_shock_continuation': return False
    if fam=='cmo_reversal':
        c=aux['cmo'].iloc[i]; return bool((side>0 and c>=0) or (side<0 and c<=0))
    if fam=='atr_expansion_breakout': return bool(aux['direction'].iloc[i]==-side)
    if fam=='opening_range_breakout':
        c=x.close.iloc[i]; hi=aux['range_high'].iloc[i]; lo=aux['range_low'].iloc[i]; return bool((side>0 and c<=hi) or (side<0 and c>=lo))
    raise ValueError(fam)


def simulate(x,fam,p,score,hold,aux):
    fids=fold_id(x.index); signal=entries(fam,p,score,aux); rows=[]; i=0; n=len(x)
    while i<n-2:
        side=int(signal.iloc[i]) if pd.notna(signal.iloc[i]) else 0
        if side==0: i+=1; continue
        entry=i+1; fold=int(fids.iloc[i])
        if int(fids.iloc[entry])!=fold: i+=1; continue
        last=min(i+hold,n-2); exit_signal=last
        for j in range(entry,last+1):
            if int(fids.iloc[j])!=fold: exit_signal=j-1; break
            if should_exit(fam,p,side,j,score,aux,x): exit_signal=j; break
        exit_i=exit_signal+1
        if exit_i>=n or exit_i<=entry or int(fids.iloc[exit_i])!=fold: i+=1; continue
        raw=(x.open.iloc[exit_i]/x.open.iloc[entry]-1)*1e4; rows.append({'fold':fold,'side':side,'raw_bps':float(raw),'gross_bps':float(side*raw)}); i=exit_i
    return rows


def perm_p(trades,iterations,seed):
    if not trades: return math.nan
    observed=float(np.mean([r[4] for r in trades])); groups={}
    for sym,fold,side,raw,gross in trades: groups.setdefault((sym,fold),[]).append((side,raw))
    rng=np.random.default_rng(seed); exceed=0
    for _ in range(iterations):
        total=0.; count=0
        for vals in groups.values():
            sides=np.asarray([v[0] for v in vals]); raw=np.asarray([v[1] for v in vals]); total+=float(np.dot(rng.permutation(sides),raw)); count+=len(vals)
        if count and total/count>=observed: exceed+=1
    return float((exceed+1)/(iterations+1))


def one_axis_neighbor(a,b):
    a=json.loads(a); b=json.loads(b)
    if set(a)!=set(b): return False
    return sum(a[k]!=b[k] for k in a)==1


def main(outdir):
    out=Path(outdir); out.mkdir(parents=True,exist_ok=True); state=[]; econ=[]; assoc=[]
    for interval,(mexc_interval,minutes) in INTERVALS.items():
        frames={s:fetch(s,mexc_interval,minutes) for s in SYMBOLS}
        pairvals={}
        for sym in ALTS:
            vv=variants(frames[sym],interval,minutes); reps={}
            for fam in FAMILIES:
                c=[v for v in vv if v[0]==fam]
                if c: reps[fam]=sorted(c,key=lambda v:json.dumps(v[1],sort_keys=True))[0][2]
            for i,a in enumerate(FAMILIES):
                for b in FAMILIES[i+1:]:
                    if a in reps and b in reps:
                        r=spearman(reps[a],reps[b])
                        if math.isfinite(r): pairvals.setdefault((a,b),[]).append(r)
        for (a,b),vals in pairvals.items():
            r=float(np.median(vals)); assoc.append({'interval':interval,'family_a':a,'family_b':b,'median_symbol_spearman':r,'absolute_median_spearman':abs(r),'high_redundancy':abs(r)>=.8})
        for sym in ALTS:
            x=frames[sym]; fids=fold_id(x.index)
            for fam,p,score,h,aux in variants(x,interval,minutes):
                target=np.log(x.close.shift(-h)/x.close).where(fids.eq(fids.shift(-h))); rr=[]
                for f in sorted(fids.unique()): rr.append(spearman(score[fids.eq(f)],target[fids.eq(f)]))
                good=[v for v in rr if math.isfinite(v)]; state.append({'interval':interval,'symbol':sym,'family':fam,'params':json.dumps(p,sort_keys=True),'h':h,'folds':len(good),'median_rho':float(np.median(good)) if good else math.nan,'positive_fold_fraction':float(np.mean(np.asarray(good)>0)) if good else 0.})
        local=pd.DataFrame([r for r in state if r['interval']==interval]); agg=local.groupby(['interval','family','params','h']).agg(symbols=('symbol','nunique'),minimum_folds=('folds','min'),median_rho=('median_rho','median'),positive_fold_fraction=('positive_fold_fraction','median')).reset_index()
        agg['state_pass']=(agg.symbols>=8)&(agg.minimum_folds>=6)&(agg.median_rho>0)&(agg.positive_fold_fraction>=.6)
        for _,g in agg[agg.state_pass].iterrows():
            fam=g.family; p=json.loads(g.params); h=int(g.h); trades=[]
            for sym in ALTS:
                x=frames[sym]; m=[v for v in variants(x,interval,minutes) if v[0]==fam and json.dumps(v[1],sort_keys=True)==g.params and v[3]==h]
                if not m: continue
                _,_,score,_,aux=m[0]
                for t in simulate(x,fam,p,score,h,aux): trades.append((sym,t['fold'],t['side'],t['raw_bps'],t['gross_bps']))
            seed=int.from_bytes(hashlib.sha256(f'{interval}|{fam}|{g.params}|{h}'.encode()).digest()[:8],'big')%(2**32); pp=perm_p(trades,2000,seed)
            for cost in COSTS:
                folds={}; syms={}; rev=[]
                for sym,fold,side,raw,gross in trades:
                    net=gross-cost; folds.setdefault(fold,[]).append(net); syms.setdefault(sym,[]).append(net); rev.append(-gross-cost)
                fm=[float(np.mean(v)) for v in folds.values()]; sm=[float(np.mean(v)) for v in syms.values()]; fps=[]
                for vals in folds.values():
                    a=np.asarray(vals); w=a[a>0].sum(); l=-a[a<0].sum(); fps.append(float(w/l) if l>0 else (1e6 if w>0 else 0.))
                econ.append({'interval':interval,'family':fam,'params':g.params,'h':h,'cost_bps':cost,'trades':sum(len(v) for v in folds.values()),'folds':len(folds),'symbols':len(syms),'median_fold_net_bps':float(np.median(fm)) if fm else math.nan,'median_fold_profit_factor':float(np.median(fps)) if fps else math.nan,'positive_fold_fraction':float(np.mean(np.asarray(fm)>0)) if fm else 0.,'positive_symbol_fraction':float(np.mean(np.asarray(sm)>0)) if sm else 0.,'reversed_mean_net_bps':float(np.mean(rev)) if rev else math.nan,'randomized_direction_pvalue':pp})
    sdf=pd.DataFrame(state); sagg=sdf.groupby(['interval','family','params','h']).agg(symbols=('symbol','nunique'),minimum_folds=('folds','min'),median_rho=('median_rho','median'),positive_fold_fraction=('positive_fold_fraction','median')).reset_index(); sagg['state_pass']=(sagg.symbols>=8)&(sagg.minimum_folds>=6)&(sagg.median_rho>0)&(sagg.positive_fold_fraction>=.6)
    edf=pd.DataFrame(econ)
    if len(edf):
        edf['base_economic_pass']=(edf.cost_bps==PRIMARY)&(edf.trades>=80)&(edf.folds>=6)&(edf.symbols>=8)&(edf.median_fold_net_bps>0)&(edf.median_fold_profit_factor>1)&(edf.positive_fold_fraction>=.6)&(edf.positive_symbol_fraction>=.6)&(edf.median_fold_net_bps>edf.reversed_mean_net_bps)
        edf['parameter_neighborhood_support']=False
        for idx in edf.index[edf.base_economic_pass]:
            r=edf.loc[idx]; peers=edf[(edf.index!=idx)&(edf.interval==r.interval)&(edf.family==r.family)&(edf.cost_bps==PRIMARY)&(edf.base_economic_pass)]
            edf.loc[idx,'parameter_neighborhood_support']=any(one_axis_neighbor(r.params,p.params) for _,p in peers.iterrows())
        edf['economic_pass']=edf.base_economic_pass&edf.parameter_neighborhood_support
    else:
        edf['base_economic_pass']=pd.Series(dtype=bool); edf['parameter_neighborhood_support']=pd.Series(dtype=bool); edf['economic_pass']=pd.Series(dtype=bool)
    adf=pd.DataFrame(assoc); sdf.to_csv(out/'state_by_symbol.csv',index=False); sagg.to_csv(out/'state_aggregate.csv',index=False); edf.to_csv(out/'economics.csv',index=False); adf.to_csv(out/'feature_association.csv',index=False)
    summary={'protocol':'unrelated-strategy-tournament-v2.1.1-state-first','intervals':list(INTERVALS),'state_variants':int(len(sagg)),'state_passes':int(sagg.state_pass.sum()) if len(sagg) else 0,'economic_rows':int(len(edf)),'high_redundancy_pairs':int(adf.high_redundancy.sum()) if len(adf) else 0,'primary_economic_passes':int(edf.economic_pass.sum()) if len(edf) else 0,'claims':{'profitable_edge_established':False,'untouched_oos':False,'live':False}}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True); a=p.parse_args(); main(a.out)

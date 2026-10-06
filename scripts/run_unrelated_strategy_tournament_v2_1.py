from __future__ import annotations

import argparse, itertools, json, math, random, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

SYMBOLS=['BTC_USDT','ETH_USDT','SOL_USDT','XRP_USDT','DOGE_USDT','BNB_USDT','ADA_USDT','LINK_USDT','SUI_USDT','ENA_USDT']
ALTS=SYMBOLS[1:]
START='2026-03-01'; END='2026-09-12'; COSTS=[12.,16.,20.]; PRIMARY=16.

def fetch(symbol, interval='Min60'):
    start=int(pd.Timestamp(START,tz='UTC').timestamp()); end=int(pd.Timestamp(END,tz='UTC').timestamp()); step=3600; cur=start; rows={}
    while cur<end:
        ce=min(end-1,cur+step*900)
        q=urlencode({'interval':interval,'start':cur,'end':ce})
        req=Request(f'https://api.mexc.com/api/v1/contract/kline/{symbol}?{q}',headers={'User-Agent':'orderflow-edge-lab/1.0'})
        with urlopen(req,timeout=30) as r: p=json.loads(r.read().decode())
        d=p.get('data',{})
        for i,t in enumerate(d.get('time',[])):
            if start<=int(t)<end:
                rows[int(t)]={k:float(d[k][i]) for k in ['open','high','low','close','vol']}
        cur=ce+step; time.sleep(.15)
    x=pd.DataFrame.from_dict(rows,orient='index').sort_index(); x.index=pd.to_datetime(x.index,unit='s',utc=True); x=x.rename(columns={'vol':'volume'})
    if len(x)<1000: raise RuntimeError(f'insufficient {symbol}: {len(x)}')
    return x

def atr(x,n=14):
    pc=x.close.shift(); tr=pd.concat([(x.high-x.low),(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1); return tr.rolling(n).mean()

def cmo(s,n):
    d=s.diff(); up=d.clip(lower=0).rolling(n).sum(); dn=(-d.clip(upper=0)).rolling(n).sum(); return 100*(up-dn)/(up+dn)

def willr(x,n):
    hi=x.high.rolling(n).max(); lo=x.low.rolling(n).min(); return -100*(hi-x.close)/(hi-lo)

def fold_id(idx): return ((idx-pd.Timestamp(START,tz='UTC')).days//21).astype(int)

def score_variants(x):
    A=atr(x); out=[]
    for f,s in [(10,30),(20,50)]: out.append(('sma_crossover',{'fast':f,'slow':s},(x.close.rolling(f).mean()-x.close.rolling(s).mean())/A,20))
    for n,m,h in itertools.product([20,40],[1.5,2.0],[12,24]):
        ema=x.close.ewm(span=n,adjust=False).mean(); out.append(('keltner_breakout',{'ema':n,'mult':m,'hold':h},(x.close-ema)/(A*m),h))
    for n,h in itertools.product([14,28],[12,24]): out.append(('williams_reversal',{'lookback':n,'hold':h},-(willr(x,n)+50)/50,h))
    for fast,slow,sig,h in [(12,26,9,12),(12,26,9,24),(8,21,5,12),(8,21,5,24)]:
        mac=x.close.ewm(span=fast,adjust=False).mean()-x.close.ewm(span=slow,adjust=False).mean(); hist=mac-mac.ewm(span=sig,adjust=False).mean(); out.append(('macd_impulse',{'fast':fast,'slow':slow,'signal':sig,'hold':h},hist/hist.rolling(96).std(),h))
    lr=np.log(x.close).diff(); vz=(np.log1p(x.volume)-np.log1p(x.volume).rolling(96).mean())/np.log1p(x.volume).rolling(96).std()
    for lb,z,h in itertools.product([1,4],[1.5,2.0],[12,24]): out.append(('volume_shock_continuation',{'lookback':lb,'volume_z':z,'hold':h},np.log(x.close/x.close.shift(lb))*vz.clip(lower=0),h))
    for n,h in itertools.product([14,28],[12,24]): out.append(('cmo_reversal',{'lookback':n,'hold':h},-cmo(x.close,n)/100,h))
    for w,q,h in itertools.product([20,40],[.7,.85],[12,24]):
        prev_hi=x.high.shift().rolling(w).max(); prev_lo=x.low.shift().rolling(w).min(); direction=pd.Series(np.where(x.close>prev_hi,1,np.where(x.close<prev_lo,-1,0)),index=x.index); aq=A>A.rolling(96).quantile(q); dist=pd.Series(np.where(direction>0,(x.close-prev_hi)/A,np.where(direction<0,(x.close-prev_lo)/A,0)),index=x.index); out.append(('atr_expansion_breakout',{'window':w,'atr_q':q,'hold':h},dist.where(aq,0),h))
    day=x.index.floor('D'); first4=x.groupby(day).head(4); hi=first4.high.groupby(first4.index.floor('D')).max(); lo=first4.low.groupby(first4.index.floor('D')).min(); dh=pd.Series(day.map(hi),index=x.index); dl=pd.Series(day.map(lo),index=x.index); sc=pd.Series(np.where(x.close>dh,(x.close-dh)/A,np.where(x.close<dl,(x.close-dl)/A,0)),index=x.index)
    for h in [12,24]: out.append(('opening_range_breakout',{'opening_bars':4,'hold':h},sc,h))
    return out

def spearman(a,b):
    z=pd.concat([a,b],axis=1).dropna(); return float(z.iloc[:,0].corr(z.iloc[:,1],method='spearman')) if len(z)>=30 else math.nan

def main(outdir):
    out=Path(outdir); out.mkdir(parents=True,exist_ok=True); frames={s:fetch(s) for s in SYMBOLS}; state=[]; econ=[]
    for sym in ALTS:
        x=frames[sym].copy(); fids=pd.Series(fold_id(x.index),index=x.index)
        for fam,params,sc,h in score_variants(x):
            target=np.log(x.close.shift(-h)/x.close); valid=fids.eq(fids.shift(-h)); target=target.where(valid)
            fold_r=[]
            for f in sorted(fids.dropna().unique()): fold_r.append(spearman(sc[fids.eq(f)],target[fids.eq(f)]))
            good=[v for v in fold_r if math.isfinite(v)]; med=float(np.median(good)) if good else math.nan; pos=float(np.mean(np.array(good)>0)) if good else 0
            state.append({'symbol':sym,'family':fam,'params':json.dumps(params,sort_keys=True),'h':h,'folds':len(good),'median_rho':med,'positive_fold_fraction':pos})
    sdf=pd.DataFrame(state); grouped=sdf.groupby(['family','params','h']).agg(symbols=('symbol','nunique'),median_rho=('median_rho','median'),positive_fold_fraction=('positive_fold_fraction','median')).reset_index(); grouped['state_pass']=(grouped.symbols>=8)&(grouped.median_rho>0)&(grouped.positive_fold_fraction>=.6)
    for _,g in grouped[grouped.state_pass].iterrows():
        params=json.loads(g.params); fam=g.family; h=int(g.h); trades=[]
        for sym in ALTS:
            x=frames[sym]; fids=pd.Series(fold_id(x.index),index=x.index); matches=[v for v in score_variants(x) if v[0]==fam and json.dumps(v[1],sort_keys=True)==g.params and v[3]==h]
            if not matches: continue
            sc=matches[0][2]; direction=np.sign(sc); entry=x.open.shift(-1); exitp=x.open.shift(-(h+1)); ok=fids.eq(fids.shift(-(h+1))); gross=direction*(exitp/entry-1)*1e4
            for f in sorted(fids.unique()):
                vals=gross[fids.eq(f)&ok&(direction!=0)].dropna().values
                if len(vals): trades.append((sym,int(f),vals))
        for cost in COSTS:
            folds={}; syms={}; allv=[]
            for sym,f,vals in trades:
                net=vals-cost; folds.setdefault(f,[]).extend(net); syms.setdefault(sym,[]).extend(net); allv.extend(net)
            fm=[np.mean(v) for v in folds.values()]; sm=[np.mean(v) for v in syms.values()]; arr=np.array(allv); wins=arr[arr>0].sum(); losses=-arr[arr<0].sum(); pf=float(wins/losses) if losses>0 else 1e6
            rev=-np.array([v for _,_,vals in trades for v in vals])-cost
            econ.append({'family':fam,'params':g.params,'h':h,'cost_bps':cost,'trades':len(arr),'folds':len(folds),'symbols':len(syms),'median_fold_net_bps':float(np.median(fm)) if fm else math.nan,'profit_factor':pf,'positive_fold_fraction':float(np.mean(np.array(fm)>0)) if fm else 0,'positive_symbol_fraction':float(np.mean(np.array(sm)>0)) if sm else 0,'reversed_mean_net_bps':float(np.mean(rev)) if len(rev) else math.nan})
    edf=pd.DataFrame(econ); edf['economic_pass']=(edf.cost_bps==PRIMARY)&(edf.trades>=80)&(edf.folds>=6)&(edf.symbols>=8)&(edf.median_fold_net_bps>0)&(edf.profit_factor>1)&(edf.positive_fold_fraction>=.6)&(edf.positive_symbol_fraction>=.6)&(edf.median_fold_net_bps>edf.reversed_mean_net_bps)
    sdf.to_csv(out/'state_by_symbol.csv',index=False); grouped.to_csv(out/'state_aggregate.csv',index=False); edf.to_csv(out/'economics.csv',index=False)
    summary={'protocol':'unrelated-strategy-tournament-v2.1-state-first','state_variants':int(len(grouped)),'state_passes':int(grouped.state_pass.sum()),'economic_rows':int(len(edf)),'primary_economic_passes':int(edf.economic_pass.sum()),'claims':{'profitable_edge_established':False,'untouched_oos':False,'live':False}}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True); a=p.parse_args(); main(a.out)

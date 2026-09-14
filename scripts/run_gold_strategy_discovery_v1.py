from __future__ import annotations
import argparse, itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
START=pd.Timestamp('2010-01-01'); DEV_END=pd.Timestamp('2024-01-01'); FOLD_DAYS=63; COSTS=[2.0,5.0,10.0]; PRIMARY=5.0

def load_csv(path: Path) -> pd.DataFrame:
    df=pd.read_csv(path); cols={c.lower():c for c in df.columns}; tcol=cols.get('time') or cols.get('date') or df.columns[0]
    df[tcol]=pd.to_datetime(df[tcol],errors='coerce',utc=True); df=df.dropna(subset=[tcol]).set_index(tcol).sort_index(); df.columns=[c.lower() for c in df.columns]
    for c in ['open','high','low','close','tick_volume','volume']:
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors='coerce')
    if 'volume' not in df.columns: df['volume']=df.get('tick_volume',0.0)
    return df[['open','high','low','close','volume']].dropna()

def ema(s,n): return s.ewm(span=n,adjust=False,min_periods=n).mean()
def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0); au=up.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=au/ad.replace(0,np.nan); return 100-100/(1+rs)
def atr(df,n=14):
    pc=df.close.shift(1); tr=pd.concat([(df.high-df.low).abs(),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def rolling_z(s,n):
    m=s.rolling(n,min_periods=max(10,n//2)).mean(); sd=s.rolling(n,min_periods=max(10,n//2)).std(ddof=0); return (s-m)/sd.replace(0,np.nan)
def spearman(a,b):
    a=pd.Series(a,dtype=float); b=pd.Series(b,dtype=float); m=a.notna()&b.notna()&np.isfinite(a)&np.isfinite(b)
    if m.sum()<20:return np.nan
    return float(a[m].rank().corr(b[m].rank()))
def pf(vals):
    a=np.asarray(vals,float); p=a[a>0].sum(); n=-a[a<0].sum(); return 999.0 if n<=0 and p>0 else (0.0 if n<=0 else float(p/n))
def fold_ids(idx): return np.floor((idx-pd.Timestamp(START,tz='UTC'))/pd.Timedelta(days=FOLD_DAYS)).astype(int)
def session_vwap(df):
    day=df.index.floor('D'); tp=(df.high+df.low+df.close)/3; pv=tp*df.volume; return pv.groupby(day).cumsum()/df.volume.groupby(day).cumsum().replace(0,np.nan)

def score_family(df,family,p):
    c=df.close; a=atr(df); eligible=pd.Series(True,index=df.index)
    if family=='ema_trend':
        f=ema(c,p['fast']); s=ema(c,p['slow']); score=(f-s)/a; eligible &= score.notna(); return score,eligible
    if family=='donchian_breakout':
        hi=df.high.shift(1).rolling(p['lookback']).max(); lo=df.low.shift(1).rolling(p['lookback']).min(); score=pd.Series(0.0,index=df.index); score=score.mask(c>hi,(c-hi)/a); score=score.mask(c<lo,(c-lo)/a); eligible &= score.ne(0); return score,eligible
    if family=='bollinger_mean_reversion':
        m=c.rolling(p['length']).mean(); sd=c.rolling(p['length']).std(ddof=0); z=(c-m)/sd.replace(0,np.nan); score=-z; eligible &= z.abs()>=p['stdev']; return score,eligible
    if family=='rsi_mean_reversion':
        x=rsi(c,p['length']); score=(50-x)/25.0; eligible &= ((x<=p['level'])|(x>=100-p['level'])); return score,eligible
    if family=='atr_range_breakout':
        rz=rolling_z((df.high-df.low)/c,96); score=np.sign(c.pct_change())*rz.clip(lower=0); eligible &= rz>=p['range_z']; return score,eligible
    if family=='trend_pullback':
        e=ema(c,p['ema']); trend=np.sign(e.diff(8)); dist=(c-e)/a; score=trend*(-dist); eligible &= (trend!=0)&(dist.abs()>=p['pullback_atr'])&(np.sign(dist)==-trend); return score,eligible
    if family=='reddit_ema_4_21_cross':
        f=ema(c,4); s=ema(c,21); d=f-s; score=d/a; cross=(np.sign(d)!=np.sign(d.shift(1)))&d.notna()&d.shift(1).notna(); eligible &= cross; return score,eligible
    if family=='reddit_ema_50_200_rsi_atr':
        f=ema(c,50); s=ema(c,200); x=rsi(c,14); score=(f-s)/a; eligible &= (((score>0)&(x>=p['rsi']))|((score<0)&(x<=100-p['rsi']))); return score,eligible
    if family=='youtube_ema_9_21_rsi':
        f=ema(c,9); s=ema(c,21); x=rsi(c,14); score=(f-s)/a; eligible &= (((score>0)&(x>=p['rsi']))|((score<0)&(x<=100-p['rsi']))); eligible &= ((np.sign((f-s).diff(3))==np.sign(score)) if p['slope'] else True); return score,eligible
    if family=='previous_day_high_low_rejection':
        day=df.index.floor('D'); dh=df.high.groupby(day).transform('max'); dl=df.low.groupby(day).transform('min'); prev_hi=dh.groupby(day).first().shift(1).reindex(day).set_axis(df.index); prev_lo=dl.groupby(day).first().shift(1).reindex(day).set_axis(df.index); long=(df.low<prev_lo)&(c>prev_lo)&((c-prev_lo)>=p['rej']*a); short=(df.high>prev_hi)&(c<prev_hi)&((prev_hi-c)>=p['rej']*a); score=pd.Series(0.0,index=df.index); score[long]=1; score[short]=-1; eligible &= score.ne(0); return score,eligible
    if family=='london_orb_sweep':
        hour=df.index.hour; day=df.index.floor('D'); pre_hi=df.high.where((hour>=4)&(hour<7)).groupby(day).transform('max'); pre_lo=df.low.where((hour>=4)&(hour<7)).groupby(day).transform('min'); london=pd.Series(hour>=7,index=df.index); lseq=london.groupby(day).cumsum()-1; orb_hi=df.high.where(london&(lseq<p['opening_bars'])).groupby(day).transform('max'); orb_lo=df.low.where(london&(lseq<p['opening_bars'])).groupby(day).transform('min'); sweep_lo=(df.low.rolling(p['sweep_lb']).min()<pre_lo)&(c>pre_lo); sweep_hi=(df.high.rolling(p['sweep_lb']).max()>pre_hi)&(c<pre_hi); long=(hour>=7)&(c>orb_hi)&sweep_lo; short=(hour>=7)&(c<orb_lo)&sweep_hi; score=pd.Series(0.0,index=df.index); score[long]=1; score[short]=-1; eligible &= score.ne(0); return score,eligible
    if family in ('turtle_soup_session_sweep','fake_breakout_reversal_proxy'):
        hi=df.high.shift(1).rolling(p['lookback']).max(); lo=df.low.shift(1).rolling(p['lookback']).min(); swept_hi=(df.high>hi)&(c<hi); swept_lo=(df.low<lo)&(c>lo); score=pd.Series(0.0,index=df.index); score[swept_lo]=1; score[swept_hi]=-1
        if p.get('confirm',1)>1: score=score.where((np.sign(c.diff())==np.sign(score))|(score==0),0)
        eligible &= score.ne(0); return score,eligible
    if family=='smc_sweep_choch_fvg_proxy':
        hi=df.high.shift(1).rolling(p['lookback']).max(); lo=df.low.shift(1).rolling(p['lookback']).min(); disp=(c-df.open).abs()/a; sweep_hi=(df.high>hi)&(c<hi); sweep_lo=(df.low<lo)&(c>lo); long=sweep_lo&(c>df.high.shift(1).rolling(3).max())&(disp>=p['disp']); short=sweep_hi&(c<df.low.shift(1).rolling(3).min())&(disp>=p['disp']); score=pd.Series(0.0,index=df.index); score[long]=1; score[short]=-1; eligible &= score.ne(0); return score,eligible
    if family=='vwap_ema_atr_rsi_confluence':
        v=session_vwap(df); e=ema(c,50); x=rsi(c,14); rz=rolling_z((df.high-df.low)/c,96); pret=c.pct_change(5); xr=x.diff(5); div=np.sign(pret)!=np.sign(xr); long=(c>v)&(c>e)&(rz>=p['atr_z'])&div&(x>50); short=(c<v)&(c<e)&(rz>=p['atr_z'])&div&(x<50); score=pd.Series(0.0,index=df.index); score[long]=1; score[short]=-1; eligible &= score.ne(0); return score,eligible
    raise ValueError(family)

def evaluate_fixed(df,family,p,hold):
    score,eligible=score_family(df,family,p); entry=df.open.shift(-1); exit_=df.open.shift(-(1+hold)); fwd=exit_/entry-1; x=pd.DataFrame({'score':score,'eligible':eligible,'fwd':fwd},index=df.index); x=x[(x.index>=pd.Timestamp(START,tz='UTC'))&(x.index<pd.Timestamp(DEV_END,tz='UTC'))&x.eligible&x.score.notna()&x.fwd.notna()].copy(); x['fold']=fold_ids(x.index); exitts=pd.Series(df.index,index=df.index).shift(-(1+hold)).reindex(x.index); same=[fold_ids(pd.DatetimeIndex([t]))[0]==fold_ids(pd.DatetimeIndex([et]))[0] for t,et in zip(x.index,exitts)]; x=x[same]
    fold_rho=[]
    for _,g in x.groupby('fold'):
        r=spearman(g.score,g.fwd)
        if np.isfinite(r): fold_rho.append(r)
    state_med=float(np.median(fold_rho)) if fold_rho else np.nan; state_pos=float(np.mean(np.array(fold_rho)>0)) if fold_rho else 0
    rows=[]; next_allowed=pd.Timestamp.min.tz_localize('UTC')
    for t,r in x.iterrows():
        if t<next_allowed: continue
        side=1 if r.score>0 else -1; rows.append((t,int(r['fold']),side*r.fwd*1e4)); loc=df.index.get_loc(t); next_allowed=df.index[min(loc+1+hold,len(df)-1)]
    if not rows:return None
    tr=pd.DataFrame(rows,columns=['t','fold','gross']).set_index('t'); out={'family':family,'params':p|{'hold':hold},'events':len(x),'trades':len(tr),'state_median_rho':state_med,'state_positive_fold_fraction':state_pos}
    for cost in COSTS:
        vals=tr.gross-cost; exps=[]; pfs=[]
        for _,g in tr.assign(net=vals).groupby('fold'): exps.append(float(g.net.mean())); pfs.append(pf(g.net))
        out[f'net_{cost:g}_median_fold']=float(np.median(exps)) if exps else np.nan; out[f'pf_{cost:g}_median_fold']=float(np.median(pfs)) if pfs else np.nan; out[f'posfold_{cost:g}']=float(np.mean(np.array(exps)>0)) if exps else 0; out[f'mean_{cost:g}']=float(vals.mean())
    out['reversed_mean_primary']=float((-tr.gross-PRIMARY).mean()); out['dev_prelim_pass']=bool(len(fold_rho)>=12 and state_med>0 and state_pos>=.60 and len(tr)>=80 and out['net_5_median_fold']>0 and out['pf_5_median_fold']>1 and out['posfold_5']>=.60 and out['net_10_median_fold']>=0 and out['mean_5']>out['reversed_mean_primary']); return out

def grids():
    yield 'ema_trend','H1', (({'fast':f,'slow':s},h) for f,s,h in itertools.product([20,50],[50,200],[4,8,16]) if f<s); yield 'ema_trend','H4', (({'fast':f,'slow':s},h) for f,s,h in itertools.product([20,50],[50,200],[4,8,16]) if f<s)
    for tf in ['H1','H4','D1']: yield 'donchian_breakout',tf, (({'lookback':lb},h) for lb,h in itertools.product([20,55],[4,8,16]))
    for tf in ['H1','H4']:
        yield 'bollinger_mean_reversion',tf, (({'length':20,'stdev':sd},h) for sd,h in itertools.product([2.0,2.5],[4,8,16])); yield 'rsi_mean_reversion',tf, (({'length':14,'level':lv},h) for lv,h in itertools.product([30,25],[4,8,16])); yield 'atr_range_breakout',tf, (({'range_z':z},h) for z,h in itertools.product([1.0,1.5,2.0],[4,8,16])); yield 'trend_pullback',tf, (({'ema':e,'pullback_atr':pa},h) for e,pa,h in itertools.product([50,100],[.5,1.0],[4,8,16]))
    for tf in ['M15','H1']: yield 'reddit_ema_4_21_cross',tf, (({},h) for h in [4,8,16])
    yield 'reddit_ema_50_200_rsi_atr','H1', (({'rsi':r},h) for r,h in itertools.product([55,60],[4,8,16])); yield 'youtube_ema_9_21_rsi','M15', (({'rsi':r,'slope':sl},h) for r,sl,h in itertools.product([52,55,60],[False,True],[4,8,16]))
    for tf in ['M15','H1']: yield 'previous_day_high_low_rejection',tf, (({'rej':r},h) for r,h in itertools.product([.1,.25,.5],[4,8,16]))
    yield 'london_orb_sweep','M15', (({'opening_bars':o,'sweep_lb':lb},h) for o,lb,h in itertools.product([2,4],[8,16],[4,8]))
    for tf in ['M15','H1']:
        yield 'turtle_soup_session_sweep',tf, (({'lookback':lb,'confirm':cf},h) for lb,cf,h in itertools.product([20,48],[1,2],[4,8,16])); yield 'fake_breakout_reversal_proxy',tf, (({'lookback':lb,'confirm':cf},h) for lb,cf,h in itertools.product([20,48],[1,2],[4,8,16])); yield 'smc_sweep_choch_fvg_proxy',tf, (({'lookback':lb,'disp':d},h) for lb,d,h in itertools.product([20,48],[.75,1.25],[4,8,16]))
    yield 'vwap_ema_atr_rsi_confluence','M15', (({'atr_z':z},h) for z,h in itertools.product([.5,1.0],[4,8]))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--data-dir',required=True); ap.add_argument('--output',required=True); args=ap.parse_args(); d=Path(args.data_dir); frames={tf:load_csv(d/f'XAUUSD_{tf}_2010_2026.csv') for tf in ['M15','H1','H4','D1']}; integrity={tf:{'rows':len(df),'start':str(df.index.min()),'end':str(df.index.max()),'median_bars_per_day':float(pd.Series(1,index=df.index).groupby(df.index.floor('D')).sum().median())} for tf,df in frames.items()}; results=[]
    for fam,tf,g in grids():
        for p,h in g:
            try:
                r=evaluate_fixed(frames[tf],fam,p,h)
                if r:r['timeframe']=tf; results.append(r)
            except Exception as e: results.append({'family':fam,'timeframe':tf,'params':p|{'hold':h},'error':repr(e),'dev_prelim_pass':False})
    valid=[r for r in results if 'error' not in r and r is not None]; valid.sort(key=lambda r:(r.get('dev_prelim_pass',False),r.get('net_5_median_fold',-1e99),r.get('state_median_rho',-1e99)),reverse=True); out={'schema_version':1,'protocol':'gold-strategy-discovery-v1','integrity':integrity,'trial_count':len(results),'error_count':sum(isinstance(r,dict) and 'error' in r for r in results),'prelim_pass_count':sum(bool(r.get('dev_prelim_pass')) for r in valid),'top_development':valid[:50],'all_trials':results,'holdout_opened':False,'claims':{'verified_oos':False,'profitable_edge_established':False,'live_enabled':False}}; Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_text(json.dumps(out,indent=2,allow_nan=False)); print(json.dumps({'trial_count':out['trial_count'],'error_count':out['error_count'],'prelim_pass_count':out['prelim_pass_count'],'integrity':integrity,'top':valid[:10]},indent=2,allow_nan=False))
if __name__=='__main__': main()

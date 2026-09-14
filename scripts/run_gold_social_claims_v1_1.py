from __future__ import annotations
import argparse, importlib.util, itertools, json
from pathlib import Path
import numpy as np
import pandas as pd

BASE=Path(__file__).with_name('run_gold_strategy_discovery_v1.py')
spec=importlib.util.spec_from_file_location('goldv1', BASE); goldv1=importlib.util.module_from_spec(spec); spec.loader.exec_module(goldv1)
START=pd.Timestamp('2020-01-01',tz='UTC'); DEV_END=pd.Timestamp('2024-01-01',tz='UTC'); FOLD_DAYS=63; COSTS=[2.0,5.0,10.0]; PRIMARY=5.0

def combine(paths):
    frames=[goldv1.load_csv(Path(p)) for p in paths]; df=pd.concat(frames).sort_index(); return df[~df.index.duplicated(keep='last')]
def fold_ids(idx): return np.floor((idx-START)/pd.Timedelta(days=FOLD_DAYS)).astype(int)
def session_mask(idx):
    h=idx.hour
    return ((h>=7)&(h<11))|((h>=13)&(h<17))
def score(df, silver, family, p):
    c=df.close; a=goldv1.atr(df); e9=goldv1.ema(c,9); eligible=pd.Series(True,index=df.index)
    if family=='youtube_ema21_50_rsi_session':
        e21=goldv1.ema(c,21); e50=goldv1.ema(c,50); x=goldv1.rsi(c,14); s=(e21-e50)/a
        eligible &= session_mask(df.index) & (((s>0)&(x>=p['rsi']))|((s<0)&(x<=100-p['rsi'])))
        return s,eligible
    if family=='youtube_double_rsi_ema9_fib_proxy':
        rf=goldv1.rsi(c,p['rf']); rs=goldv1.rsi(c,p['rs']); mom=(rf-rs)/10.0
        hi=df.high.shift(1).rolling(p['lb']).max(); lo=df.low.shift(1).rolling(p['lb']).min(); span=(hi-lo).replace(0,np.nan)
        retr=(hi-c)/span
        long=(mom>0)&(c>e9)&retr.between(.382,.618); short=(mom<0)&(c<e9)&((c-lo)/span).between(.382,.618)
        s=pd.Series(0.0,index=df.index); s[long]=mom[long].abs(); s[short]=-mom[short].abs(); eligible &= s.ne(0); return s,eligible
    if family.startswith('gold_silver_'):
        idx=df.index.intersection(silver.index); x=df.loc[idx]; y=silver.loc[idx]; lr=np.log(x.close).diff(); sr=np.log(y.close).diff(); lb=p['lb']; rel=(lr-sr).rolling(lb,min_periods=lb).sum(); z=goldv1.rolling_z(rel,max(96,lb*4)); s=(-z if family.endswith('reversal') else z).reindex(df.index); eligible &= s.abs()>=p['z']; return s,eligible
    if family=='new_york_sweep_choch_proxy':
        h=df.index.hour; hi=df.high.shift(1).rolling(p['lb']).max(); lo=df.low.shift(1).rolling(p['lb']).min(); disp=(c-df.open).abs()/a
        sweep_hi=(df.high>hi)&(c<hi); sweep_lo=(df.low<lo)&(c>lo); long=(h>=11)&(h<17)&sweep_lo&(c>df.high.shift(1).rolling(3).max())&(disp>=p['disp']); short=(h>=11)&(h<17)&sweep_hi&(c<df.low.shift(1).rolling(3).min())&(disp>=p['disp']); s=pd.Series(0.0,index=df.index); s[long]=1; s[short]=-1; eligible &= s.ne(0); return s,eligible
    raise ValueError(family)

def evaluate(df,silver,family,p,hold):
    s,eligible=score(df,silver,family,p); entry=df.open.shift(-1); ex=df.open.shift(-(1+hold)); fwd=ex/entry-1
    q=pd.DataFrame({'score':s,'eligible':eligible,'fwd':fwd},index=df.index); q=q[(q.index>=START)&(q.index<DEV_END)&q.eligible&q.score.notna()&q.fwd.notna()].copy(); q['fold']=fold_ids(q.index)
    et=pd.Series(df.index,index=df.index).shift(-(1+hold)).reindex(q.index); same=[]
    for t,u in zip(q.index,et): same.append(False if pd.isna(u) else int(fold_ids(pd.DatetimeIndex([t]))[0])==int(fold_ids(pd.DatetimeIndex([u]))[0])); q=q[same]
    rhos=[]
    for _,g in q.groupby('fold'):
        r=goldv1.spearman(g.score,g.fwd)
        if np.isfinite(r): rhos.append(r)
    if not rhos:return None
    trades=[]; next_allowed=pd.Timestamp.min.tz_localize('UTC')
    for t,r in q.iterrows():
        if t<next_allowed: continue
        side=1 if r.score>0 else -1; trades.append((t,int(r['fold']),side*r.fwd*1e4)); pos=df.index.searchsorted(t); next_allowed=df.index[min(pos+1+hold,len(df)-1)]
    if not trades:return None
    tr=pd.DataFrame(trades,columns=['t','fold','gross']).set_index('t'); out={'family':family,'params':p|{'hold':hold},'events':len(q),'trades':len(tr),'state_folds':len(rhos),'state_median_rho':float(np.median(rhos)),'state_posfold':float(np.mean(np.array(rhos)>0))}
    for cost in COSTS:
        vals=tr.gross-cost; exps=[]; pfs=[]
        for _,g in tr.assign(net=vals).groupby('fold'): exps.append(float(g.net.mean())); pfs.append(goldv1.pf(g.net))
        out[f'net_{cost:g}']=float(np.median(exps)); out[f'pf_{cost:g}']=float(np.median(pfs)); out[f'pos_{cost:g}']=float(np.mean(np.array(exps)>0)); out[f'mean_{cost:g}']=float(vals.mean())
    out['rev_mean_5']=float((-tr.gross-5).mean()); out['prelim_pass']=bool(out['state_folds']>=12 and out['state_median_rho']>0 and out['state_posfold']>=.60 and len(tr)>=80 and out['net_5']>0 and out['pf_5']>1 and out['pos_5']>=.60 and out['net_10']>=0 and out['mean_5']>out['rev_mean_5']); return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--data-dir',required=True); ap.add_argument('--output',required=True); a=ap.parse_args(); d=Path(a.data_dir)
    m1=combine([d/'XAUUSD_M1_2020_2022.csv',d/'XAUUSD_M1_2023_2026.csv']); m15=goldv1.load_csv(d/'XAUUSD_M15_2010_2026.csv'); h1=goldv1.load_csv(d/'XAUUSD_H1_2010_2026.csv'); sm15=goldv1.load_csv(d/'XAGUSD_M15.csv'); sh1=goldv1.load_csv(d/'XAGUSD_H1.csv')
    trials=[]
    def add(fam,df,sil,params,holds):
        for p,h in itertools.product(params,holds):
            try:
                r=evaluate(df,sil,fam,p,h)
                if r: trials.append(r)
            except Exception as e: trials.append({'family':fam,'params':p|{'hold':h},'error':repr(e),'prelim_pass':False})
    add('youtube_ema21_50_rsi_session',m1,None,[{'rsi':x} for x in [52,55,60]],[5,15,30,60]); add('youtube_ema21_50_rsi_session',m15,None,[{'rsi':x} for x in [52,55,60]],[4,8,16])
    add('youtube_double_rsi_ema9_fib_proxy',m1,None,[{'rf':rf,'rs':rs,'lb':lb} for rf,rs,lb in itertools.product([7,9],[14,21],[30,60])],[5,15,30])
    for fam in ['gold_silver_smt_reversal','gold_silver_relative_strength_momentum_control']:
        add(fam,m15,sm15,[{'lb':lb,'z':z} for lb,z in itertools.product([20,48,96],[.5,1.0])],[4,8,16]); add(fam,h1,sh1,[{'lb':lb,'z':z} for lb,z in itertools.product([20,48,96],[.5,1.0])],[4,8,16])
    add('new_york_sweep_choch_proxy',m15,None,[{'lb':lb,'disp':di} for lb,di in itertools.product([20,48],[.75,1.25])],[4,8,16])
    valid=[x for x in trials if 'error' not in x]; valid.sort(key=lambda r:(r.get('prelim_pass',False),r.get('net_5',-1e99),r.get('state_median_rho',-1e99)),reverse=True); out={'schema_version':1,'protocol':'gold-social-claims-v1.1','trial_count':len(trials),'error_count':sum('error'in x for x in trials),'prelim_pass_count':sum(x.get('prelim_pass',False) for x in valid),'top':valid[:50],'all_trials':trials,'holdout_opened':False,'claims':{'verified_oos':False,'profitable_edge_established':False,'live_enabled':False}}; Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,indent=2,allow_nan=False)); print(json.dumps({'trial_count':out['trial_count'],'errors':out['error_count'],'passes':out['prelim_pass_count'],'top':valid[:10]},indent=2,allow_nan=False))
if __name__=='__main__': main()

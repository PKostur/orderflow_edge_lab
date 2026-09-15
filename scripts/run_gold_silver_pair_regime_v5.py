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


def pf(values) -> float:
    x = np.asarray(values, float)
    pos = float(x[x > 0].sum())
    neg = float(-x[x < 0].sum())
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return pos / neg


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float); b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 5:
        return float('nan')
    return float(a[m].rank(method='average').corr(b[m].rank(method='average')))


def load_cash(path: Path, prefix: str, min_tick: int) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    need = ['time','open','high','low','close','tick_volume']
    if any(c not in d.columns for c in need):
        raise ValueError(f'{path}: missing expected columns')
    d['time'] = pd.to_datetime(d['time'], utc=True, errors='coerce').dt.floor('D')
    for c in need[1:]: d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=need)
    d = d[(d[['open','high','low','close']] > 0).all(axis=1)]
    d = d[d['tick_volume'] >= min_tick]
    d = d[d['time'].dt.weekday <= 4]
    d = d.drop_duplicates('time', keep='last').set_index('time').sort_index()
    return d[['open','high','low','close','tick_volume']].add_prefix(prefix+'_')


def adaptive_states(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m = cfg['pair_model']; warm = int(m['initial_warmup_trading_days']); lam = float(m['forgetting_factor'])
    y = np.log(d['gold_close'].to_numpy(float)); x = np.log(d['silver_close'].to_numpy(float))
    out = pd.DataFrame(index=d.index, columns=['alpha','beta','innovation','innovation_sd','z'], dtype=float)
    X0 = np.column_stack([np.ones(warm), x[:warm]])
    theta, *_ = np.linalg.lstsq(X0, y[:warm], rcond=None)
    resid = y[:warm] - X0 @ theta; var = float(np.var(resid, ddof=0))
    gram = (X0.T @ X0) / float(warm); P = np.linalg.inv(gram + 1e-8*np.eye(2))
    for i in range(warm, len(d)):
        xt = np.array([1.0, x[i]], float); pred = float(xt @ theta); innov = float(y[i]-pred)
        sd = float(math.sqrt(max(var,1e-12))); out.iloc[i] = [float(theta[0]),float(theta[1]),innov,sd,innov/sd]
        Px=P@xt; den=float(lam+xt@Px); K=Px/den; theta=theta+K*innov; P=(P-np.outer(K,xt)@P)/lam; P=0.5*(P+P.T)
        var=float(lam*var+(1-lam)*innov*innov)
    return out


def admitted(s: pd.Series, cfg: dict) -> bool:
    m=cfg['pair_model']; vals=[s.get('alpha'),s.get('beta'),s.get('innovation'),s.get('innovation_sd'),s.get('z')]
    return all(np.isfinite(float(v)) for v in vals) and float(s['beta'])>float(m['beta_gt']) and float(s['beta'])<float(m['beta_lt'])


def prior_zscore(raw: pd.Series, window: int) -> pd.Series:
    h=raw.shift(1); mu=h.rolling(window,min_periods=window).mean(); sd=h.rolling(window,min_periods=window).std(ddof=0)
    return (raw-mu)/sd.replace(0,np.nan)


def pair_close_return(d: pd.DataFrame, i0: int, i1: int, beta: float) -> float:
    gr=float(d['gold_close'].iloc[i1]/d['gold_close'].iloc[i0]-1.0); sr=float(d['silver_close'].iloc[i1]/d['silver_close'].iloc[i0]-1.0)
    b=abs(beta); wg=1/(1+b); ws=b/(1+b); return float(wg*gr-ws*sr)


def pair_open_components(d: pd.DataFrame, i0: int, i1: int, beta: float) -> tuple[float,float,float]:
    gr=float(d['gold_open'].iloc[i1]/d['gold_open'].iloc[i0]-1.0); sr=float(d['silver_open'].iloc[i1]/d['silver_open'].iloc[i0]-1.0)
    b=abs(beta); wg=1/(1+b); ws=b/(1+b)
    return float(wg*gr-ws*sr), gr, float(0.5*gr-0.5*sr)


def build_features(d: pd.DataFrame, states: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    w=int(cfg['feature_engineering']['standardization_window_trading_days'])
    n=len(d); beta=states['beta']; z=states['z']
    raw_trend=pd.Series(np.nan,index=d.index,dtype=float)
    for i in range(21,n):
        if np.isfinite(beta.iloc[i]): raw_trend.iloc[i]=pair_close_return(d,i-21,i,float(beta.iloc[i]))
    trend_std=prior_zscore(raw_trend,w)
    signz=np.sign(z)
    trend_support=-signz*trend_std

    prior5=z.shift(1).rolling(5,min_periods=5).mean()
    innov_std=prior_zscore(prior5,w)
    innovation_support=-signz*innov_std

    daily_pair=pd.Series(np.nan,index=d.index,dtype=float)
    for i in range(1,n):
        if np.isfinite(beta.iloc[i]): daily_pair.iloc[i]=pair_close_return(d,i-1,i,float(beta.iloc[i]))
    rv21=daily_pair.rolling(21,min_periods=21).std(ddof=0)
    vol_support=-prior_zscore(rv21,w)

    beta_change=(beta/beta.shift(21)-1.0).abs()
    beta_support=-prior_zscore(beta_change,w)

    f=pd.DataFrame(index=d.index)
    f['trend_reversion_support_21']=trend_support
    f['innovation_reversal_support_5']=innovation_support
    f['low_pair_volatility_support_21']=vol_support
    f['stable_beta_support_21']=beta_support
    f['equal_weight_pair_regime_support']=f[['trend_reversion_support_21','innovation_reversal_support_5','low_pair_volatility_support_21','stable_beta_support_21']].mean(axis=1,skipna=False)
    return f


def stable_seed(base:int,text:str)->int:
    return int((base+int.from_bytes(hashlib.sha256(text.encode()).digest()[:4],'big'))%(2**32-1))


def sign_flip_pvalue(rhos:list[float],epochs:int,seed:int)->float:
    r=np.asarray(rhos,float); r=r[np.isfinite(r)]
    if len(r)==0:return float('nan')
    obs=float(np.median(r))
    if obs<=0:return 1.0
    rng=np.random.default_rng(seed); a=np.abs(r); count=0; done=0
    while done<epochs:
        k=min(2000,epochs-done); signs=rng.choice(np.array([-1.,1.]),size=(k,len(a)))
        count+=int(np.sum(np.median(signs*a[None,:],axis=1)>=obs)); done+=k
    return float((count+1)/(epochs+1))


def bh_qvalues(pvals:list[float])->list[float]:
    p=np.asarray(pvals,float); q=np.full(len(p),np.nan); valid=np.where(np.isfinite(p))[0]
    if len(valid)==0:return q.tolist()
    order=valid[np.argsort(p[valid])]; m=len(order); raw=np.array([p[idx]*m/r for r,idx in enumerate(order,1)])
    adj=np.minimum.accumulate(raw[::-1])[::-1]
    for j,idx in enumerate(order):q[idx]=min(float(adj[j]),1.0)
    return q.tolist()


def state_results(d:pd.DataFrame,states:pd.DataFrame,features:pd.DataFrame,start:pd.Timestamp,cfg:dict)->list[dict]:
    s=cfg['state_first']; h=int(s['horizon_trading_bars']); days=int(s['dependence_cluster_calendar_days'])
    folds=np.floor((d.index-start)/pd.Timedelta(days=days)).astype(int); event_z=float(cfg['pair_model']['event_abs_innovation_z_gte'])
    out=[]
    for feature in cfg['feature_engineering']['features'].keys():
        rows=[]
        for i in range(len(d)-h):
            st=states.iloc[i]; score=features[feature].iloc[i]
            if not admitted(st,cfg) or abs(float(st['z']))<event_z or not np.isfinite(score):continue
            j=i+h
            if folds[j]!=folds[i]:continue
            pr=pair_close_return(d,i,j,float(st['beta'])); target=float(-np.sign(float(st['z']))*pr)
            rows.append({'fold':int(folds[i]),'score':float(score),'target':target})
        f=pd.DataFrame(rows); fr=[]
        if not f.empty:
            for fid,g in f.groupby('fold'):
                if len(g)<int(s['minimum_events_per_fold']):continue
                r=rho(g['score'],g['target'])
                if np.isfinite(r):fr.append({'fold':int(fid),'rho':float(r),'events':int(len(g))})
        rs=[x['rho'] for x in fr]
        out.append({'feature':feature,'events':int(len(f)),'positive_score_event_fraction':float((f['score']>0).mean()) if not f.empty else 0.0,'negative_score_event_fraction':float((f['score']<0).mean()) if not f.empty else 0.0,'scorable_folds':int(len(fr)),'fold_rhos':fr,'median_fold_spearman':float(np.median(rs)) if rs else np.nan,'positive_fold_fraction':float(np.mean(np.asarray(rs)>0)) if rs else 0.0,'sign_flip_p':sign_flip_pvalue(rs,int(s['sign_flip_epochs']),stable_seed(int(s['sign_flip_seed']),feature))})
    qs=bh_qvalues([x['sign_flip_p'] for x in out])
    for x,q in zip(out,qs):
        x['bh_q']=q; x['state_pass']=bool(x['events']>=int(s['minimum_total_events']) and x['scorable_folds']>=int(s['minimum_scorable_folds']) and x['positive_score_event_fraction']>=float(s['minimum_positive_score_event_fraction']) and x['negative_score_event_fraction']>=float(s['minimum_negative_score_event_fraction']) and x['median_fold_spearman']>float(s['minimum_median_fold_spearman']) and x['positive_fold_fraction']>=float(s['minimum_positive_fold_fraction']) and x['bh_q']<=float(s['maximum_bh_fdr_q']))
    return out


def fold_ra(frame:pd.DataFrame,col:str)->float:
    vals=[]
    for _,g in frame.groupby('fold'):
        x=g[col].to_numpy(float)
        if len(x)<2:continue
        sd=float(np.std(x,ddof=1))
        if np.isfinite(sd) and sd>0:vals.append(float(np.mean(x)/sd))
    return float(np.median(vals)) if vals else float('nan')


def side_stats(tr:pd.DataFrame,col:str,side:int)->dict:
    g=tr[tr['pair_side']==side]
    if g.empty:return {'trades':0,'mean_net_bps':np.nan,'median_net_bps':np.nan,'win_rate':np.nan}
    x=g[col].to_numpy(float); return {'trades':int(len(g)),'mean_net_bps':float(np.mean(x)),'median_net_bps':float(np.median(x)),'win_rate':float(np.mean(x>0))}


def simulate(d:pd.DataFrame,states:pd.DataFrame,features:pd.DataFrame,feature:str,threshold:float,hold:int,start:pd.Timestamp,state_pass:bool,cfg:dict)->dict:
    days=int(cfg['state_first']['dependence_cluster_calendar_days']); folds=np.floor((d.index-start)/pd.Timedelta(days=days)).astype(int)
    event_z=float(cfg['pair_model']['event_abs_innovation_z_gte']); rows=[]; i=0
    while i+hold+1<len(d):
        st=states.iloc[i]; score=features[feature].iloc[i]
        if not admitted(st,cfg) or abs(float(st['z']))<event_z or not np.isfinite(score) or abs(float(score))<threshold or float(score)==0:
            i+=1;continue
        entry=i+1; exitp=entry+hold
        if folds[exitp]!=folds[i]:i+=1;continue
        mr_side=int(-np.sign(float(st['z']))); cont_side=-mr_side; regime_side=mr_side if score>0 else cont_side
        pair,gold,static=pair_open_components(d,entry,exitp,float(st['beta']))
        rows.append({'fold':int(folds[i]),'pair_side':int(regime_side),'regime_choice':'reversion' if score>0 else 'continuation','score':float(score),'event_z':float(st['z']),'gross_bps':float(regime_side*pair*10000),'reversed_regime_gross_bps':float(-regime_side*pair*10000),'always_mr_gross_bps':float(mr_side*pair*10000),'always_cont_gross_bps':float(cont_side*pair*10000),'static_pair_gross_bps':float(regime_side*static*10000),'unhedged_gold_gross_bps':float(regime_side*gold*10000)})
        i=exitp
    tr=pd.DataFrame(rows); cid=f'{feature}__threshold{str(threshold).replace(".","p")}__hold{hold}'
    out={'candidate_id':cid,'feature':feature,'regime_threshold':float(threshold),'hold':int(hold),'state_pass':bool(state_pass),'trades':int(len(tr))}
    if tr.empty:out['economic_pass_before_neighborhood']=False;return out
    costs=[float(x) for x in cfg['economic_translation']['round_trip_cost_bps_on_total_gross_notional']]; primary=float(cfg['economic_translation']['primary_cost_bps'])
    for cost in costs:
        key=f'{cost:g}'; col=f'net_{key}'; tr[col]=tr['gross_bps']-cost; fn=tr.groupby('fold')[col].mean(); fp=tr.groupby('fold')[col].apply(pf)
        out[f'net_{key}_median_fold_bps']=float(fn.median());out[f'pf_{key}_median_fold']=float(fp.median());out[f'positive_fold_fraction_{key}']=float((fn>0).mean());out[f'mean_net_{key}_bps']=float(tr[col].mean())
    pkey=f'{primary:g}'; pcol=f'net_{pkey}'
    for name in ['reversed_regime','always_mr','always_cont','static_pair','unhedged_gold']:tr[f'{name}_net_primary']=tr[f'{name}_gross_bps']-primary
    out['reversed_regime_mean_net_primary_bps']=float(tr['reversed_regime_net_primary'].mean())
    out['strategy_median_fold_risk_adjusted_primary']=fold_ra(tr,pcol);out['always_mr_median_fold_risk_adjusted_primary']=fold_ra(tr,'always_mr_net_primary');out['always_cont_median_fold_risk_adjusted_primary']=fold_ra(tr,'always_cont_net_primary');out['static_pair_median_fold_risk_adjusted_primary']=fold_ra(tr,'static_pair_net_primary');out['unhedged_gold_median_fold_risk_adjusted_primary']=fold_ra(tr,'unhedged_gold_net_primary')
    out['long_gold_short_silver']=side_stats(tr,pcol,1);out['short_gold_long_silver']=side_stats(tr,pcol,-1);out['reversion_decisions']=int((tr['regime_choice']=='reversion').sum());out['continuation_decisions']=int((tr['regime_choice']=='continuation').sum())
    out['trade_return_corr_with_unhedged_gold']=float(np.corrcoef(tr['gross_bps'],tr['unhedged_gold_gross_bps'])[0,1]) if len(tr)>=3 and np.std(tr['gross_bps'])>0 and np.std(tr['unhedged_gold_gross_bps'])>0 else np.nan
    e=cfg['economic_gate'];hkey=f'{float(cfg["economic_translation"]["high_cost_bps"]):g}'
    out['economic_pass_before_neighborhood']=bool(state_pass and len(tr)>=int(e['minimum_non_overlapping_trades']) and out.get(f'net_{pkey}_median_fold_bps',-np.inf)>float(e['minimum_primary_median_fold_net_bps']) and out.get(f'pf_{pkey}_median_fold',0)>=float(e['minimum_primary_median_fold_pf']) and out.get(f'positive_fold_fraction_{pkey}',0)>=float(e['minimum_primary_positive_fold_fraction']) and out.get(f'net_{hkey}_median_fold_bps',-np.inf)>=float(e['minimum_high_cost_median_fold_net_bps']) and out.get(f'mean_net_{pkey}_bps',-np.inf)>float(e['minimum_overall_mean_primary_net_bps']) and out.get(f'mean_net_{pkey}_bps',-np.inf)>out.get('reversed_regime_mean_net_primary_bps',np.inf) and np.isfinite(out.get('strategy_median_fold_risk_adjusted_primary',np.nan)) and out['strategy_median_fold_risk_adjusted_primary']>out.get('always_mr_median_fold_risk_adjusted_primary',np.inf) and out['strategy_median_fold_risk_adjusted_primary']>out.get('always_cont_median_fold_risk_adjusted_primary',np.inf) and out['strategy_median_fold_risk_adjusted_primary']>out.get('static_pair_median_fold_risk_adjusted_primary',np.inf) and out['long_gold_short_silver']['trades']>=int(e['minimum_long_gold_short_silver_trades']) and out['short_gold_long_silver']['trades']>=int(e['minimum_short_gold_long_silver_trades']) and out['long_gold_short_silver']['mean_net_bps']>0 and out['short_gold_long_silver']['mean_net_bps']>0)
    out['trade_rows']=rows;return out


def neighbor(a:dict,b:dict)->bool:
    return a['feature']==b['feature'] and (int(a['regime_threshold']!=b['regime_threshold'])+int(a['hold']!=b['hold'])==1)


def supports(c:dict,cfg:dict)->bool:
    r=cfg['neighborhood_gate']['supporter_requires'];pk=f'{float(cfg["economic_translation"]["primary_cost_bps"]):g}';hk=f'{float(cfg["economic_translation"]["high_cost_bps"]):g}'
    return c.get(f'net_{pk}_median_fold_bps',-np.inf)>float(r['primary_median_fold_net_bps_gt']) and c.get(f'pf_{pk}_median_fold',0)>float(r['primary_median_fold_pf_gt']) and c.get(f'mean_net_{pk}_bps',-np.inf)>float(r['overall_mean_primary_net_bps_gt']) and c.get(f'net_{hk}_median_fold_bps',-np.inf)>=float(r['high_cost_median_fold_net_bps_gte'])


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--gold',required=True);ap.add_argument('--silver',required=True);ap.add_argument('--output',required=True);args=ap.parse_args()
    cfg=json.loads(Path(args.config).read_text());mt=int(cfg['data_admission']['minimum_tick_volume_each_leg'])
    g=load_cash(Path(args.gold),'gold',mt);s=load_cash(Path(args.silver),'silver',mt);common=g.join(s,how='inner').dropna().sort_index()
    dev=cfg['periods']['development'];start=pd.Timestamp(dev['start'],tz='UTC');end=pd.Timestamp(dev['end_exclusive'],tz='UTC');d=common.loc[(common.index>=start)&(common.index<end)].copy()
    states=adaptive_states(d,cfg);features=build_features(d,states,cfg);sr=state_results(d,states,features,start,cfg);smap={x['feature']:bool(x['state_pass']) for x in sr}
    cells=[]
    for feature in cfg['feature_engineering']['features'].keys():
        for threshold in cfg['economic_translation']['minimum_abs_regime_score']:
            for hold in cfg['economic_translation']['hold_trading_bars']:
                cells.append(simulate(d,states,features,feature,float(threshold),int(hold),start,smap[feature],cfg))
    for c in cells:
        ns=[x['candidate_id'] for x in cells if x is not c and neighbor(c,x) and supports(x,cfg)];c['supporting_neighbors']=sorted(ns);c['neighborhood_support_count']=len(ns);c['full_development_pass']=bool(c.get('economic_pass_before_neighborhood') and len(ns)>=int(cfg['neighborhood_gate']['minimum_supporting_neighbors']))
    passed=[c for c in cells if c.get('full_development_pass')]; pk=f'{float(cfg["economic_translation"]["primary_cost_bps"]):g}';rmap={x['feature']:x for x in sr}
    passed.sort(key=lambda c:(-float(rmap[c['feature']].get('median_fold_spearman',-np.inf)),-float(c.get(f'positive_fold_fraction_{pk}',-np.inf)),-float(c.get(f'net_{pk}_median_fold_bps',-np.inf)),c['candidate_id']))
    selected=passed[:int(cfg['candidate_selection']['maximum_candidates'])]
    payload={'schema_version':1,'protocol':cfg['protocol_name'],'evidence_class':cfg['evidence_class'],'development_period':dev,'data_integrity':{'common_rows_all_source':int(len(common)),'development_rows':int(len(d)),'first':str(d.index.min()),'last':str(d.index.max()),'feature_non_null':{c:int(features[c].notna().sum()) for c in features.columns}},'grid':{'state_hypotheses':int(len(sr)),'state_passes':int(sum(bool(x['state_pass']) for x in sr)),'economic_cells':int(len(cells)),'economic_passes_before_neighborhood':int(sum(bool(x.get('economic_pass_before_neighborhood')) for x in cells)),'full_development_passes':int(len(passed))},'state_results':sr,'cells':cells,'selected_candidates_for_separate_freeze':[x['candidate_id'] for x in selected],'locked_internal_validation_opened':False,'retrospective_extension_opened':False,'leverage_tested':False,'claims':cfg['claims']}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(json.dumps(clean(payload),indent=2));print(json.dumps(clean({'grid':payload['grid'],'selected':payload['selected_candidates_for_separate_freeze'],'validation_opened':False}),indent=2))

if __name__=='__main__':main()

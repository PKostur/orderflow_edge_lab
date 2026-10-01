"""Frozen causal LSK experiment. Event economics only; no order routing."""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median, fmean

from .orderflow_backtest import BacktestConfig, _flow_ratio, _book_imbalance, _micro_edge

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config/lsk_conditional_regime_v1.json'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def code_digest(path):
    """Portable freeze identity across Git's Windows/Linux newline conversion."""
    return hashlib.sha256(Path(path).read_text(encoding='utf-8').replace('\r\n','\n').encode('utf-8')).hexdigest()


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def quantile(xs, q):
    ys = sorted(xs)
    pos = (len(ys)-1)*q
    i = int(pos)
    return ys[i] + (ys[min(i+1,len(ys)-1)]-ys[i])*(pos-i)


def bbo(row):
    bid, ask = row.get('best_bid'), row.get('best_ask')
    return (float(bid), float(ask)) if finite(bid) and finite(ask) and 0 < bid < ask else None


def applied_depth(row):
    return row['event_type']=='depth' and row.get('depth_applied') is True and bbo(row) is not None


def load_rows(path,cfg):
    """Validate the global causal clock while retaining only the two input symbols."""
    out=[]; last=-1; epoch={}; gap_counts={}
    keys={'symbol','event_type','received_at_ns','exchange_ts_ms','depth_applied','best_bid','best_ask','microprice',
          'rolling_buy_volume','rolling_sell_volume','rolling_trade_count'}
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            row=json.loads(line)
            if not isinstance(row,dict): raise ValueError('non-object feature row')
            if row.get('event_type') not in ('trade','depth','snapshot'): continue
            t=row.get('received_at_ns')
            if not isinstance(t,int) or isinstance(t,bool) or t<last: raise ValueError('invalid/regressing received clock')
            last=t
            if row.get('symbol') not in (cfg['symbol'],cfg['context_symbol']): continue
            symbol=row['symbol']; gap=row.get('true_depth_gaps_seen',0)
            if row['event_type']=='snapshot' or gap>gap_counts.get(symbol,0): epoch[symbol]=t
            gap_counts[symbol]=gap
            if row['event_type']=='snapshot': continue
            item={k:v for k,v in row.items() if k in keys or k.startswith('book_imbalance_')}
            item['observed_at_ns']=t; item['epoch_ns']=epoch.get(symbol,0); out.append(item)
    if not out: raise ValueError('no LSK/BTC causal rows')
    return out


def signals(rows, cfg):
    """Preserve discovery-v1 thresholds/cooldowns, fixing same-time BTC lookahead."""
    base = BacktestConfig(symbol=cfg['symbol'], context_symbol=cfg['context_symbol'])
    last, btc, btc_t, depth_t = {}, 0, -10**30, -10**30
    result = []
    for row in rows:
        t = row['observed_at_ns']
        if row['symbol']==cfg['symbol']:
            if row.get('epoch_ns',0)>depth_t: depth_t=-10**30
            if applied_depth(row): depth_t=t
        if row['event_type'] != 'trade': continue
        flow = _flow_ratio(row)
        if row['symbol'] == cfg['context_symbol']:
            btc = 1 if flow is not None and flow >= .10 else -1 if flow is not None and flow <= -.10 else 0
            btc_t = t
            continue
        if row['symbol'] != cfg['symbol'] or bbo(row) is None: continue
        if t-depth_t>cfg['maximum_quote_delay_ms']*1_000_000: continue
        book, micro = _book_imbalance(row), _micro_edge(row)
        if not all(finite(x) for x in (flow,book,micro)): continue
        if (row.get('rolling_trade_count') or 0) < base.min_trade_count: continue
        sides = [1 if v >= cut else -1 if v <= -cut else 0 for v,cut in ((flow,.25),(book,.25),(micro,.20))]
        if not sides[0] or len(set(sides)) != 1: continue
        side = sides[0]
        aligned = btc == side and 0 <= t-btc_t <= cfg['maximum_btc_age_ms']*1_000_000
        for family in ('aligned','aligned_btc') if aligned else ('aligned',):
            key = (family,side)
            if t-last.get(key,-10**30) < base.cooldown_ms*1_000_000: continue
            last[key] = t
            result.append(dict(t=t,epoch_ns=row.get('epoch_ns',0),side=side,family=family,flow=flow,book=book,micro=micro,btc_aligned=aligned,signal_bbo=bbo(row)))
    return result


def states(rows, cfg):
    """Five-second anchors from strict earlier rows; normalization never sees labels."""
    own = [r for r in rows if r['symbol']==cfg['symbol']]
    if not own: return []
    quotes = [r for r in own if applied_depth(r)]
    qt = [r['observed_at_ns'] for r in quotes]
    mids = [sum(bbo(r))/2 for r in quotes]
    trades = [r for r in own if r['event_type']=='trade']
    tt = [r['observed_at_ns'] for r in trades]
    depths = qt
    step = cfg['grid_seconds']*NS
    out=[]
    for t in range(((own[0]['observed_at_ns']//step)+1)*step,own[-1]['observed_at_ns']+1,step):
        right=bisect_left(qt,t); left=bisect_left(qt,t-15*NS)
        tr=bisect_left(tt,t)-1
        if right==0 or tr<0 or right-left<2: continue
        i=right-1
        if t-qt[i]>cfg['maximum_quote_delay_ms']*1_000_000 or t-tt[tr]>5*NS: continue
        j10=bisect_right(qt,t-10*NS)-1
        j15=bisect_right(qt,t-15*NS)-1
        if min(j10,j15)<0: continue
        if quotes[i].get('epoch_ns',0)>t-15*NS: continue
        if len({quotes[j15].get('epoch_ns',0),quotes[i].get('epoch_ns',0),trades[tr].get('epoch_ns',0)})!=1: continue
        if t-10*NS-qt[j10]>NS or t-15*NS-qt[j15]>NS: continue
        # A missing quote feed inside the window is not a valid continuous state.
        if any(b-a>NS for a,b in zip(qt[j15:i],qt[j15+1:i+1])): continue
        bid,ask=bbo(quotes[i]); spread=(ask-bid)/mids[i]*10000
        flow=_flow_ratio(trades[tr]); count=trades[tr].get('rolling_trade_count')
        if not finite(flow) or not finite(count): continue
        side=1 if flow>0 else -1 if flow<0 else 0
        ret10=(mids[i]/mids[j10]-1)*10000
        ret15=(mids[i]/mids[j15]-1)*10000
        window=mids[j15:right]
        rng=(max(window)/min(window)-1)*10000
        activity=(bisect_left(depths,t)-bisect_left(depths,t-15*NS))/15
        out.append(dict(t=t,epoch_ns=quotes[i].get('epoch_ns',0),flow=abs(flow),flow_side=side,trade=count,quote=activity,range=rng,spread=spread,
                        displacement=side*ret15/spread,range_spread=rng/spread,
                        efficiency=side*ret10/spread/max(.25,abs(flow))))
    return out


def classify(current, history, cfg, side):
    if current is None: return 'NO_TRADE','missing_state',{}
    t=current['t']
    hist=[r for r in history if t-cfg['baseline_seconds']*NS <= r['t'] < t and r.get('epoch_ns',0)==current.get('epoch_ns',0)]
    if len(hist)<cfg['minimum_baseline_samples']: return 'NO_TRADE','warmup',{}
    if hist[0]['t']>t-(cfg['baseline_seconds']-cfg['grid_seconds'])*NS: return 'NO_TRADE','warmup',{}
    keys=('flow','trade','quote','range','spread','efficiency','range_spread')
    if any(not all(finite(r.get(k)) for k in keys) for r in hist+[current]): return 'NO_TRADE','nonfinite',{}
    limits={k:[quantile([r[k] for r in hist],q) for q in (cfg['thresholds']['lower_quantile'],.5,cfg['thresholds']['upper_quantile'])] for k in keys}
    prior=[r for r in hist if r['t']<=t-15*NS]
    if not prior or t-15*NS-prior[-1]['t']>cfg['grid_seconds']*NS: return 'NO_TRADE','missing_lag',limits
    prev=prior[-1]
    th=cfg['thresholds']
    # Reject flat normalization rather than inventing epsilon divisions or quantile ranks.
    if any(limits[k][2]<=limits[k][0] for k in ('trade','quote','range','efficiency')):
        return 'NO_TRADE','degenerate_baseline',limits
    if current['flow_side']!=side or current['spread']>th['maximum_spread_bps'] or current['range_spread']<=th['minimum_range_spread']:
        return 'NO_TRADE','pressure_or_liquidity_veto',limits
    original=(current['trade']>=limits['trade'][1] and current['quote']>=limits['quote'][1]
              and current['range']>limits['range'][1] and current['range']>prev['range']
              and current['efficiency']>0 and current['efficiency']>=limits['efficiency'][2]
              and th['moving_displacement_spread']<current['displacement']<=th['mature_displacement_spread']
              and current['spread']<=prev['spread'])
    reversed_=(prev['flow_side']==side and current['flow']>=limits['flow'][2] and current['efficiency']<=limits['efficiency'][0]
               and current['efficiency']<prev['efficiency'] and current['displacement']>th['mature_displacement_spread']
               and current['trade']<=prev['trade'] and current['quote']<=prev['quote']
               and current['range']<=prev['range'] and current['spread']>=prev['spread'])
    return ('ORIGINAL','conversion',limits) if original else ('REVERSED','absorption',limits) if reversed_ else ('NO_TRADE','indeterminate',limits)


def executable(quotes, times, t, horizon_ms, side, cost, max_delay_ms, signal_bbo=None, quote_epochs=None, signal_epoch=None):
    """Cross BBO at delayed entry and delayed horizon exit; spread paid once."""
    entry_target=t+cost['latency_ms']*1_000_000
    exit_target=t+(horizon_ms+cost['latency_ms'])*1_000_000
    a,b=bisect_left(times,entry_target),bisect_left(times,exit_target)
    direct_entry=cost['latency_ms']==0 and signal_bbo is not None
    if b>=len(quotes) or (not direct_entry and a>=len(quotes)): return None
    if quote_epochs is not None and (quote_epochs[b]!=signal_epoch or (not direct_entry and quote_epochs[a]!=signal_epoch)): return None
    if (not direct_entry and times[a]-entry_target>max_delay_ms*1_000_000) or times[b]-exit_target>max_delay_ms*1_000_000: return None
    entry_quote=signal_bbo if cost['latency_ms']==0 and signal_bbo is not None else quotes[a]
    entry=entry_quote[1 if side>0 else 0]; exit_=quotes[b][0 if side>0 else 1]
    gross=side*(exit_/entry-1)*10000
    return gross-cost['fee_bps']-cost['slippage_bps_rt']-cost['adverse_selection_bps_rt']


def evaluate_capture(path,cfg):
    rows=load_rows(path,cfg)
    own=[r for r in rows if r['symbol']==cfg['symbol']]
    if not own: raise ValueError(f'{path}: LSK missing')
    ss=states(rows,cfg); st=[s['t'] for s in ss]
    qr=[r for r in own if applied_depth(r)]
    qt=[r['observed_at_ns'] for r in qr]; qs=[bbo(r) for r in qr]; qe=[r.get('epoch_ns',0) for r in qr]
    output=[]; decisions=[]
    for sig in signals(rows,cfg):
        i=bisect_right(st,sig['t'])-1
        state=ss[i] if i>=0 and sig['t']-st[i]<=cfg['maximum_state_age_ms']*1_000_000 else None
        if state and state.get('epoch_ns',0)!=sig['epoch_ns']: state=None
        decision,reason,limits=classify(state,ss[:i],cfg,sig['side']) if state else ('NO_TRADE','missing_state',{})
        if sig['family']=='aligned_btc': decisions.append(dict(**sig,decision=decision,reason=reason,state=state,limits=limits))
        for cost in cfg['costs']:
            orig=executable(qs,qt,sig['t'],cfg['horizon_ms'],sig['side'],cost,cfg['maximum_quote_delay_ms'],sig['signal_bbo'],qe,sig['epoch_ns'])
            rev=executable(qs,qt,sig['t'],cfg['horizon_ms'],-sig['side'],cost,cfg['maximum_quote_delay_ms'],sig['signal_bbo'],qe,sig['epoch_ns'])
            if orig is None or rev is None:
                strategies=('unconditional_aligned',) if sig['family']=='aligned' else ('always_original','always_reversed','classifier')
                for strategy in strategies:
                    output.append(dict(t=sig['t'],family=sig['family'],cost=cost['name'],strategy=strategy,missing_fill=True,decision=decision,
                                       traded=strategy!='classifier' or decision!='NO_TRADE',tail_censored=sig['t']+(cfg['horizon_ms']+cost['latency_ms'])*1_000_000>rows[-1]['observed_at_ns']))
                continue
            values={'unconditional_aligned':orig} if sig['family']=='aligned' else {'always_original':orig,'always_reversed':rev,'classifier':orig if decision=='ORIGINAL' else rev if decision=='REVERSED' else 0}
            for strategy,net in values.items():
                output.append(dict(t=sig['t'],family=sig['family'],cost=cost['name'],strategy=strategy,net_bps=net,decision=decision,
                                   traded=strategy!='classifier' or decision!='NO_TRADE'))
    return dict(path=str(path),sha256=digest(path),start_ns=rows[0]['observed_at_ns'],end_ns=rows[-1]['observed_at_ns'],
                timestamped_state_count=len(ss),decisions=decisions,observations=output)


def cluster_representatives(captures,gap_seconds):
    groups=[]
    for cap in sorted(captures,key=lambda c:(c['start_ns'],c['sha256'])):
        if not groups or cap['start_ns']>max(c['end_ns'] for c in groups[-1])+gap_seconds*NS: groups.append([])
        groups[-1].append(cap)
    selected=[]
    for i,group in enumerate(groups):
        representative=min(group,key=lambda c:(-c['timestamped_state_count'],c['start_ns'],c['sha256']))
        selected.append((f'cluster_{i+1}',representative))
    return selected


def metrics(values):
    gains=sum(v for v in values if v>0); losses=-sum(v for v in values if v<0)
    return dict(trades=len(values),net_mean_bps=fmean(values) if values else None,net_total_bps=sum(values),
                pf=gains/losses if losses else 'INF' if gains else None)


def summarize(captures,cfg):
    selected=cluster_representatives(captures,cfg['dependence_gap_seconds'])
    report=[]
    for cost in cfg['costs']:
        for strategy in ('classifier','always_original','always_reversed','unconditional_aligned'):
            by={}
            opportunities=0; missing=0; intended=0; tail=0
            for cluster,cap in selected:
                rs=[r for r in cap['observations'] if r.get('strategy')==strategy and r['cost']==cost['name']]
                opportunities+=len(rs)
                intended+=sum(r['traded'] for r in rs)
                missing+=sum(r['traded'] and r.get('missing_fill',False) and not r.get('tail_censored',False) for r in rs)
                tail+=sum(r['traded'] and r.get('tail_censored',False) for r in rs)
                by[cluster]=[r['net_bps'] for r in rs if r['traded'] and not r.get('missing_fill')]
            vals=[v for vs in by.values() for v in vs]; active={k:v for k,v in by.items() if v}
            totals={k:sum(v) for k,v in by.items()}; best=max(totals,key=totals.get) if totals else None
            pos=sum(max(0,v) for v in totals.values())
            report.append(dict(strategy=strategy,cost=cost['name'],**metrics(vals),independent_clusters=len(selected),active_clusters=len(active),
                intended_trades=intended,missing_interior_fills=missing,tail_censored_trades=tail,
                opportunity_mean_bps=sum(vals)/opportunities if opportunities and not missing and not tail else None,eligible_opportunities=opportunities,
                positive_cluster_fraction=sum(sum(v)>0 for v in by.values())/len(by) if by else None,
                equal_active_cluster_mean_bps=fmean(fmean(v) for v in active.values()) if active else None,
                median_active_cluster_mean_bps=median(fmean(v) for v in active.values()) if active else None,
                best_cluster_positive_profit_share=max(totals.values())/pos if pos else None,
                leave_best_cluster_out=metrics([v for k,vs in by.items() if k!=best for v in vs]),
                clusters={k:metrics(v) for k,v in by.items()}))
    paired=[]
    for cost in cfg['costs']:
        for control in ('always_original','always_reversed'):
            by={}
            for k,c in selected:
                candidate={r['t']:r['net_bps'] for r in c['observations'] if r.get('strategy')=='classifier' and r['cost']==cost['name'] and not r.get('missing_fill')}
                baseline={r['t']:r['net_bps'] for r in c['observations'] if r.get('strategy')==control and r['cost']==cost['name'] and not r.get('missing_fill')}
                by[k]=[candidate[t]-baseline[t] for t in candidate.keys() & baseline.keys()]
            paired.append(dict(cost=cost['name'],control=control,matched_opportunity_delta_mean_bps=fmean(v for vs in by.values() for v in vs) if any(by.values()) else None,
                               cluster_delta_mean_bps={k:fmean(v) if v else None for k,v in by.items()}))
    branches={}
    for branch in ('ORIGINAL','REVERSED'):
        by={k:[r['net_bps'] for r in c['observations'] if r.get('strategy')=='classifier' and r['cost']=='severe' and r['decision']==branch and r['traded'] and not r.get('missing_fill')] for k,c in selected}
        branches[branch]=dict(**metrics([v for vs in by.values() for v in vs]),active_clusters=sum(bool(v) for v in by.values()),clusters={k:metrics(v) for k,v in by.items()})
    gate=cfg['forward_gate']; stress=next(r for r in report if r['strategy']=='classifier' and r['cost']=='severe')
    def good_pf(pf): return pf=='INF' or finite(pf) and pf>gate['minimum_pf']
    checks=dict(complete_interior_fills=stress['missing_interior_fills']==0,minimum_clusters=stress['independent_clusters']>=gate['minimum_clusters'],minimum_trades=stress['trades']>=gate['minimum_trades'],
        positive_clusters=(stress['positive_cluster_fraction'] or 0)>=gate['minimum_positive_cluster_fraction'],pf=good_pf(stress['pf']),
        positive_median=(stress['median_active_cluster_mean_bps'] or 0)>0,
        dispersed_profit=stress['best_cluster_positive_profit_share'] is not None and stress['best_cluster_positive_profit_share']<=gate['maximum_best_cluster_positive_profit_share'],
        survives_best_cluster_removal=(stress['leave_best_cluster_out']['net_mean_bps'] or 0)>0,
        both_branches_replicated=all(v['trades']>=gate['minimum_branch_trades'] and v['active_clusters']>=gate['minimum_branch_clusters'] and (v['net_mean_bps'] or 0)>0 and good_pf(v['pf']) for v in branches.values()))
    return dict(summary=report,paired_control_deltas=paired,branches_severe=branches,numeric_screen_checks=checks,numeric_conditions_met=all(checks.values()),numeric_screen_pass=False,
                chronological_cohort_completeness_verified=False,forward_sequence_audit_required=True,
                representatives=[dict(cluster=k,sha256=c['sha256'],start_ns=c['start_ns'],end_ns=c['end_ns']) for k,c in selected],
                decision_counts=dict(Counter(d['decision'] for _,c in selected for d in c['decisions'])),
                abstention_reasons=dict(Counter(d['reason'] for _,c in selected for d in c['decisions'] if d['decision']=='NO_TRADE')),
                missing_fills=sum(r.get('missing_fill',False) for _,c in selected for r in c['observations']),
                promotable=False,ready_for_live=False,verified_out_of_sample_evidence=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('features',nargs='*'); p.add_argument('--config',default=str(CONFIG)); p.add_argument('--freeze',required=True)
    p.add_argument('--create-freeze',action='store_true'); p.add_argument('--mode',choices=['exploratory','forward'],default='exploratory')
    p.add_argument('--output',required=True); p.add_argument('--known-sources-json')
    args=p.parse_args(); cfg=json.loads(Path(args.config).read_text())
    for cost in cfg['costs']:
        if any(not finite(cost[k]) or cost[k]<0 for k in ('fee_bps','latency_ms','slippage_bps_rt','adverse_selection_bps_rt')): raise ValueError('invalid costs')
    freeze_path=Path(args.freeze)
    if args.create_freeze:
        payload=dict(protocol=cfg['protocol'],frozen_at_utc=datetime.now(timezone.utc).isoformat(),frozen_at_ns=__import__('time').time_ns(),
                     config_sha256=code_digest(args.config),implementation_sha256=code_digest(__file__),dependency_sha256=code_digest(Path(__file__).with_name('orderflow_backtest.py')),base_signal_config=asdict(BacktestConfig()),
                     known_source_sha256=sorted(set([digest(f) for f in args.features]+(json.loads(Path(args.known_sources_json).read_text()) if args.known_sources_json else []))),trial_id='LSK-CONDITIONAL-001',trial_count=1,
                     forward_rule='Capture start strictly after freeze; known source hashes forbidden. First ten independent clusters are the fixed assessment; no early success or threshold changes. At least 150 capture minutes before candidate revision.',
                     ready_for_live=False)
        freeze_path.parent.mkdir(parents=True,exist_ok=True)
        with freeze_path.open('x') as f: json.dump(payload,f,indent=2)
    freeze=json.loads(freeze_path.read_text())
    if freeze['config_sha256']!=code_digest(args.config) or freeze['implementation_sha256']!=code_digest(__file__) or freeze['dependency_sha256']!=code_digest(Path(__file__).with_name('orderflow_backtest.py')): raise ValueError('freeze identity mismatch; create a new version, never overwrite freeze')
    caps=[]
    for path in args.features:
        if args.mode=='forward':
            if digest(path) in freeze['known_source_sha256']: raise ValueError('known capture cannot be forward evidence')
            with Path(path).open(encoding='utf-8') as f:
                first=next((json.loads(line)['received_at_ns'] for line in f if line.strip()),None)
            if not isinstance(first,int) or first<=freeze['frozen_at_ns']: raise ValueError('pre-freeze capture cannot be forward evidence')
        cap=evaluate_capture(path,cfg)
        if args.mode=='forward' and (cap['start_ns']<=freeze['frozen_at_ns'] or cap['sha256'] in freeze['known_source_sha256']): raise ValueError('historical/known capture cannot be forward evidence')
        caps.append(cap)
    result=dict(protocol=cfg['protocol'],mode=args.mode,freeze=freeze,**summarize(caps,cfg),captures=caps,
                interpretation='Exploratory event economics; no portfolio or live-fill claim. Forward mode only establishes temporal eligibility; provenance/holdout audits remain required.')
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('captures','summary','freeze')}))


if __name__=='__main__': main()

"""Descriptive supplement to immutable historical event ledgers; no strategy or gate changes."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import math
import numpy as np

from .public_strategy_completion import clock_counts, SESSION_WINDOWS


def average(values):
    return float(np.mean(values)) if len(values) else None


def middle(values):
    return float(np.median(values)) if len(values) else None


def beta_fit(events, btc_field):
    if len(events)<2:
        return dict(n=len(events),beta=None,intercept_bps=None,reason='insufficient observations')
    x=[float(e[btc_field]) for e in events];y=[float(e['net_bps']) for e in events]
    mx,my=average(x),average(y)
    denominator=math.fsum((v-mx)**2 for v in x)
    if denominator==0:
        return dict(n=len(events),beta=None,intercept_bps=None,reason='constant matched BTC returns')
    beta=math.fsum((a-mx)*(z-my) for a,z in zip(x,y))/denominator
    return dict(n=len(events),beta=beta,intercept_bps=my-beta*mx,
                note='Unweighted paired-event descriptive OLS sensitivity; overlapping durations and sleeves are dependent. Not causal alpha, a tradable hedge, or a statistical confidence interval.')


def concentration(events,key):
    groups=defaultdict(list)
    for e in events:groups[str(e[key])].append(e)
    total=math.fsum(abs(float(e['net_cash_profit_or_cutoff_mark'])) for e in events)
    rows=[]
    for label,items in sorted(groups.items()):
        absolute=math.fsum(abs(float(e['net_cash_profit_or_cutoff_mark'])) for e in items)
        rows.append(dict(group=label,n=len(items),signed_cash_pnl=math.fsum(float(e['net_cash_profit_or_cutoff_mark']) for e in items),
                         absolute_event_cash_pnl=absolute,share_absolute_event_cash_pnl=absolute/total if total else None))
    return dict(rows=rows,hhi_absolute_event_cash_pnl=math.fsum(r['share_absolute_event_cash_pnl']**2 for r in rows) if total else None,
                note='Shares allocate absolute individual-event cash PnL, not absolute group net PnL or an equal-risk ranking.')


def reference_cost_curve(events):
    result={}
    for cost in (10,20,30,40,60,80):
        side=cost/20000
        values=[10000*((float(e['endpoint_reference_price'])/float(e['entry_price']))*(1-side)/(1+side)-1) for e in events]
        positive=math.fsum(v for v in values if v>0);negative=-math.fsum(v for v in values if v<0)
        result[str(cost)]=dict(n=len(values),mean_net_bps=average(values),median_net_bps=middle(values),
                              worst_net_bps=min(values) if values else None,best_net_bps=max(values) if values else None,
                              per_unit_profit_factor=positive/negative if negative else None,
                              win_fraction=sum(v>0 for v in values)/len(values) if values else None)
    return dict(cases=result,note='Conditional reference-return burden on the unchanged baseline admissions, prices and durations. The10/30bps rows are descriptive arithmetic, not new funded simulations, changed admission sets, screening gates or a rescue of the rejected candidate.')


def excursion_details(event,data,side_bps=20):
    if event['status'] not in ('COMPLETED','CENSORED_MTM') or not 0<=side_bps<10000:
        raise ValueError('invalid endpoint status or cost')
    first,last=int(event['entry_index']),int(event['endpoint_minute_index'])
    if data.ndim!=2 or data.shape[1]<5 or not 0<=first<=last<len(data):
        raise ValueError('invalid event/data alignment')
    if not np.isfinite(data[first:last+1,:5]).all() or np.min(data[first:last+1,1:5])<=0:
        raise ValueError('finite positive path required')
    entry=float(event['entry_price']);endpoint=float(event['endpoint_reference_price'])
    if not math.isfinite(entry) or not math.isfinite(endpoint) or min(entry,endpoint)<=0:
        raise ValueError('finite positive event prices required')
    if entry != float(data[first,1]):
        raise ValueError('entry must bind minute OPEN')
    censored=event['status']=='CENSORED_MTM'
    at_open=not censored and event['exit_interval'] is not None and event['exit_interval'][0]==event['exit_interval'][1]
    stop=last+1 if censored else last
    full=data[first:stop]
    known_peak=max(entry,float(data[last,1]),endpoint,float(full[:,2].max()) if len(full) else entry)
    possible_peak=known_peak if at_open or censored else max(known_peak,float(data[last,2]))
    expected=[10000*(known_peak/entry-1),10000*(possible_peak/entry-1)]
    if not np.allclose(expected,event['mfe_bps_bounds'],rtol=0,atol=1e-9):
        raise ValueError('event MFE does not bind this path')
    known_low=min(entry,float(data[last,1]),endpoint,float(full[:,3].min()) if len(full) else entry)
    possible_low=known_low if at_open or censored else min(known_low,float(data[last,3]))
    expected_mae=[10000*(possible_low/entry-1),10000*(known_low/entry-1)]
    if not np.allclose(expected_mae,event['mae_bps_bounds'],rtol=0,atol=1e-9):
        raise ValueError('event MAE does not bind this path')
    peak_index=None
    if possible_peak==entry:
        before=[0.,0.];method='first maximum is entry OPEN';peak_index=first
    elif possible_peak==known_peak:
        hits=np.flatnonzero(full[:,2]==possible_peak) if len(full) else np.array([],int)
        if len(hits):
            peak_index=first+int(hits[0])
            prior=data[first:peak_index]
            known_low=min(entry,float(data[peak_index,1]),float(prior[:,3].min()) if len(prior) else entry)
            possible_low=known_low if float(data[peak_index,1])==possible_peak else min(known_low,float(data[peak_index,3]))
            before=[10000*(possible_low/entry-1),10000*(known_low/entry-1)]
            method='first identified maximum minute; its LOW ordering bounded unless maximum is its OPEN'
        elif float(data[last,1])==possible_peak:
            peak_index=last
            low=min(entry,float(full[:,3].min()) if len(full) else entry)
            before=[10000*(low/entry-1)]*2;method='first maximum at endpoint OPEN; exclude later endpoint-minute extremes'
        else:
            before=[float(event['mae_bps_bounds'][0]),0.];method='unresolved intraminute endpoint; conservative full-MAE-to-zero bound'
    else:
        before=[float(event['mae_bps_bounds'][0]),0.];method='unresolved intraminute endpoint; conservative full-MAE-to-zero bound'
    side=side_bps/10000
    net_peak=[10000*((price/entry)*(1-side)/(1+side)-1) for price in (known_peak,possible_peak)]
    return dict(symbol=event.get('symbol'),entry_time=event.get('entry_time'),status=event['status'],
                first_mfe_minute_index=peak_index,pre_first_mfe_mae_bps_bounds=before,pre_first_mfe_method=method,
                mfe_bps_bounds=list(event['mfe_bps_bounds']),mae_through_endpoint_bps_bounds=list(event['mae_bps_bounds']),
                hypothetical_peak_net_after_cost_bps_bounds=net_peak,
                mfe_giveback_to_endpoint_bps_bounds=[v-float(event['gross_bps']) for v in event['mfe_bps_bounds']],
                endpoint_correct_direction=float(event['gross_bps'])>0,
                definite_positive_excursion=float(event['mfe_bps_bounds'][0])>0,
                possible_positive_excursion=float(event['mfe_bps_bounds'][1])>0,
                note='Peak is retrospective. No peak fill, tick ordering, executable capture ratio, new stop or gate is inferred.')


def event_summary(events,calendar_week_count):
    if calendar_week_count<0:
        raise ValueError('invalid calendar denominator')
    weeks=defaultdict(list)
    for e in events:weeks[e['entry_week']].append(e)
    if len(weeks)>calendar_week_count:
        raise ValueError('active weeks exceed calendar denominator')
    weekly=[dict(entry_week=k,n=len(v),mean_net_bps=average([e['net_bps'] for e in v])) for k,v in sorted(weeks.items())]
    positive=sum(w['mean_net_bps']>0 for w in weekly)
    def identity(e):return {k:e[k] for k in ('symbol','entry_time','status','net_bps','gross_bps','net_cash_profit_or_cutoff_mark')}
    return dict(n=len(events),completed=sum(e['status']=='COMPLETED' for e in events),
                trade_extreme_ordering='Per-unit net bps; all-admission summary retains cutoff marks with their status. Completed-only summary must be reported separately.',
                worst_net_trade=identity(min(events,key=lambda e:e['net_bps'])) if events else None,
                best_net_trade=identity(max(events,key=lambda e:e['net_bps'])) if events else None,
                median_mfe_bps_bounds=[middle([e['mfe_bps_bounds'][i] for e in events]) for i in (0,1)],
                median_mae_bps_bounds=[middle([e['mae_bps_bounds'][i] for e in events]) for i in (0,1)],
                correct_direction_endpoint_fraction=sum(e['gross_bps']>0 for e in events)/len(events) if events else None,
                weekly_means_active=weekly,positive_active_week_fraction=positive/len(weeks) if weeks else None,
                positive_calendar_week_fraction_including_zeros=positive/calendar_week_count if calendar_week_count else None,
                calendar_weeks=calendar_week_count,zero_event_calendar_weeks=calendar_week_count-len(weeks),
                concentration={k:concentration(events,k) for k in ('symbol','month','entry_week')},
                matched_btc_beta_sensitivity={k:beta_fit(events,k) for k in ('btc_net_lower_bps','btc_net_upper_bps')},
                reference_price_cost_curve=reference_cost_curve(events))


def source_signal_clock(candles,flags,warmup_bars,signal_minutes=480):
    if len(candles)!=len(flags) or warmup_bars<1:
        raise ValueError('invalid source signal clock')
    stamps=[datetime.fromtimestamp(float(candles[i,0])/1000+signal_minutes*60,tz=timezone.utc)
            for i in range(warmup_bars-1,len(candles)) if flags[i]]
    return dict(completion_clock=clock_counts(stamps),session_windows_utc=dict(SESSION_WINDOWS),
                includes_last_available_signal_with_no_next_open=True,
                note='Eligible raw BUY flags, including ignored/rejected/final-unexecuted flags; completed-candle availability clock. Fixed UTC point labels, no DST, intrabar-time or session-filter claim.')

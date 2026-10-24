"""Fixed four-asset regime diversification, funded quarter-rotation research."""
import argparse
import csv
import hashlib
import json
import math
import subprocess
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .equity_calendar_carry import cost, load_data, quantity

ASSETS = ("SPY", "TLT", "GLD", "SHV")
WEIGHTS = {s:.25 for s in ASSETS}


def load_sources(folder):
    calendar, frames, divs, manifest, planned = load_data(folder)
    expected=list(frames['SPY'])
    for asset in ('TLT','GLD'):
        with (Path(folder)/(asset+'.csv')).open(newline='',encoding='utf-8') as stream:
            rows=list(csv.DictReader(stream))
        if [x['date'] for x in rows] != expected:
            raise ValueError('unaligned asset sessions')
        frame={}
        for x in rows:
            p={k:float(x[k]) for k in ('open','high','low','close','volume')}
            if not all(math.isfinite(v) and v>0 for v in p.values()) or not p['low']<=min(p['open'],p['close'])<=max(p['open'],p['close'])<=p['high']:
                raise ValueError('invalid OHLCV')
            frame[x['date']]=p
        frames[asset]=frame
        events=json.loads((Path(folder)/(asset+'-dividends.json')).read_text())
        if len(set(x['ex_date'] for x in events))!=len(events) or any(x['ex_date'] not in frame or not math.isfinite(x['amount']) or x['amount']<0 for x in events):
            raise ValueError('invalid/duplicate distributions')
        divs[asset]={x['ex_date']:x['amount'] for x in events}
    return calendar,frames,divs,manifest,planned


def quarterly_schedule(planned, actual):
    quarters=defaultdict(list)
    for d in planned:
        quarters[(d[:4],(int(d[5:7])-1)//3)].append(d)
    exits,entries=set(),set()
    for days in quarters.values():
        i=bisect_left(actual,days[-1])
        if i<len(actual):
            exits.add(actual[i])
        if i+1<len(actual):
            entries.add(actual[i+1])
    return exits,entries


def simulate(calendar,frames,divs,planned,weights=None,multiplier=1):
    weights=WEIGHTS if weights is None else weights
    if any(s not in ASSETS or w<=0 for s,w in weights.items()) or abs(sum(weights.values())-1)>1e-12:
        raise ValueError('fixed positive fully funded weights required')
    days=[d for d in calendar if '2009-01-01'<=d<='2026-09-30']
    exits,entries=quarterly_schedule(planned,calendar)
    positions=dict.fromkeys(ASSETS,0)
    cash,budget,peak,previous=10000.,10000.,10000.,10000.
    receivables,ledger,distributions,marks=[],[],[],[]
    worst,low_bound,total_fees,turnover=0.,0.,0.,0.
    year_start,year_end={},{}
    max_volume_fraction=0.
    for day in days:
        current=date.fromisoformat(day)
        for s in ASSETS:
            entitled=positions[s]*divs[s].get(day,0)
            if entitled:
                due=(current+timedelta(days=90)).isoformat()
                receivables.append((due,entitled))
                distributions.append({'ex_date':day,'asset':s,'shares':positions[s],'receivable_usd':entitled,'modeled_cash_date':due})
        cash+=math.fsum(v for due,v in receivables if due<=day)
        receivables=[(due,v) for due,v in receivables if due>day]
        if day==days[0] or day in entries:
            if any(positions.values()):
                raise ArithmeticError('new allocation before previous inventory liquidated')
            prior=calendar[calendar.index(day)-1]
            assigned={s:budget*w for s,w in weights.items()}
            for s,available in assigned.items():
                limit=1.02*frames[s][prior]['close']
                q=quantity(available,limit,multiplier)
                p=frames[s][day]['open']
                filled=q>0 and p<limit
                fee=cost(q,p,multiplier) if filled else 0.
                if filled:
                    if q*p+fee>available+1e-9:
                        raise ArithmeticError('buy exceeds its preassigned cash budget')
                    cash-=q*p+fee;positions[s]+=q;total_fees+=fee;turnover+=q*p
                    max_volume_fraction=max(max_volume_fraction,q/frames[s][day]['volume'])
                ledger.append({'date':day,'asset':s,'side':'buy','shares':q if filled else 0,'submitted_shares':q,'limit':limit,
                               'fixed_cash_budget':available,'price':p if filled else None,'fee_usd':fee,'cash_after':cash,
                               'status':'FILLED_MODEL' if filled else 'UNFILLED_LIMIT_OR_BUDGET'})
        receivable_value=math.fsum(v for _,v in receivables)
        low=cash+receivable_value+math.fsum(positions[s]*frames[s][day]['low']-cost(positions[s],frames[s][day]['low'],multiplier) for s in ASSETS)
        low_bound=min(low_bound,low/peak-1)
        if day in exits:
            for s in ASSETS:
                q,p=positions[s],frames[s][day]['close']
                if q:
                    fee=cost(q,p,multiplier)
                    cash+=q*p-fee;positions[s]=0;total_fees+=fee;turnover+=q*p
                    max_volume_fraction=max(max_volume_fraction,q/frames[s][day]['volume'])
                    ledger.append({'date':day,'asset':s,'side':'sell','shares':q,'price':p,'fee_usd':fee,'cash_after':cash,'status':'FILLED_MODEL'})
            budget=cash
        if cash < -1e-8 or any(x<0 for x in positions.values()):
            raise ArithmeticError('negative wallet inventory/cash')
        inventory=math.fsum(positions[s]*frames[s][day]['close'] for s in ASSETS)
        liquidation_fee=math.fsum(cost(positions[s],frames[s][day]['close'],multiplier) for s in ASSETS)
        nav=cash+receivable_value+inventory-liquidation_fee
        peak=max(peak,nav);worst=min(worst,nav/peak-1)
        y=day[:4];year_start.setdefault(y,previous);year_end[y]=nav;previous=nav
        marks.append({'date':day,'net_liquidation_usd':nav,'cash_usd':cash,'receivables_usd':receivable_value,'shares':dict(positions)})
    years={y:year_end[y]/year_start[y]-1 for y in year_start}
    blocks={label:math.prod(1+r for y,r in years.items() if start<=int(y)<=end)-1 for label,start,end in (('2009-13',2009,2013),('2014-18',2014,2018),('2019-23',2019,2023),('2024-26',2024,2026))}
    duration=((date.fromisoformat(days[-1])-date.fromisoformat(days[0])).days+1)/365.25
    return {'weights':weights,'cost_multiplier':multiplier,'initial_usd':10000.,'first_session':days[0],'last_session':days[-1],
            'final_net_liquidation_usd':nav,'net_profit_usd':nav-10000,'net_return':nav/10000-1,'cagr':(nav/10000)**(1/duration)-1,
            'max_close_drawdown':worst,'low_vs_prior_close_high_water':low_bound,'calendar_returns':years,'fixed_block_returns':blocks,
            'paid_costs_usd':total_fees,'turnover_notional_usd':turnover,'maximum_trade_daily_volume_fraction':max_volume_fraction,
            'terminal_hypothetical_liquidation_cost_usd':liquidation_fee,'terminal_unpaid_receivables_usd':receivable_value,
            'dividends_entitled_usd':math.fsum(x['receivable_usd'] for x in distributions),
            'filled_orders':sum(x['status']=='FILLED_MODEL' for x in ledger),'unfilled_orders':sum(x['status']!='FILLED_MODEL' for x in ledger),
            'ending_inventory':positions,'ledger':ledger,'equity':marks,'distributions':distributions}


def evaluate(folder):
    calendar,frames,divs,manifest,planned=load_sources(folder)
    portfolios={'four_regime':WEIGHTS,'Treasury_only':{'SHV':1.},'equity_only':{'SPY':1.},'sixty_forty':{'SPY':.6,'TLT':.4},'three_risk_assets':{'SPY':1/3,'TLT':1/3,'GLD':1/3}}
    cases=[]
    for multiplier in (1,2):
        for name,weights in portfolios.items():
            cases.append({'name':name,**simulate(calendar,frames,divs,planned,weights,multiplier)})
    own=[c for c in cases if c['name']=='four_regime']
    bills=[c for c in cases if c['name']=='Treasury_only']
    gates={'CAGR_at_least_4pct_both_costs':all(c['cagr']>=.04 for c in own),
           'above_Treasury_CAGR_both_costs':all(c['cagr']>b['cagr'] for c,b in zip(own,bills)),
           'drawdown_at_most_25pct_both_costs':all(c['max_close_drawdown']>=-.25 for c in own),
           'all_fixed_blocks_positive_both_costs':all(all(r>0 for r in c['fixed_block_returns'].values()) for c in own),
           'no_annual_return_below_minus_20pct':all(min(c['calendar_returns'].values())>=-.20 for c in own)}
    return {'candidate':'FOUR_REGIME_ALLOCATION_V1','evidence':'RETROSPECTIVE_DEVELOPMENT_ONLY','gates':gates,
            'decision':'HISTORICAL_SCREEN_SURVIVOR_ONLY' if all(gates.values()) else 'REJECTED_AS_DEFINED',
            'cases':cases,'source_manifest':manifest,'orders':False,'promotable':False,'future_confirmation_started':False,
            'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'wallet_helper_sha256':hashlib.sha256((Path(__file__).parent/'equity_calendar_carry.py').read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError('evidence already exists')
    root=Path(__file__).resolve().parents[2]
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    committed=subprocess.check_output(['git','show','HEAD:src/orderflow_edge_lab/four_regime_allocation.py'],cwd=root)
    if Path(__file__).read_bytes().replace(b'\r\n',b'\n')!=committed.replace(b'\r\n',b'\n'):
        raise ValueError('commit evaluator before market evaluation')
    config=(root/'config/four_regime_allocation_v1.json').read_bytes()
    if config!=subprocess.check_output(['git','show','7192bf3:config/four_regime_allocation_v1.json'],cwd=root):
        raise ValueError('registered allocation changed')
    report=evaluate(args.source)
    report.update(executed_commit=commit,config_sha256=hashlib.sha256(config).hexdigest(),source_manifest_sha256=hashlib.sha256((args.source/'manifest.json').read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report,allow_nan=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','source_manifest')},indent=2))
    for c in report['cases']:
        print(json.dumps({k:v for k,v in c.items() if k not in ('ledger','equity','distributions')},indent=2))


if __name__=='__main__':
    main()

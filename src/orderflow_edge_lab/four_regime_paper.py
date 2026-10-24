"""Finite initial-quarter paper observer: frozen intentions, public data, no orders."""
import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .equity_calendar_carry import cost, quantity
from .four_regime_allocation import ASSETS

REGISTRATION_COMMIT = 'd4cb8bd61eb7e0a2c9c1f4cfe07101b7c3fb527c'
REGISTERED_INTENT = '1d66bb284c0df54a6b1af65d6d0c6f925c1030c8bc08ca8879ebc88da30bfc60'
REGISTERED_CALENDAR = '536bb309183b7d986c86206a17f0109d63d2010d86564239b17591b3c0b005c4'
REGISTERED_HELPER = 'e225d2aeb2af6092fe3915b577442be2c97c5bf5001ab7917a339c9a849eb922'


def verify_registration(intent, calendar_path):
    verify_intent(intent)
    if intent['intent_sha256'] != REGISTERED_INTENT:
        raise ValueError('intent differs from published pre-open registration')
    if hashlib.sha256(calendar_path.read_bytes()).hexdigest() != REGISTERED_CALENDAR:
        raise ValueError('calendar differs from published registration')
    helper = Path(__file__).with_name('equity_calendar_carry.py').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(helper).hexdigest() != REGISTERED_HELPER:
        raise ValueError('wallet helper differs from registered execution rules')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def make_intent(reference,protocol,created_at=None):
    now=created_at or datetime.now(timezone.utc)
    if now>=datetime.fromisoformat(protocol['initial_open_utc']):
        raise ValueError('cannot create an intent after observing its entry open')
    if reference['reference_session']!=protocol['reference_session']:
        raise ValueError('wrong pre-entry reference session')
    if datetime.fromisoformat(reference['captured_at_utc'])>now:
        raise ValueError('reference capture from the future')
    accounts=[]
    for multiplier in (1,2):
        intents=[]
        for s in ASSETS:
            close=reference['closes'][s]
            if not math.isfinite(close) or close<=0:
                raise ValueError('invalid reference price')
            limit=1.02*close
            intents.append({'asset':s,'fixed_cash_budget':2500.,'limit':limit,'shares':quantity(2500,limit,multiplier)})
        accounts.append({'initial_usd':10000.,'cost_multiplier':multiplier,'intents':intents})
    result={'protocol':protocol,'created_at_utc':now.isoformat(),'reference':reference,'accounts':accounts,
            'orders':False,'future_confirmation_started':False,'promotable':False}
    result['intent_sha256']=hashlib.sha256(canonical(result)).hexdigest()
    return result


def verify_intent(intent):
    original=dict(intent);seal=original.pop('intent_sha256')
    if hashlib.sha256(canonical(original)).hexdigest()!=seal:
        raise ValueError('intent seal mismatch')
    p=intent['protocol']
    if datetime.fromisoformat(intent['created_at_utc'])>=datetime.fromisoformat(p['initial_open_utc']):
        raise ValueError('late intent')
    rebuilt=make_intent(intent['reference'],p,datetime.fromisoformat(intent['created_at_utc']))
    if rebuilt!=intent:
        raise ValueError('intent differs from fixed strategy quantities')


def fetch_quotes(asset,start,end,folder):
    if asset not in ASSETS:
        raise ValueError('only registered public ETF symbols allowed')
    params={'period1':int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()),
            'period2':int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp()),
            'interval':'1d','events':'div,splits','includeAdjustedClose':'false'}
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+asset+'?'+urlencode(params)
    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as stream:
        raw=stream.read()
    (folder/(asset+'-raw.json')).write_bytes(raw)
    payload=json.loads(raw)
    if payload['chart'].get('error'):
        raise ValueError('provider error')
    data=payload['chart']['result'][0]
    if data.get('events',{}).get('splits'):
        raise ValueError('unmodeled split in prospective observation')
    source=data['indicators']['quote'][0]
    prices={}
    for i,t in enumerate(data['timestamp']):
        d=datetime.fromtimestamp(t,ZoneInfo('America/New_York')).date().isoformat()
        prices[d]={k:float(source[k][i]) for k in ('open','high','low','close','volume')}
    dividends={datetime.fromtimestamp(x['date'],ZoneInfo('America/New_York')).date().isoformat():x['amount'] for x in data.get('events',{}).get('dividends',{}).values()}
    return prices,dividends,{'asset':asset,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def observe(intent,calendar,frames,dividends,as_of):
    verify_intent(intent)
    sessions=[x['session'] for x in calendar]
    if sessions!=sorted(set(sessions)):
        raise ValueError('calendar must have unique chronological sessions')
    p=intent['protocol']
    beginning=datetime.fromisoformat(p['initial_open_utc'])
    if as_of<beginning:
        return {'status':'WAITING_FOR_REGISTERED_ENTRY','intent_sha256':intent['intent_sha256'],'orders':False,'future_confirmation_started':False,'promotable':False,'accounts':[]}
    eligible=[x for x in calendar if p['initial_entry_session']<=x['session']<=p['terminal_session'] and datetime.fromisoformat(x['close'])<=as_of]
    if not eligible:
        return {'status':'WAITING_FOR_COMPLETE_FIRST_SESSION','intent_sha256':intent['intent_sha256'],'orders':False,'future_confirmation_started':False,'promotable':False,'accounts':[]}
    days=[x['session'] for x in eligible]
    if days[0]!=p['initial_entry_session']:
        raise ValueError('missing registered opening session')
    for s in ASSETS:
        if any(not math.isfinite(v) or v < 0 for v in dividends[s].values()):
            raise ValueError('invalid prospective dividend amount')
        if any(d not in frames[s] for d in days):
            raise ValueError('missing prospective bar; no forward filling')
        for d in days:
            q=frames[s][d]
            if not all(math.isfinite(x) and x>0 for x in q.values()) or not q['low']<=min(q['open'],q['close'])<=max(q['open'],q['close'])<=q['high']:
                raise ValueError('invalid prospective OHLCV')
    accounts=[]
    for account in intent['accounts']:
        multiplier=account['cost_multiplier'];cash=10000.;held=dict.fromkeys(ASSETS,0);fills=[];receivables=[];marks=[];peak=10000.;dd=0.
        for d in days:
            if d==days[0]:
                for order in account['intents']:
                    s,q=order['asset'],order['shares'];price=frames[s][d]['open']
                    filled=q>0 and price<order['limit'];fee=cost(q,price,multiplier) if filled else 0.
                    if filled:
                        debit=q*price+fee
                        if debit>order['fixed_cash_budget']+1e-9:
                            raise ArithmeticError('paper fill exceeds committed budget')
                        cash-=debit;held[s]=q
                    fills.append({'date':d,'asset':s,'shares':q if filled else 0,'price':price if filled else None,'fee_usd':fee,
                                  'status':'ASSUMED_AUCTION_PROXY_FILL' if filled else 'UNFILLED_LIMIT_OR_BUDGET'})
            else:
                for s in ASSETS:
                    amount=held[s]*dividends[s].get(d,0)
                    if amount:
                        receivables.append(((date.fromisoformat(d)+timedelta(days=90)).isoformat(),amount))
            cash+=math.fsum(v for due,v in receivables if due<=d)
            receivables=[(due,v) for due,v in receivables if due>d]
            if d==p['terminal_session']:
                for s,q in held.items():
                    if q:
                        price=frames[s][d]['close'];fee=cost(q,price,multiplier)
                        cash+=q*price-fee
                        fills.append({'date':d,'asset':s,'side':'terminal_sell','shares':q,'price':price,'fee_usd':fee,'status':'ASSUMED_AUCTION_PROXY_FILL'})
                        held[s]=0
            nav=cash+math.fsum(v for _,v in receivables)+math.fsum(held[s]*frames[s][d]['close']-cost(held[s],frames[s][d]['close'],multiplier) for s in ASSETS)
            if cash<0:
                raise ArithmeticError('unfunded paper cash')
            peak=max(peak,nav);dd=min(dd,nav/peak-1)
            marks.append({'date':d,'net_liquidation_usd':nav,'cash_usd':cash,'receivables_usd':math.fsum(v for _,v in receivables),'shares':dict(held)})
        accounts.append({'cost_multiplier':multiplier,'net_profit_usd':nav-10000,'net_return':nav/10000-1,'max_close_drawdown':dd,'fills':fills,'equity':marks})
    return {'status':'PILOT_COMPLETE_NOT_EDGE_CONFIRMATION' if days[-1]==p['terminal_session'] else 'COLLECTING_FORWARD_PAPER_OBSERVATIONS',
            'as_of_utc':as_of.isoformat(),'intent_sha256':intent['intent_sha256'],'accounts':accounts,
            'orders':False,'verified_broker_fills':False,'future_confirmation_started':False,'promotable':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intent',type=Path,required=True)
    parser.add_argument('--calendar',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    intent=json.loads(args.intent.read_text());verify_registration(intent,args.calendar)
    with args.calendar.open(newline='',encoding='utf-8') as stream:
        calendar=list(csv.DictReader(stream))
    now=datetime.now(timezone.utc)
    end=min(now.date()+timedelta(days=1),date.fromisoformat(intent['protocol']['terminal_session'])+timedelta(days=1)).isoformat()
    frames,divs,receipts={},{},[]
    for asset in ASSETS:
        frames[asset],divs[asset],receipt=fetch_quotes(asset,intent['protocol']['reference_session'],end,args.output)
        receipts.append(receipt)
    report=observe(intent,calendar,frames,divs,now)
    report.update(raw_receipts=receipts,evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),registration_commit=REGISTRATION_COMMIT)
    (args.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('accounts','raw_receipts')},indent=2))


if __name__=='__main__':
    main()

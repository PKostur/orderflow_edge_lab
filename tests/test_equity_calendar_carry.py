import copy
import math
import random
import unittest
from datetime import date, timedelta

from orderflow_edge_lab.equity_calendar_carry import cost, make_schedule, quantity, simulate


class EquityCalendarTests(unittest.TestCase):
    @staticmethod
    def fixture():
        first, last = date(2008,12,1), date(2009,6,30)
        days = [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)
                if (first+timedelta(days=i)).weekday()<5 and (first+timedelta(days=i)).isoformat()!='2009-01-01']
        frames = {s:{d:dict(open=100.,high=101.,low=99.,close=100.,volume=1000000.) for d in days} for s in ('SPY','SHV')}
        return days, frames, {'SPY':{},'SHV':{}}

    def test_clock_known_before_order_and_four_sessions(self):
        days,_,_=self.fixture()
        buys,sells,_=make_schedule(days)
        self.assertEqual(buys['2009-01-30'],'SPY')
        self.assertEqual(sells['2009-01-29'],'SHV')
        self.assertEqual(sells['2009-02-04'],'SPY')
        self.assertEqual(buys['2009-02-05'],'SHV')
        self.assertEqual(make_schedule(days,'random',4),make_schedule(days,'random',4))

    def test_cash_inclusive_fixed_integer_quantity(self):
        rng=random.Random(7)
        for _ in range(1000):
            cash,limit,m=rng.uniform(0,100000),rng.uniform(1,1000),rng.choice((1,2))
            q=quantity(cash,limit,m)
            self.assertEqual(q,int(q))
            self.assertLessEqual(q*limit+cost(q,limit,m),cash+1e-9)
            self.assertGreater((q+1)*limit+cost(q+1,limit,m),cash-1e-9)

    def test_unfilled_gap_stays_cash_entire_window(self):
        days,frames,div=self.fixture()
        frames['SPY']['2009-01-30'].update(open=103.,high=104.,low=100.,close=103.)
        r=simulate(days,frames,div)
        order=next(x for x in r['ledger'] if x['date']=='2009-01-30')
        self.assertEqual(order['status'],'UNFILLED_LIMIT_OR_CASH')
        self.assertTrue(all(x['shares']['SPY']==0 for x in r['equity'] if '2009-01-30'<=x['date']<='2009-02-04'))

    def test_flat_prices_lose_only_costs(self):
        days,frames,div=self.fixture()
        r=simulate(days,frames,div)
        self.assertAlmostEqual(r['final_net_liquidation_usd'],10000-r['paid_costs_usd']-r['terminal_hypothetical_liquidation_cost_usd'])
        self.assertLess(r['net_return'],0)
        self.assertTrue(all(x['cash_usd']>=0 for x in r['equity']))

    def test_exdate_entitlement_before_open_and_delayed_cash(self):
        days,frames,div=self.fixture()
        div['SHV']['2009-01-12']=1.
        r=simulate(days,frames,div,'SHV')
        event=r['distributions'][0]
        self.assertEqual(event['modeled_cash_date'],'2009-04-12')
        self.assertGreater(event['receivable_usd'],0)
        marks={x['date']:x for x in r['equity']}
        self.assertEqual(marks['2009-04-10']['receivables_usd'],event['receivable_usd'])
        self.assertEqual(marks['2009-04-13']['receivables_usd'],0)

    def test_independent_fill_and_receivable_accounting(self):
        days,frames,div=self.fixture()
        div['SPY']['2009-02-02']=.5
        div['SHV']['2009-02-10']=.2
        r=simulate(days,frames,div)
        cash=10000.
        qty={'SPY':0,'SHV':0}
        for x in r['ledger']:
            if x['status']=='FILLED_MODEL':
                signed=x['shares']*(1 if x['side']=='buy' else -1)
                cash-=signed*x['price']+x['fee_usd'];qty[x['asset']]+=signed
        cash+=sum(x['receivable_usd'] for x in r['distributions'] if x['modeled_cash_date']<=r['last_session'])
        unpaid=sum(x['receivable_usd'] for x in r['distributions'] if x['modeled_cash_date']>r['last_session'])
        value=cash+unpaid+sum(qty[s]*frames[s][r['last_session']]['close']-cost(qty[s],frames[s][r['last_session']]['close']) for s in qty)
        self.assertAlmostEqual(value,r['final_net_liquidation_usd'],places=8)

    def test_future_prices_do_not_change_prior_fills(self):
        days,frames,div=self.fixture()
        before=simulate(days,frames,div)
        future=copy.deepcopy(frames)
        for s in future:
            for day in future[s]:
                if day>'2009-03-01':
                    for key in ('open','high','low','close'):
                        future[s][day][key]*=2
        after=simulate(days,future,div)
        self.assertEqual([x for x in before['equity'] if x['date']<'2009-03-01'],[x for x in after['equity'] if x['date']<'2009-03-01'])
        self.assertTrue(math.isfinite(after['net_return']))


if __name__=='__main__':
    unittest.main()

import copy
import unittest
from datetime import date,timedelta

from orderflow_edge_lab.equity_calendar_carry import cost
from orderflow_edge_lab.four_regime_allocation import ASSETS,quarterly_schedule,simulate


class FourRegimeTests(unittest.TestCase):
    @staticmethod
    def fixture():
        start,end=date(2008,12,1),date(2009,10,10)
        days=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1) if (start+timedelta(days=i)).weekday()<5 and (start+timedelta(days=i)).isoformat()!='2009-01-01']
        frames={s:{d:dict(open=100.,high=101.,low=99.,close=100.,volume=1000000.) for d in days} for s in ASSETS}
        return days,frames,{s:{} for s in ASSETS}

    def test_fixed_quarter_orders_and_delayed_closure(self):
        days,_,_=self.fixture()
        exits,entries=quarterly_schedule(days,days)
        self.assertIn('2009-03-31',exits)
        self.assertIn('2009-04-01',entries)
        actual=[d for d in days if d=='2009-03-31' or d!='2009-04-01']
        _,entry=quarterly_schedule(days,actual)
        self.assertIn('2009-04-02',entry)
        self.assertNotIn('2009-04-01',entry)

    def test_full_wallet_conservation_without_returns(self):
        days,prices,div=self.fixture()
        r=simulate(days,prices,div,days)
        self.assertAlmostEqual(r['final_net_liquidation_usd'],10000-r['paid_costs_usd']-r['terminal_hypothetical_liquidation_cost_usd'])
        self.assertTrue(all(x['cash_usd']>=0 for x in r['equity']))
        self.assertEqual(set(x['fixed_cash_budget'] for x in r['ledger'] if x['side']=='buy' and x['date']==r['first_session']),{2500.})

    def test_gap_sleeve_cash_not_redistributed(self):
        days,prices,div=self.fixture()
        first='2009-01-02'
        prices['GLD'][first].update(open=103.,high=104.,close=103.)
        r=simulate(days,prices,div,days)
        first_mark=r['equity'][0]
        self.assertEqual(first_mark['shares']['GLD'],0)
        self.assertGreater(first_mark['cash_usd'],2500)
        self.assertTrue(all(first_mark['shares'][s]==24 for s in ('SPY','TLT','SHV')))

    def test_dividends_and_ledger_independent_reconciliation(self):
        days,prices,div=self.fixture()
        div['TLT']['2009-02-02']=1.
        div['SHV']['2009-03-02']=.2
        r=simulate(days,prices,div,days)
        cash,qty=10000.,dict.fromkeys(ASSETS,0)
        for event in r['ledger']:
            if event['status']=='FILLED_MODEL':
                signed=event['shares']*(1 if event['side']=='buy' else -1)
                cash-=signed*event['price']+event['fee_usd'];qty[event['asset']]+=signed
        paid=sum(x['receivable_usd'] for x in r['distributions'] if x['modeled_cash_date']<=r['last_session'])
        unpaid=sum(x['receivable_usd'] for x in r['distributions'] if x['modeled_cash_date']>r['last_session'])
        value=cash+paid+unpaid+sum(qty[s]*prices[s][r['last_session']]['close']-cost(qty[s],prices[s][r['last_session']]['close']) for s in ASSETS)
        self.assertAlmostEqual(value,r['final_net_liquidation_usd'],places=8)

    def test_future_price_perturbation_invariant(self):
        days,prices,div=self.fixture()
        r=simulate(days,prices,div,days)
        changed=copy.deepcopy(prices)
        for s in ASSETS:
            for day in days:
                if day>='2009-07-01':
                    for key in ('open','high','low','close'):
                        changed[s][day][key]*=4
        alternative=simulate(days,changed,div,days)
        self.assertEqual([x for x in r['equity'] if x['date']<'2009-07-01'],[x for x in alternative['equity'] if x['date']<'2009-07-01'])

    def test_no_unsupported_allocation_or_leverage(self):
        days,prices,div=self.fixture()
        for weights in ({'SPY':2},{'SPY':.5},{'FAKE':1},{'SPY':1.1,'TLT':-.1}):
            with self.assertRaises(ValueError):
                simulate(days,prices,div,days,weights)


if __name__=='__main__':
    unittest.main()

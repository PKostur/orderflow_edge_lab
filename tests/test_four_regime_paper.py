import copy
import unittest
from datetime import datetime,timezone

from orderflow_edge_lab.four_regime_paper import make_intent,observe,verify_intent


class ForwardPaperTests(unittest.TestCase):
    def fixture(self):
        protocol={'reference_session':'2026-10-23','initial_entry_session':'2026-10-26','initial_open_utc':'2026-10-26T13:30:00+00:00','terminal_session':'2026-12-31','terminal_close_utc':'2026-12-31T21:00:00+00:00'}
        reference={'reference_session':'2026-10-23','closes':{s:100. for s in ('SPY','TLT','GLD','SHV')},'captured_at_utc':'2026-10-24T00:00:00+00:00'}
        intent=make_intent(reference,protocol,datetime(2026,10,24,1,tzinfo=timezone.utc))
        calendar=[{'session':'2026-10-26','close':'2026-10-26T20:00:00+00:00'},{'session':'2026-10-27','close':'2026-10-27T20:00:00+00:00'}]
        prices={s:{x['session']:dict(open=100.,high=101.,low=99.,close=100.,volume=100000.) for x in calendar} for s in reference['closes']}
        return intent,calendar,prices,{s:{} for s in prices}

    def test_preopen_seal_and_late_intent_rejected(self):
        intent,_,_,_=self.fixture();verify_intent(intent)
        changed=copy.deepcopy(intent);changed['accounts'][0]['intents'][0]['shares']+=1
        with self.assertRaises(ValueError):
            verify_intent(changed)
        with self.assertRaises(ValueError):
            make_intent(intent['reference'],intent['protocol'],datetime(2026,10,26,14,tzinfo=timezone.utc))

    def test_waiting_does_not_create_fake_positions(self):
        i,c,p,d=self.fixture()
        r=observe(i,c,p,d,datetime(2026,10,24,tzinfo=timezone.utc))
        self.assertEqual(r['accounts'],[])
        self.assertEqual(r['status'],'WAITING_FOR_REGISTERED_ENTRY')

    def test_funded_future_quote_fill_and_missing_data_failclosed(self):
        i,c,p,d=self.fixture()
        r=observe(i,c,p,d,datetime(2026,10,27,22,tzinfo=timezone.utc))
        for account in r['accounts']:
            self.assertLess(account['net_profit_usd'],0)
            self.assertGreaterEqual(account['equity'][0]['cash_usd'],0)
        del p['SPY']['2026-10-26']
        with self.assertRaises(ValueError):
            observe(i,c,p,d,datetime(2026,10,27,22,tzinfo=timezone.utc))


if __name__=='__main__':
    unittest.main()

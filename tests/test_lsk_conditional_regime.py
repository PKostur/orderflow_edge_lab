import json
import unittest
from orderflow_edge_lab.lsk_conditional_regime import CONFIG, NS, classify, states, signals, executable, cluster_representatives, summarize


class LSKConditionalTests(unittest.TestCase):
    def setUp(self): self.cfg=json.loads(CONFIG.read_text())

    def history(self):
        return [dict(t=i*5*NS,flow=.3+i*.01,flow_side=1,trade=10+i,quote=20+i,range=2+i*.1,spread=1,
                     displacement=2,range_spread=5,efficiency=i*.1) for i in range(60)]

    def test_three_way_fixed_tree(self):
        h=self.history(); c=dict(h[-1],t=300*NS,trade=100,quote=100,range=10,efficiency=10,displacement=2)
        self.assertEqual(classify(c,h,self.cfg,1)[0],'ORIGINAL')
        c.update(flow=1,trade=5,quote=5,range=3,efficiency=-1,displacement=5)
        self.assertEqual(classify(c,h,self.cfg,1)[0],'REVERSED')
        c['displacement']=.5
        self.assertEqual(classify(c,h,self.cfg,1)[0],'NO_TRADE')

    def test_warmup_missing_degenerate_and_liquidity(self):
        h=self.history(); c=dict(h[-1],t=300*NS)
        self.assertEqual(classify(c,h[:5],self.cfg,1)[1],'warmup')
        for r in h: r['efficiency']=1
        self.assertEqual(classify(c,h,self.cfg,1)[1],'degenerate_baseline')
        h=self.history(); c['spread']=6
        self.assertEqual(classify(c,h,self.cfg,1)[0],'NO_TRADE')

    def test_thresholds_ignore_future_and_current(self):
        h=self.history(); c=dict(h[-1],t=300*NS)
        expected=classify(c,h,self.cfg,1)
        future=dict(c,t=301*NS,efficiency=999999)
        self.assertEqual(expected,classify(c,h+[future],self.cfg,1))

    def test_spread_paid_once_and_reversal_crosses(self):
        cost=dict(latency_ms=0,fee_bps=8,slippage_bps_rt=2,adverse_selection_bps_rt=2)
        q=[(99,101),(109,111)]; t=[0,30*NS]
        self.assertAlmostEqual(executable(q,t,0,30000,1,cost,1000),(109/101-1)*10000-12)
        self.assertAlmostEqual(executable(q,t,0,30000,-1,cost,1000),-(111/99-1)*10000-12)
        self.assertNotEqual(executable(q,t,0,30000,-1,cost,1000),-executable(q,t,0,30000,1,cost,1000))

    def test_latency_and_missing_fills(self):
        cost=dict(latency_ms=250,fee_bps=8,slippage_bps_rt=0,adverse_selection_bps_rt=0)
        q=[(99,101),(100,102),(109,111),(110,112)]; t=[0,NS,30*NS,31*NS]
        self.assertAlmostEqual(executable(q,t,0,30000,1,cost,1000),(110/102-1)*10000-8)
        self.assertIsNone(executable(q,t,0,30000,1,cost,100))

    def test_zero_latency_uses_signal_quote_not_earlier_equal_timestamp(self):
        c=dict(latency_ms=0,fee_bps=0,slippage_bps_rt=0,adverse_selection_bps_rt=0)
        self.assertAlmostEqual(executable([(90,92),(99,101),(109,111)],[0,0,30*NS],0,30000,1,c,1000,(99,101)),(109/101-1)*10000)

    def test_execution_rejects_epoch_change(self):
        c=dict(latency_ms=250,fee_bps=8,slippage_bps_rt=2,adverse_selection_bps_rt=2)
        self.assertIsNone(executable([(99,101),(109,111)],[NS,31*NS],0,30000,1,c,1000,None,[0,10*NS],0))

    def test_recovery_restarts_baseline(self):
        h=self.history(); c=dict(h[-1],t=300*NS,epoch_ns=290*NS)
        self.assertEqual(classify(c,h,self.cfg,1)[1],'warmup')

    def test_incomplete_selected_fill_blocks_screen(self):
        c=dict(start_ns=0,end_ns=100*NS,sha256='a',timestamped_state_count=100,decisions=[],observations=[dict(t=0,strategy='classifier',cost='severe',traded=True,decision='ORIGINAL',missing_fill=True,tail_censored=False)])
        r=summarize([c],self.cfg)
        self.assertFalse(r['numeric_screen_checks']['complete_interior_fills'])
        s=next(x for x in r['summary'] if x['strategy']=='classifier' and x['cost']=='severe')
        self.assertEqual(s['intended_trades'],1); self.assertEqual(s['trades'],0)

    def test_transitive_clusters_and_duplicate_sources(self):
        caps=[dict(start_ns=a*NS,end_ns=b*NS,sha256=name,timestamped_state_count=n) for a,b,name,n in [(0,10,'a',10),(300,310,'b',20),(600,610,'c',15),(1000,1010,'d',1)]]
        reps=cluster_representatives(caps+[caps[0]],300)
        self.assertEqual(len(reps),2); self.assertEqual(reps[0][1]['sha256'],'b')

    def test_same_timestamp_later_btc_not_visible(self):
        trade=dict(symbol='LSK_USDT',event_type='trade',observed_at_ns=NS,rolling_buy_volume=10,rolling_sell_volume=0,rolling_trade_count=10,best_bid=99,best_ask=101,microprice=100.5,book_imbalance_10=.5)
        btc=dict(trade,symbol='BTC_USDT')
        depth=dict(trade,event_type='depth',depth_applied=True)
        self.assertEqual([s['family'] for s in signals([depth,trade,btc],self.cfg)],['aligned'])
        self.assertEqual([s['family'] for s in signals([depth,btc,trade],self.cfg)],['aligned','aligned_btc'])
        self.assertEqual(signals([btc,trade],self.cfg),[])

    def test_state_prefix_invariance(self):
        rows=[]
        for i in range(100):
            rows.append(dict(symbol='LSK_USDT',event_type='trade',observed_at_ns=i*NS,best_bid=100+i*.01,best_ask=100.1+i*.01,rolling_buy_volume=6,rolling_sell_volume=4,rolling_trade_count=5))
            rows.append(dict(rows[-1],event_type='depth',depth_applied=True))
        a=states(rows[:70],self.cfg); b=states(rows,self.cfg)
        self.assertEqual(a,[s for s in b if s['t']<=rows[69]['observed_at_ns']])
        self.assertTrue(a) # weak-flow anchors remain in the normalization sample

    def test_empty_results_are_not_profitable(self):
        report=summarize([],self.cfg)
        self.assertFalse(report['numeric_screen_pass']); self.assertFalse(report['promotable'])
        self.assertIsNone(report['summary'][0]['pf'])


if __name__=='__main__': unittest.main()

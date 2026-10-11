import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from orderflow_edge_lab import public_candle_batch7 as study
from orderflow_edge_lab import public_protective_batch5 as shared


ROOT = Path(__file__).resolve().parents[1]


class CandleDefaultTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT/'config/public_candle_batch7_v1.json').read_text())
        self.spec['warmup_bars'] = 1

    def fixture(self, prices=(100,101,102,103)):
        rows = []
        for b,opening in enumerate(prices):
            for k in range(480):
                rows.append((1680307200+(b*480+k)*60,opening,opening+2,opening-2,opening+1,1))
        data = np.array(rows,dtype=float)
        candles = shared.bars8h(data)
        features = dict(long=np.zeros(len(candles),bool),short=np.zeros(len(candles),bool),
                        close=candles[:,2].copy(),opening=candles[:,1].copy())
        return data,candles,features

    def run_case(self,data,candles,features,flags=None,cost=40,gap='conservative_limit'):
        return study.simulate(data,data.copy(),candles,features,study.CANDIDATES[0],self.spec,cost,gap,entry_flags=flags)[0]

    def test_exact_ema_reference_and_prefix(self):
        rng = np.random.default_rng(20261011)
        close = rng.uniform(1,100,100)
        candles = np.column_stack((np.arange(100),close-.1,close,close+.01,close-2,np.ones(100)))
        actual = study.source_features(candles,study.CANDIDATES[0],self.spec)
        alpha,beta = 2/11,1-2/11
        expected = [float(close[0])]
        for x in close[1:]:
            expected.append(alpha*float(x)+beta*expected[-1])
        np.testing.assert_array_equal(actual['ema'],expected)
        for length in (1,2,10,51,99):
            prefix = study.source_features(candles[:length],study.CANDIDATES[0],self.spec)
            np.testing.assert_array_equal(actual['long'][:length],prefix['long'])
            np.testing.assert_array_equal(actual['ema'][:length],prefix['ema'])

    def test_zero_range_remains_undefined(self):
        candles = np.array([[0,1,1,1,1,0],[1,1,2,2.01,.5,1]],float)
        f = study.source_features(candles,study.CANDIDATES[0],self.spec)
        self.assertTrue(np.isnan(f['shadow_percentage'][0]))
        self.assertFalse(f['long'][0] or f['short'][0])

    def test_exact_profit_strict_threshold(self):
        price = 67975.34048642045
        close = price*1.002
        self.assertTrue(study.profit_exit(close,price,price))
        self.assertFalse(study.profit_exit(price+price*.002,price,price))
        self.assertFalse(study.profit_exit(close,close,price))

    def test_first_fill_bar_exit_next_open_and_no_same_boundary_reentry(self):
        data,candles,f = self.fixture()
        f['long'][:3] = True
        state = self.run_case(data,candles,f)
        self.assertEqual(state['events'][0]['entry_index'],480)
        self.assertEqual(state['events'][0]['endpoint_minute_index'],960)
        self.assertEqual(state['events'][0]['reason'],'source_bullish_profit_close')
        self.assertEqual(state['events'][1]['entry_index'],1440)
        self.assertEqual(state['counts']['held_entry_ignored'],1)

    def test_flat_prior_profit_close_does_not_cancel_entry(self):
        data,candles,f = self.fixture((100,100))
        f['long'][0] = True
        state = self.run_case(data,candles,f)
        self.assertEqual(state['counts']['accepted_entries'],1)
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')

    def test_original_short_exit_works_under_control_flags(self):
        data,candles,f = self.fixture()
        f['close'][:] = f['opening']
        flags = np.array([True,False,False,False])
        f['short'][1] = True
        state = self.run_case(data,candles,f,flags)
        self.assertEqual(state['events'][0]['reason'],'source_short_to_cash')
        self.assertEqual(state['events'][0]['endpoint_minute_index'],960)

    def test_control_owns_dynamic_reference_and_duration(self):
        data,candles,f = self.fixture((100,100,200,190))
        f['close'][:] = [101,101,201,191]
        f['long'][0] = True
        baseline = self.run_case(data,candles,f)
        control = self.run_case(data,candles,f,np.array([False,True,False,False]))
        self.assertEqual(baseline['events'][0]['entry_price'],100)
        self.assertEqual(control['events'][0]['entry_price'],200)
        self.assertEqual(control['events'][0]['endpoint_minute_index'],1440)

    def test_quantity_budget_actual_cash_profit_and_nav_reconcile(self):
        data,candles,f = self.fixture()
        f['long'][0] = True
        state = self.run_case(data,candles,f)
        qty = np.floor((1000*.1/(candles[0,2]*1.002))*1e8)/1e8
        self.assertEqual(state['events'][0]['quantity'],qty)
        total = sum(e['net_cash_profit_or_cutoff_mark'] for e in state['events'])
        self.assertAlmostEqual(state['nav'][-1],1000+total,places=10)
        self.assertAlmostEqual(state['btc_nav_lower'][-1],state['nav'][-1],places=10)
        self.assertTrue(all(x>=0 for x in state['nav']))

    def test_extreme_gap_rejects_without_resize(self):
        data,candles,f = self.fixture((100,2000,2001))
        f['long'][0] = True
        state = self.run_case(data,candles,f)
        self.assertEqual(state['counts']['cash_rejected'],1)
        self.assertEqual(state['events'],[])
        self.assertEqual(state['cash'],1000)

    def test_cutoff_exit_is_pending_and_not_completed(self):
        data,candles,f = self.fixture((100,101))
        f['long'][0] = True
        state = self.run_case(data,candles,f)
        self.assertTrue(state['pending_source_exit'])
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertIsNone(state['events'][0]['exit_interval'])
        self.assertEqual(state['position']['source_reference_known_at'],shared.stamp(int(data[480,0])+28800))
        self.assertIsNone(state['events'][0]['initial_stop'])

    def test_final_flat_entry_unexecuted_and_accounted(self):
        data,candles,f = self.fixture()
        f['long'][-1] = True
        state = self.run_case(data,candles,f)
        self.assertEqual(state['counts']['raw_entry_flags'],1)
        self.assertEqual(state['counts']['unexecuted_final_entry'],1)
        self.assertEqual(state['events'],[])

    def test_gap_models_identical_without_price_orders(self):
        data,candles,f = self.fixture()
        f['long'][0] = True
        self.assertEqual(self.run_case(data,candles,f),self.run_case(data,candles,f,gap='opening_price_improvement'))

    def test_config_dependencies_bind_and_changes_fail(self):
        config = ROOT/'config/public_candle_batch7_v1.json'
        committed = config.read_bytes()
        with patch.object(study.subprocess,'check_output',return_value=committed):
            self.assertEqual(study.checked_spec(ROOT,config)['new_registered_trading_cells'],1)
        changed = json.loads(committed)
        changed['full_candle']['stop_loss_enabled'] = True
        with patch.object(Path,'read_text',return_value=json.dumps(changed)):
            with self.assertRaisesRegex(ValueError,'changed frozen design'):
                study.checked_spec(ROOT,config)


if __name__ == '__main__':
    unittest.main()

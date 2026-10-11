import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from orderflow_edge_lab import public_protective_batch5 as shared
from orderflow_edge_lab import public_trend_batch8 as study


ROOT=Path(__file__).resolve().parents[1]


class TrendDefaultTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((ROOT/'config/public_trend_batch8_v1.json').read_text())

    def candles(self,prices):
        close=np.array(prices,dtype=float)
        return np.column_stack((1680307200000+np.arange(len(close))*28800000,close-.5,close,close+1,close-1,np.ones(len(close))))

    def features(self,prices):
        return study.source_features(self.candles(prices),study.CANDIDATES[0],self.spec)

    def fixture(self,prices=(100,101,102,103)):
        rows=[]
        for b,opening in enumerate(prices):
            for k in range(480):
                rows.append((1680307200+(b*480+k)*60,opening,opening+2,opening-2,opening+1,1))
        data=np.array(rows,float)
        frame=shared.bars8h(data)
        f=dict(long=np.zeros(len(frame),bool),short=np.zeros(len(frame),bool),close=frame[:,2],opening=frame[:,1])
        return data,frame,f

    def simulate(self,data,frame,f,flags=None,gap='conservative_limit'):
        spec=dict(self.spec,warmup_bars=1)
        return study.simulate(data,data.copy(),frame,f,study.CANDIDATES[0],spec,40,gap,entry_flags=flags)[0]

    def test_atr_wilder_seed_gap_and_product_order(self):
        f=self.features([100]*10+[90,110])
        self.assertTrue(np.isnan(f['atr'][:9]).all())
        self.assertEqual(f['atr'][9],2)
        self.assertEqual(f['atr'][10],.1*11+(1-.1)*2)
        self.assertEqual(f['atr'][11],.1*21+(1-.1)*f['atr'][10])

    def test_no_initial_entry_and_strict_flip_only(self):
        f=self.features([100]*10+[90,110])
        self.assertFalse(f['long'][:11].any())
        self.assertTrue(f['short'][10])
        self.assertTrue(f['long'][11])
        np.testing.assert_array_equal(f['direction'],[1]*10+[-1,1])

    def test_previous_band_comparison_priority_when_bands_overlap(self):
        f=self.features([100]*10+[75,90])
        self.assertGreater(f['lower'][10],f['upper'][10])
        self.assertGreater(90,f['upper'][10])
        self.assertLess(90,f['lower'][10])
        self.assertEqual(f['direction'][11],1)

    def test_equality_to_band_does_not_flip(self):
        for close in (94,106):
            f=self.features([100]*10+[close])
            self.assertEqual(f['direction'][-1],1)
            self.assertFalse(f['long'][-1] or f['short'][-1])

    def test_causal_all_feature_prefix_and_future_mutation(self):
        rng=np.random.default_rng(14)
        prices=100+np.cumsum(rng.normal(size=100))
        frame=self.candles(prices)
        original=study.source_features(frame,study.CANDIDATES[0],self.spec)
        for n in (1,9,10,11,51,99):
            prefix=study.source_features(frame[:n],study.CANDIDATES[0],self.spec)
            for k in original:
                np.testing.assert_array_equal(original[k][:n],prefix[k])
        frame[51:,1:5]*=2
        mutated=study.source_features(frame,study.CANDIDATES[0],self.spec)
        for k in original:
            np.testing.assert_array_equal(original[k][:51],mutated[k][:51])

    def test_source_calendar_gates_entries_and_exits_without_forced_close(self):
        frame=self.candles([100]*10+[90,110])
        frame[:,0]-=5*365*86400000
        f=study.source_features(frame,study.CANDIDATES[0],self.spec)
        self.assertFalse(f['source_calendar_window'].any())
        self.assertFalse(f['long'].any() or f['short'].any())

    def test_held_flags_exit_next_open_without_same_boundary_reentry(self):
        data,frame,f=self.fixture()
        f['long'][:3]=True
        f['short'][1]=True
        state=self.simulate(data,frame,f)
        self.assertEqual(state['events'][0]['entry_index'],480)
        self.assertEqual(state['events'][0]['endpoint_minute_index'],960)
        self.assertEqual(state['events'][0]['reason'],'source_short_to_cash')
        self.assertEqual(state['events'][1]['entry_index'],1440)
        self.assertEqual(state['counts']['held_entry_ignored'],1)

    def test_profit_is_not_an_exit_and_default_has_no_barriers(self):
        data,frame,f=self.fixture((100,200,500))
        f['long'][0]=True
        state=self.simulate(data,frame,f)
        self.assertEqual(len(state['events']),1)
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertFalse(state['pending_source_exit'])
        self.assertIsNone(state['events'][0]['initial_stop'])
        self.assertIsNone(state['events'][0]['last_target'])

    def test_control_entries_use_original_bearish_flip(self):
        data,frame,f=self.fixture()
        f['short'][2]=True
        state=self.simulate(data,frame,f,np.array([False,True,False,False]))
        self.assertEqual(state['events'][0]['entry_index'],960)
        self.assertEqual(state['events'][0]['endpoint_minute_index'],1440)

    def test_five_percent_quantity_cash_btc_nav_reconcile(self):
        data,frame,f=self.fixture()
        f['long'][0]=True
        f['short'][1]=True
        state=self.simulate(data,frame,f)
        expected=np.floor((10000*.05/(frame[0,2]*1.002))*1e8)/1e8
        self.assertEqual(state['events'][0]['quantity'],expected)
        total=sum(e['net_cash_profit_or_cutoff_mark'] for e in state['events'])
        self.assertAlmostEqual(state['nav'][-1],10000+total,places=9)
        self.assertAlmostEqual(state['nav'][-1],state['btc_nav_lower'][-1],places=9)

    def test_extreme_gap_cash_rejection_without_resize(self):
        data,frame,f=self.fixture((100,3000))
        f['long'][0]=True
        state=self.simulate(data,frame,f)
        self.assertEqual(state['counts']['cash_rejected'],1)
        self.assertEqual(state['cash'],10000)
        self.assertEqual(state['events'],[])

    def test_final_queued_exit_censored_and_flat_entry_unexecuted(self):
        data,frame,f=self.fixture((100,101))
        f['long'][0]=True
        f['short'][-1]=True
        state=self.simulate(data,frame,f)
        self.assertTrue(state['pending_source_exit'])
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertIsNone(state['events'][0]['exit_interval'])
        f['long'][:]=[False,True]
        flat=self.simulate(data,frame,f)
        self.assertEqual(flat['counts']['unexecuted_final_entry'],1)

    def test_gap_profiles_identical_without_prices(self):
        data,frame,f=self.fixture()
        f['long'][0]=True
        self.assertEqual(self.simulate(data,frame,f),self.simulate(data,frame,f,gap='opening_price_improvement'))

    def test_real_config_bindings_and_mutation_fail(self):
        config=ROOT/'config/public_trend_batch8_v1.json'
        with patch.object(study.subprocess,'check_output',return_value=config.read_bytes()):
            self.assertEqual(study.checked_spec(ROOT,config)['new_registered_trading_cells'],1)
        changed=dict(self.spec)
        changed['supertrend']=dict(changed['supertrend'],use_stop_loss=True)
        with patch.object(Path,'read_text',return_value=json.dumps(changed)):
            with self.assertRaisesRegex(ValueError,'changed frozen design'):
                study.checked_spec(ROOT,config)

    def test_missing_independent_review_blocks_before_market_load(self):
        with TemporaryDirectory() as scratch:
            with self.assertRaisesRegex(ValueError,'INDEPENDENT_PRE_OUTCOME_REVIEW_REQUIRED'):
                study.require_pre_outcome_review(Path(scratch),self.spec,Path(study.__file__))


if __name__=='__main__':
    unittest.main()

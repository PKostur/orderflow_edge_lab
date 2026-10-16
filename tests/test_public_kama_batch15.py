import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from orderflow_edge_lab import public_protective_batch5 as shared
from orderflow_edge_lab import public_kama_batch15 as study


ROOT=Path(__file__).resolve().parents[1]


class KAMAStateTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((ROOT/'config/public_kama_batch15_v1.json').read_text())

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
        f=dict(long=np.zeros(len(frame),bool),exit_long=np.zeros(len(frame),bool),close=frame[:,2],opening=frame[:,1])
        return data,frame,f

    def simulate(self,data,frame,f,flags=None,gap='conservative_limit'):
        spec=dict(self.spec,warmup_bars=1)
        return study.simulate(data,data.copy(),frame,f,study.CANDIDATES[0],spec,40,gap,entry_flags=flags)[0]

    def test_causal_all_feature_prefix_and_future_mutation(self):
        rng=np.random.default_rng(14)
        prices=100+np.cumsum(rng.normal(size=100))
        frame=self.candles(prices)
        original=study.source_features(frame,study.CANDIDATES[0],self.spec)
        for n in (1,2,13,14,15,51,99):
            prefix=study.source_features(frame[:n],study.CANDIDATES[0],self.spec)
            for k in original:
                np.testing.assert_array_equal(original[k][:n],prefix[k])
        frame[51:,1:5]*=2
        mutated=study.source_features(frame,study.CANDIDATES[0],self.spec)
        for k in original:
            np.testing.assert_array_equal(original[k][:51],mutated[k][:51])

    def test_held_flags_exit_next_open_without_same_boundary_reentry(self):
        data,frame,f=self.fixture()
        f['long'][:3]=True
        f['exit_long'][1]=True
        state=self.simulate(data,frame,f)
        self.assertEqual(state['events'][0]['entry_index'],480)
        self.assertEqual(state['events'][0]['endpoint_minute_index'],960)
        self.assertEqual(state['events'][0]['reason'],'source_kama_sell_to_cash')
        self.assertEqual(state['events'][1]['entry_index'],1440)
        self.assertEqual(state['counts']['held_entry_ignored'],1)

    def test_profit_is_not_an_exit_and_default_has_no_barriers(self):
        data,frame,f=self.fixture((100,100,500))
        f['long'][0]=True
        state=self.simulate(data,frame,f)
        self.assertEqual(len(state['events']),1)
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertFalse(state['pending_source_exit'])
        self.assertIsNone(state['events'][0]['initial_stop'])
        self.assertIsNone(state['events'][0]['last_target'])

    def test_control_entries_use_original_sell_state(self):
        data,frame,f=self.fixture()
        f['exit_long'][2]=True
        state=self.simulate(data,frame,f,np.array([False,True,False,False]))
        self.assertEqual(state['events'][0]['entry_index'],960)
        self.assertEqual(state['events'][0]['endpoint_minute_index'],1440)

    def test_full_cash_quantity_cash_btc_nav_reconcile(self):
        data,frame,f=self.fixture()
        f['long'][0]=True
        f['exit_long'][1]=True
        state=self.simulate(data,frame,f)
        from decimal import Decimal, ROUND_DOWN
        expected=float(Decimal(str(10000/(frame[0,2]*1.002))).quantize(Decimal('0.00000001'),rounding=ROUND_DOWN))
        self.assertEqual(state['events'][0]['quantity'],expected)
        self.assertEqual(state['events'][0]['source_signal_close'],frame[0,2])
        self.assertEqual(state['events'][0]['source_reference_known_at'],shared.stamp(int(data[480,0])))
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
        f['exit_long'][-1]=True
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
        config=ROOT/'config/public_kama_batch15_v1.json'
        with patch.object(study.subprocess,'check_output',return_value=config.read_bytes()):
            self.assertEqual(study.checked_spec(ROOT,config)['new_registered_trading_cells'],1)
        changed=dict(self.spec)
        changed['kama']=dict(changed['kama'],er_period=11)
        with patch.object(Path,'read_text',return_value=json.dumps(changed)):
            with self.assertRaisesRegex(ValueError,'changed frozen design'):
                study.checked_spec(ROOT,config)

    def test_missing_independent_review_blocks_before_market_load(self):
        with TemporaryDirectory() as scratch:
            with self.assertRaisesRegex(ValueError,'INDEPENDENT_PRE_OUTCOME_REVIEW_REQUIRED'):
                study.require_pre_outcome_review(Path(scratch),self.spec,Path(study.__file__))

    def test_native_math_all_fixtures_and_available_actions(self):
        folder=ROOT/'artifacts/public_kama_batch15_registration_20261016'
        fixtures=json.loads((folder/'kama-synthetic-input.json').read_text())
        native=json.loads((folder/'kama-native-synthetic-output.json').read_text())
        values=actions=0
        for fixture,expected in zip(fixtures,native['results']):
            got=self.features(fixture['prices'])
            actual=['NaN' if np.isnan(x) else float(x) for x in got['kama'][10:]]
            self.assertEqual(actual,expected['kama'])
            flags=np.where(got['long'],1,np.where(got['exit_long'],-1,0)).tolist()
            self.assertEqual(flags,expected['actions'][:len(fixture['prices'])])
            self.assertTrue(all(len(x)==len(fixture['prices']) for x in got.values()))
            values+=len(actual);actions+=len(flags)
        self.assertEqual((values,actions),(4714,4902))

    def test_seed_previous_close_and_repeated_states(self):
        prices=np.arange(100.,130.)
        f=self.features(prices)
        self.assertTrue(np.isnan(f['kama'][:10]).all())
        first=prices[9]+(2/3)**2*(prices[10]-prices[9])
        self.assertEqual(f['kama'][10],first)
        self.assertNotEqual(f['kama'][10],np.mean(prices[:10]))
        self.assertTrue(f['long'][10:].all())
        self.assertFalse(f['exit_long'].any())
        down=self.features(prices[::-1])
        self.assertTrue(down['exit_long'][10:].all())

    def test_zero_denominator_nan_persists_after_variation_recovers(self):
        f=self.features([100.]*12+list(np.arange(101.,130.)))
        self.assertTrue(np.isnan(f['kama']).all())
        self.assertGreater(f['volatility_sum'][-1],0)
        self.assertTrue(np.isfinite(f['efficiency_ratio'][-1]))
        self.assertFalse(f['long'].any() or f['exit_long'].any())

    def test_control_can_enter_invalid_kama_and_remains_censored(self):
        data,frame,_=self.fixture((100,100,100))
        f=study.source_features(frame,study.CANDIDATES[0],self.spec)
        flags=np.array([True,False,False])
        state=self.simulate(data,frame,f,flags)
        self.assertEqual(len(state['events']),1)
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertFalse(state['pending_source_exit'])

    def test_empty_short_input_and_domain(self):
        for n in range(11):
            f=self.features([100.]*n)
            self.assertTrue(all(len(x)==n for x in f.values()))
            self.assertFalse(f['long'].any() or f['exit_long'].any())
        for price in (0.,-1.,float('nan'),float('inf')):
            with self.assertRaises(ValueError):self.features([price])
        # Volume is not part of the mathematical source input.
        frame=self.candles(np.arange(100.,140.));frame[:,5]=np.nan
        np.testing.assert_array_equal(study.source_features(frame,study.CANDIDATES[0],self.spec)['kama'],self.features(np.arange(100.,140.))['kama'])

    def test_full_history_is_not_reseeded_at_warmup(self):
        rng=np.random.default_rng(925)
        prices=100+np.cumsum(rng.normal(size=500))
        all_features=self.features(prices)
        suffix=self.features(prices[240:])
        self.assertNotEqual(all_features['kama'][250],suffix['kama'][10])

    def test_completed_exit_open_excludes_later_extremes(self):
        data,frame,f=self.fixture()
        f['long'][0]=True;f['exit_long'][1]=True
        a=self.simulate(data,frame,f)['events'][0]
        data[960:,2]*=20;data[960:,3]/=20
        frame=shared.bars8h(data)
        b=self.simulate(data,frame,f)['events'][0]
        self.assertEqual(a['mfe_bps_bounds'],b['mfe_bps_bounds'])
        self.assertEqual(a['mae_bps_bounds'],b['mae_bps_bounds'])

if __name__=='__main__':unittest.main()

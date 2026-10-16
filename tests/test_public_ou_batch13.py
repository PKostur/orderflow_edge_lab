import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from orderflow_edge_lab import public_protective_batch5 as shared
from orderflow_edge_lab import public_ou_batch13 as study


ROOT=Path(__file__).resolve().parents[1]


class OUOneUnitTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((ROOT/'config/public_ou_batch13_v1.json').read_text())

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
        self.assertEqual(state['events'][0]['reason'],'source_long_z_exit_to_cash')
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

    def test_control_entries_use_original_long_exit_state(self):
        data,frame,f=self.fixture()
        f['exit_long'][2]=True
        state=self.simulate(data,frame,f,np.array([False,True,False,False]))
        self.assertEqual(state['events'][0]['entry_index'],960)
        self.assertEqual(state['events'][0]['endpoint_minute_index'],1440)

    def test_one_unit_cash_btc_nav_reconcile(self):
        data,frame,f=self.fixture()
        f['long'][0]=True
        f['exit_long'][1]=True
        state=self.simulate(data,frame,f)
        expected=1.
        self.assertEqual(state['events'][0]['quantity'],expected)
        self.assertEqual(state['events'][0]['source_signal_close'],frame[0,2])
        self.assertEqual(state['events'][0]['source_reference_known_at'],shared.stamp(int(data[480,0])))
        total=sum(e['net_cash_profit_or_cutoff_mark'] for e in state['events'])
        self.assertAlmostEqual(state['nav'][-1],10000+total,places=9)
        self.assertAlmostEqual(state['nav'][-1],state['btc_nav_lower'][-1],places=9)

    def test_extreme_gap_cash_rejection_without_resize(self):
        data,frame,f=self.fixture((100,30000))
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
        config=ROOT/'config/public_ou_batch13_v1.json'
        with patch.object(study.subprocess,'check_output',return_value=config.read_bytes()):
            self.assertEqual(study.checked_spec(ROOT,config)['new_registered_trading_cells'],1)
        changed=dict(self.spec)
        changed['ou']=dict(changed['ou'],lookback=31)
        with patch.object(Path,'read_text',return_value=json.dumps(changed)):
            with self.assertRaisesRegex(ValueError,'changed frozen design'):
                study.checked_spec(ROOT,config)

    def test_missing_independent_review_blocks_before_market_load(self):
        with TemporaryDirectory() as scratch:
            with self.assertRaisesRegex(ValueError,'INDEPENDENT_PRE_OUTCOME_REVIEW_REQUIRED'):
                study.require_pre_outcome_review(Path(scratch),self.spec,Path(study.__file__))



    def test_empty_and_invalid_source_domain(self):
        f=study.source_features(np.empty((0,6)),study.CANDIDATES[0],self.spec)
        self.assertEqual(len(f['z_score']),0)
        for close,volume in [(0,1),(-1,1),(float('nan'),1),(float('inf'),1)]:
            frame=self.candles([100]);frame[0,2]=close;frame[0,5]=volume
            with self.assertRaises(ValueError):
                study.source_features(frame,study.CANDIDATES[0],self.spec)





    def test_flat_invalid_fit_never_enters_or_exits(self):
        f=self.features([100.]*80)
        self.assertFalse(f['long'].any() or f['exit_long'].any())

    def test_actual_pinned_native_feature_fixtures(self):
        folder=ROOT/'artifacts/public_ou_batch13_registration_20261015'
        fixtures=json.loads((folder/'ou-8h-synthetic-input.json').read_text())
        native=json.loads((folder/'ou-8h-native-synthetic-output.json').read_text())
        for fixture,expected in zip(fixtures,native):
            frame=self.candles(fixture['prices'])
            got=study.source_features(frame,study.CANDIDATES[0],self.spec)
            for row in expected['rows']:
                i=row['bar'];fit=row['fit']
                self.assertAlmostEqual(got['sma'][i],row['sma'],places=10)
                if fit[0] is None:
                    self.assertFalse(got['long'][i] or got['exit_long'][i])
                    continue
                np.testing.assert_allclose([got[k][i] for k in ['mu','theta','sigma','equilibrium_std']],fit,rtol=1e-9,atol=1e-10)
                if fit[3]<=0:
                    self.assertFalse(got['long'][i] or got['exit_long'][i]);continue
                z=(np.log(fixture['prices'][i])-fit[0])/fit[3]
                self.assertEqual(got['long'][i],bool(z<-1 and fixture['prices'][i]>row['sma']))
                self.assertEqual(got['exit_long'][i],bool(z>0))

    def test_invalid_fit_while_held_does_not_force_exit(self):
        data,frame,f=self.fixture((100,100,100))
        f['long'][0]=True
        f['z_score']=np.array([-2.,np.nan,np.nan])
        state=self.simulate(data,frame,f)
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertEqual(state['events'][0]['quantity'],1.)

    def test_one_unit_quantity_does_not_scale_with_capital_or_signal_price(self):
        for price in [10,100,1000]:
            data,frame,f=self.fixture((price,price))
            f['long'][0]=True
            state=self.simulate(data,frame,f)
            self.assertEqual(state['events'][0]['quantity'],1.)

    def test_nonpositive_theta_fallback_and_long_exit_are_literal(self):
        frame=self.candles([100.+i for i in range(40)])
        with patch.object(study.stats,'linregress',return_value=(.1,.2,0.,0.,0.)):
            got=study.source_features(frame,study.CANDIDATES[0],self.spec)
        values=np.array([np.log(float(x)) for x in frame[-30:,2]])
        self.assertEqual(got['theta'][-1],-.1)
        self.assertEqual(got['mu'][-1],np.mean(values))
        self.assertTrue(got['exit_long'][-1])


    def test_control_replaces_entry_validity_while_invalid_exit_stays_false(self):
        data,frame,f=self.fixture((100,100,100))
        f['z_score']=np.full(len(frame),np.nan)
        native=self.simulate(data,frame,f)
        self.assertEqual(native['events'],[])
        control=self.simulate(data,frame,f,np.array([True,False,False]))
        self.assertEqual(control['counts']['accepted_entries'],1)
        self.assertEqual(control['events'][0]['status'],'CENSORED_MTM')


if __name__=='__main__':
    unittest.main()

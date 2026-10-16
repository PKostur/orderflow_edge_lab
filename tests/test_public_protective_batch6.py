import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from orderflow_edge_lab import public_protective_batch6 as study
from orderflow_edge_lab.public_protective_batch5 import bars8h


class ProtectiveBatch6Tests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.spec = json.loads((root/'config/public_protective_batch6_v1.json').read_text())
        self.spec.update(warmup_bars=1, episode_initial_cash_per_symbol=1000)
        n = 4*480
        self.data = np.column_stack([np.arange(n)*60, np.full(n,100.),np.full(n,101.),
                                    np.full(n,99.),np.full(n,100.),np.ones(n)])
        self.features = dict(long=np.array([True,False,False,False]),exit=np.zeros(4,dtype=bool))

    def run_cmf(self):
        return study.simulate(self.data,self.data,bars8h(self.data),self.features,study.CANDIDATES[1],self.spec,40,'conservative_limit')[0]

    def test_roi_uses_close_and_next_open_never_high_target(self):
        self.data[481,2] = 110
        self.data[482,2:5] = [104,99,103]
        self.data[483,1:5] = [102,105,90,102]
        event = self.run_cmf()['events'][0]
        self.assertEqual(event['endpoint_minute_index'],483)
        self.assertEqual(event['endpoint_reference_price'],102)
        self.assertEqual(event['reason'],'observed_minute_roi_next_open')

    def test_stop_before_same_minute_close_roi(self):
        self.data[481,2:5] = [110,94,103]
        event = self.run_cmf()['events'][0]
        self.assertEqual(event['endpoint_reference_price'],95)
        self.assertEqual(event['reason'],'stop_touch')

    def test_stop_gap_is_adverse_open(self):
        self.data[481,1:5] = [90,92,89,91]
        event = self.run_cmf()['events'][0]
        self.assertEqual(event['endpoint_reference_price'],90)
        self.assertEqual(event['reason'],'stop_gap')

    def test_final_roi_has_no_unavailable_open_fill(self):
        self.data[-1,2:5] = [104,99,103]
        state = self.run_cmf()
        self.assertEqual(state['events'][0]['status'],'CENSORED_MTM')
        self.assertTrue(state['pending_observed_roi_exit'])
        self.assertEqual(state['pending_roi_decision_time'],'1970-01-02T08:00:00Z')
        self.assertIsNotNone(state['position'])

    def test_source_reason_priority_at_queued_roi_boundary(self):
        self.data[959,2:5] = [104,99,103]
        self.features['exit'][1] = True
        event = self.run_cmf()['events'][0]
        self.assertEqual(event['endpoint_minute_index'],960)
        self.assertEqual(event['reason'],'source_signal_exit')

    def test_held_signals_reconcile_and_pending_cash_matches_nav(self):
        self.features['long'][:] = True
        state = self.run_cmf()
        self.assertEqual(state['counts'],dict(raw_entry_flags=4,accepted_entries=1,held_entry_ignored=3))
        self.assertEqual(state['events'][0]['initial_stop'],95)
        self.assertIsNone(state['events'][0]['initial_target'])
        self.assertAlmostEqual(state['nav'][-1]-1000,state['events'][0]['net_cash_profit_or_cutoff_mark'])

    def test_gap_affordability_rejects_without_resize(self):
        self.data[480,1:5] = [102,103,101,102]
        state = self.run_cmf()
        self.assertEqual(state['counts']['cash_rejected'],1)
        self.assertEqual(state['events'],[])

    def test_stop_anchor_is_actual_entry_not_signal_close(self):
        self.data[480,1:5] = [99,100,98,99]
        event = self.run_cmf()['events'][0]
        self.assertEqual(event['entry_price'],99)
        self.assertAlmostEqual(event['initial_stop'],94.05)

    def test_sar_control_reanchors_on_original_qualifier(self):
        features = dict(long=np.array([False,True,False,False]),short=np.zeros(4,dtype=bool),
                        exit=np.zeros(4,dtype=bool),atr=np.array([5.,2.,2.,2.]),
                        stop_atr=3,target_atr=2,risk_fraction=None)
        flags = np.array([True,False,False,False])
        self.data[961,3] = 93
        state = study.simulate(self.data,self.data,bars8h(self.data),features,study.CANDIDATES[0],
                               self.spec,40,'conservative_limit',entry_flags=flags)[0]
        self.assertEqual(state['counts']['bracket_replacements'],1)
        self.assertEqual(state['events'][0]['initial_stop'],85)
        self.assertEqual(state['events'][0]['last_stop'],94)
        self.assertEqual(state['events'][0]['endpoint_reference_price'],94)

    def test_roi_rounding_strict_boundary(self):
        fee = self.spec['cmf']['roi_fee_each_side']
        for profit,expected in [(0.01,False),(.010000004,False),(.010000006,True),(.009999994,False)]:
            price = 100*(1+profit)*(1+fee)/(1-fee)
            self.assertEqual(study.roi_observed(price,100,self.spec),expected)
        self.assertFalse(study.roi_observed(101,100,self.spec))

    def test_cmf_zero_range_propagates_nan_for_full_window(self):
        candles = bars8h(self.data)
        candles = np.tile(candles[0],(50,1))
        candles[:,2] = 99.5
        candles[21,2:5] = 100
        feature = study.source_features(candles,study.CANDIDATES[1],self.spec)
        self.assertTrue(feature['long'][20])
        self.assertTrue(np.isnan(feature['cmf'][21:42]).all())
        self.assertFalse(feature['long'][21:42].any())
        self.assertTrue(feature['long'][42])

    def test_zero_volume_window_stays_undefined(self):
        candles = np.tile(bars8h(self.data)[0],(30,1))
        candles[:,5] = 0
        features = study.source_features(candles,study.CANDIDATES[1],self.spec)
        self.assertTrue(np.isnan(features['cmf']).all())
        self.assertFalse(features['long'].any())

    def test_sar_hand_seeds_tie_and_reversal(self):
        candles = np.array([[0,101,100,110,99,1],[1,100,101,105,98,1],[2,101,101,104,99,1]],dtype=float)
        sar = study.sar_reference(candles)
        self.assertTrue(np.isnan(sar[0]))
        self.assertEqual(list(sar[1:]),[110,110])
        flat = np.tile([0,100,100,100.8,99.4,1],(3,1)).astype(float)
        np.testing.assert_array_equal(study.sar_reference(flat)[1:],[99.4,100.8])

    def test_features_are_prefix_causal_under_future_mutation(self):
        rng = np.random.default_rng(818)
        close = 100*np.exp(np.cumsum(rng.normal(0,.02,400)))
        candles = np.column_stack([np.arange(400)*28800000,close,close,close*1.02,close*.98,rng.uniform(1,10,400)])
        for candidate in study.CANDIDATES:
            full = study.source_features(candles,candidate,self.spec)
            for n in (2,14,21,83,239,300):
                truncated = study.source_features(candles[:n],candidate,self.spec)
                for key,value in truncated.items():
                    if isinstance(value,np.ndarray):
                        np.testing.assert_array_equal(value,full[key][:n])
            changed = candles.copy()
            changed[300:,2:5] *= 20
            changed[300:,5] *= 9
            altered = study.source_features(changed,candidate,self.spec)
            for key,value in full.items():
                if isinstance(value,np.ndarray):
                    np.testing.assert_array_equal(value[:300],altered[key][:300])

    def test_reject_changed_dependency_and_design(self):
        root = Path(__file__).resolve().parents[1]
        frozen = (root/'config/public_protective_batch6_v1.json').read_bytes()
        # CI's shallow checkout need not retain the older registration commit.
        with patch.object(study.subprocess,'check_output',return_value=frozen):
            spec = study.checked_spec(root,root/'config/public_protective_batch6_v1.json')
        self.assertEqual(spec['minimum_registered_trading_cells_after_freeze'],19)


if __name__ == '__main__':
    unittest.main()

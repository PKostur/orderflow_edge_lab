import json
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import numpy as np
from orderflow_edge_lab import public_dual_thrust_batch9 as study
from orderflow_edge_lab import public_protective_batch5 as shared
ROOT=Path(__file__).resolve().parents[1]

class KernelFixture:
    def __init__(self):self.lengths=[]
    def atr_last(self,candles,period):
        self.lengths.append(len(candles))
        return float(np.mean(candles[:,3]-candles[:,4]))

class DualThrustTests(unittest.TestCase):
    def setUp(self):self.spec=json.loads((ROOT/'config/public_dual_thrust_batch9_v1.json').read_text())
    def candles(self,n=300):
        rng=np.random.default_rng(15);c=100+np.cumsum(rng.normal(0,.2,n))
        return np.column_stack((1680307200000+np.arange(n)*28800000,c-.1,c,c+2,c-2,np.ones(n)))
    def features(self,frame,kernel=None):return study.source_features(frame,study.CANDIDATES[0],self.spec,kernel or KernelFixture())
    def fixture(self,n=4):
        data=np.column_stack((1680307200+np.arange(n*480)*60,np.full(n*480,100.),np.full(n*480,102.),np.full(n*480,98.),np.full(n*480,100.),np.ones(n*480)))
        btc=data.copy();btc[:,1:5]*=10
        frame=shared.bars8h(data)
        f=dict(long=np.zeros(n,bool),short=np.zeros(n,bool),atr=np.full(n,5.))
        return data,btc,frame,f
    def simulate(self,data,btc,frame,f,flags=None,gap='conservative_limit',cash=10000):
        spec=dict(self.spec,warmup_bars=1,episode_initial_cash_per_symbol=cash)
        return study.simulate(data,btc,frame,f,study.CANDIDATES[0],spec,40,gap,entry_flags=flags)[0]
    def test_requires_selected_kernel(self):
        with self.assertRaisesRegex(ValueError,'kernel'):study.source_features(self.candles(),study.CANDIDATES[0],self.spec)
    def test_known_daily_anchor_and_midnight_boundary(self):
        frame=self.candles(9);frame[:,1]=[101,201,301,102,202,302,103,203,303]
        f=self.features(frame)
        np.testing.assert_array_equal(f['anchor'],[101]*3+[102]*3+[103]*3)
        self.assertEqual(f['anchor'][2],101)  # prior16bar at00decision
        self.assertEqual(f['anchor'][3],102)  # current00bar at08decision
    def test_partial_source_startup_and_exact_native_crop(self):
        frame=self.candles();k=KernelFixture();f=self.features(frame,k)
        self.assertTrue(np.isfinite(f['upper']).all())
        self.assertTrue(np.isnan(f['atr'][:13]).all())
        self.assertEqual(k.lengths[0],14);self.assertEqual(k.lengths[-1],240)
        self.assertEqual(k.lengths.count(240),61)
    def test_source_low_column_asymmetry(self):
        frame=self.candles(21);frame[:,1:5]=[100,100,200,80];frame[-1,2]=80
        f=self.features(frame)
        self.assertAlmostEqual(f['lower'][-1],100-.67*20)
        self.assertTrue(f['short'][-1])
        corrected=100-.67*120
        self.assertFalse(frame[-1,2]<corrected)
    def test_strict_threshold_equality(self):
        frame=self.candles(21);frame[:,1:5]=[100,100,200,90];frame[-1,2]=171
        self.assertFalse(self.features(frame)['long'][-1])
        frame[-1,2]=np.nextafter(171,np.inf);self.assertTrue(self.features(frame)['long'][-1])
        frame[:,1:5]=[100,100,110,90];frame[-1,2]=100-.67*10
        self.assertFalse(self.features(frame)['short'][-1])
        frame[-1,2]=np.nextafter(frame[-1,2],-np.inf);self.assertTrue(self.features(frame)['short'][-1])
    def test_causal_features_all_prefixes_and_future_mutation(self):
        frame=self.candles();original=self.features(frame)
        for n in (1,13,14,20,21,99,239,240,241,299):
            prefix=self.features(frame[:n])
            for key in original:np.testing.assert_array_equal(original[key][:n],prefix[key])
        frame[150:,1:5]*=2;mutated=self.features(frame)
        for key in original:np.testing.assert_array_equal(original[key][:150],mutated[key][:150])
    def test_missing_daily_open_and_grid_fail_closed(self):
        frame=self.candles();frame[:,0]+=28800000
        with self.assertRaisesRegex(ValueError,'daily00'):self.features(frame)
        frame=self.candles();frame[10:,0]+=28800000
        with self.assertRaisesRegex(ValueError,'grid'):self.features(frame)
    def test_quantity_native_cap_and_fee_reserve_double_floor(self):
        for cash,signal,stop in ((1000,200,180),(1000,200,199.5),(1000,17.12345,17.12340)):
            q,quote,source=study.source_quantity(cash,signal,stop,.002,self.spec)
            expected_quote=min((cash*.02/(signal-stop))*signal,cash)
            floor=lambda x:float(Decimal(str(x)).quantize(Decimal('.00000001'),rounding=ROUND_DOWN))
            expected_source=floor(expected_quote/signal)
            self.assertEqual(quote,expected_quote);self.assertEqual(source,expected_source)
            self.assertEqual(q,floor(min(expected_source,cash/(signal*1.002))))
            self.assertLessEqual(q*signal*1.002,cash+1e-10)
    def test_source_exit_next_open_held_no_reentry_or_stop_reanchor(self):
        data,btc,frame,f=self.fixture();f['long'][:3]=True;f['atr'][1]=20;f['short'][1]=True
        s=self.simulate(data,btc,frame,f)
        self.assertEqual(s['events'][0]['entry_index'],480);self.assertEqual(s['events'][0]['endpoint_minute_index'],960)
        self.assertEqual(s['events'][0]['initial_stop'],90);self.assertEqual(s['events'][0]['last_stop'],90)
        self.assertEqual(s['counts']['held_entry_ignored'],1);self.assertEqual(s['events'][1]['entry_index'],1440)
    def test_intraminute_stop_excursion_uncertainty(self):
        data,btc,_,f=self.fixture();f['long'][0]=True;data[500,2:4]=[110,80];frame=shared.bars8h(data)
        e=self.simulate(data,btc,frame,f)['events'][0]
        self.assertEqual(e['reason'],'stop_touch');self.assertEqual(e['endpoint_minute_index'],500)
        self.assertEqual(e['endpoint_reference_price'],90);self.assertEqual(e['holding_minutes_bounds'],[20,21])
        self.assertEqual(e['mfe_bps_bounds'],[200.00000000000017,1000.0000000000009])
        self.assertEqual(e['mae_bps_bounds'],[-1999.9999999999995,-999.9999999999998])
        self.assertLess(e['btc_net_lower_bps'],e['btc_net_upper_bps'])
    def test_entry_boundary_gap_stop_permitted(self):
        data,btc,_,f=self.fixture();f['long'][0]=True;data[480,1:5]=[85,87,83,85];frame=shared.bars8h(data)
        e=self.simulate(data,btc,frame,f)['events'][0]
        self.assertEqual(e['entry_index'],e['endpoint_minute_index']);self.assertEqual(e['reason'],'stop_gap')
        self.assertEqual(e['entry_price'],85);self.assertEqual(e['endpoint_reference_price'],85)
        self.assertEqual(e['holding_minutes_bounds'],[0,0]);self.assertEqual(e['last_stop'],90)
    def test_scheduled_source_close_priority_at_gap(self):
        data,btc,_,f=self.fixture();f['long'][0]=True;f['short'][1]=True;data[960,1:5]=[85,87,83,85];frame=shared.bars8h(data)
        e=self.simulate(data,btc,frame,f)['events'][0]
        self.assertEqual(e['reason'],'source_short_to_cash');self.assertEqual(e['endpoint_reference_price'],85)
    def test_fixed_nextopen_cash_rejection_without_resize(self):
        data,btc,_,f=self.fixture();f['long'][0]=True;f['atr'][0]=.1;data[480:960,1:5]=[150,152,148,150];frame=shared.bars8h(data)
        s=self.simulate(data,btc,frame,f)
        self.assertEqual(s['counts']['cash_rejected'],1);self.assertEqual(s['events'],[]);self.assertEqual(s['cash'],10000)
    def test_invalid_atr_stop_and_zero_quantity_accounting(self):
        for atr in (np.nan,0,100):
            data,btc,frame,f=self.fixture();f['long'][0]=True;f['atr'][0]=atr
            self.assertEqual(self.simulate(data,btc,frame,f)['counts']['invalid_entry'],1)
        data,btc,frame,f=self.fixture();f['long'][0]=True
        self.assertEqual(self.simulate(data,btc,frame,f,cash=1e-8)['counts']['zero_quantity'],1)
    def test_control_own_atr_stop_quantity_and_original_state_exit(self):
        data,btc,frame,f=self.fixture();f['atr'][1]=2;f['short'][2]=True
        s=self.simulate(data,btc,frame,f,np.array([False,True,False,False]))
        e=s['events'][0];self.assertEqual(e['entry_index'],960);self.assertEqual(e['initial_stop'],96)
        self.assertEqual(e['quantity'],50);self.assertEqual(e['endpoint_minute_index'],1440)
    def test_censors_pending_exit_and_unexecuted_final_entry(self):
        data,btc,frame,f=self.fixture();f['long'][0]=True;f['short'][-1]=True
        s=self.simulate(data,btc,frame,f);self.assertEqual(s['events'][0]['status'],'CENSORED_MTM');self.assertTrue(s['pending_source_exit'])
        f['long'][:]=False;f['long'][-1]=True;s=self.simulate(data,btc,frame,f)
        self.assertEqual(s['counts']['unexecuted_final_entry'],1);self.assertEqual(s['events'],[])
    def test_funded_alt_btc_cash_reconciliation_and_gap_identity(self):
        data,btc,frame,f=self.fixture();f['long'][0]=True;f['short'][1]=True
        a=self.simulate(data,btc,frame,f);b=self.simulate(data,btc,frame,f,gap='opening_price_improvement')
        self.assertEqual(a,b);self.assertEqual(a['cash'],9992);self.assertEqual(a['btc_cash_lower'],9992)
        self.assertEqual(a['btc_cash_upper'],9992);self.assertEqual(a['nav'][-1],9992)
    def test_frozen_config_hash_and_missing_committed_review(self):
        spec=study.checked_spec(ROOT,ROOT/'config/public_dual_thrust_batch9_v1.json')
        self.assertEqual(shared.digest(spec),study.DESIGN_SHA256)
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'INDEPENDENT_PRE_OUTCOME_REVIEW_REQUIRED'):
                study.require_pre_outcome_review(Path(folder),spec,ROOT/'src/orderflow_edge_lab/public_dual_thrust_batch9.py')

if __name__=='__main__':unittest.main()

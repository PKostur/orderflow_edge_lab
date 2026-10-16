import copy
import json
import unittest
import numpy as np
from orderflow_edge_lab import public_screen_supplement as m


class ScreenSupplementTests(unittest.TestCase):
    def path(self):
        return np.array([[0,100,105,95,101,1],[60,101,110,90,103,1],[120,104,999,1,400,1]],float)

    def event(self,**updates):
        e=dict(entry_index=0,endpoint_minute_index=2,entry_price=100.,endpoint_reference_price=104.,
               status='COMPLETED',exit_interval=['x','x'],mfe_bps_bounds=[1000.,1000.],mae_bps_bounds=[-1000.,-1000.],
               gross_bps=400.,net_bps=358.4830339321357,symbol='ETHUSDT',entry_time='2023-01-02T00:00:00Z',
               month='2023-01',entry_week='2023-01-02',btc_net_lower_bps=10.,btc_net_upper_bps=10.,
               net_cash_profit_or_cutoff_mark=10.)
        e.update(updates);return e

    def examples(self):
        return [self.event(net_bps=10,gross_bps=20,mfe_bps_bounds=[50.,50.],mae_bps_bounds=[-10.,-10.]),
                self.event(net_bps=-5,gross_bps=-1,mfe_bps_bounds=[20.,20.],mae_bps_bounds=[-30.,-30.],entry_week='2023-01-09',net_cash_profit_or_cutoff_mark=-5),
                self.event(net_bps=20,gross_bps=40,mfe_bps_bounds=[100.,100.],mae_bps_bounds=[-5.,-5.],symbol='SOLUSDT',net_cash_profit_or_cutoff_mark=15)]

    def test_open_exit_excludes_endpoint_minute_extremes(self):
        r=m.excursion_details(self.event(),self.path())
        np.testing.assert_allclose(r['pre_first_mfe_mae_bps_bounds'],[-1000,-500],rtol=0,atol=1e-9)
        self.assertEqual(r['first_mfe_minute_index'],1)
        self.assertEqual(r['mfe_bps_bounds'],[1000,1000])

    def test_peak_at_minute_open_excludes_later_low(self):
        d=self.path();d[1,1:5]=[110,110,80,104]
        r=m.excursion_details(self.event(mae_bps_bounds=[-2000,-2000]),d)
        np.testing.assert_allclose(r['pre_first_mfe_mae_bps_bounds'],[-500,-500],rtol=0,atol=1e-9)

    def test_censor_includes_full_final_minute(self):
        d=self.path();d[2,1:5]=[104,120,70,104]
        e=self.event(status='CENSORED_MTM',exit_interval=None,mfe_bps_bounds=[2000,2000],mae_bps_bounds=[-3000,-3000])
        r=m.excursion_details(e,d)
        self.assertEqual(r['first_mfe_minute_index'],2)
        np.testing.assert_allclose(r['pre_first_mfe_mae_bps_bounds'],[-3000,-1000],rtol=0,atol=1e-9)

    def test_first_tied_maximum_ignores_later_adversity(self):
        d=self.path();d[0,2]=110;d[1,3]=80
        r=m.excursion_details(self.event(mae_bps_bounds=[-2000,-2000]),d)
        self.assertEqual(r['first_mfe_minute_index'],0)
        np.testing.assert_allclose(r['pre_first_mfe_mae_bps_bounds'],[-500,0],rtol=0,atol=1e-9)

    def test_entry_is_first_maximum_when_no_favorable_move(self):
        d=self.path();d[0,1:5]=[100,100,95,98];d[1,1:5]=[98,99,90,95];d[2,1]=94
        e=self.event(endpoint_reference_price=94,gross_bps=-600,mfe_bps_bounds=[0,0])
        r=m.excursion_details(e,d)
        self.assertEqual(r['pre_first_mfe_mae_bps_bounds'],[0,0]);self.assertFalse(r['endpoint_correct_direction'])

    def test_unresolved_intraminute_exit_uses_conservative_bound(self):
        d=self.path();d[2,1:5]=[104,120,80,110]
        e=self.event(endpoint_reference_price=105,gross_bps=500,exit_interval=['x','y'],mfe_bps_bounds=[1000,2000],mae_bps_bounds=[-2000,-1000])
        r=m.excursion_details(e,d)
        self.assertIsNone(r['first_mfe_minute_index']);self.assertEqual(r['pre_first_mfe_mae_bps_bounds'],[-2000,0])

    def test_intraminute_exit_with_larger_prior_peak_identified(self):
        d=self.path();d[1,2]=120;d[2,1:5]=[104,115,80,110]
        e=self.event(endpoint_reference_price=105,gross_bps=500,exit_interval=['x','y'],mfe_bps_bounds=[2000,2000],mae_bps_bounds=[-2000,-1000])
        r=m.excursion_details(e,d)
        self.assertEqual(r['first_mfe_minute_index'],1)
        np.testing.assert_allclose(r['pre_first_mfe_mae_bps_bounds'],[-1000,-500],rtol=0,atol=1e-9)

    def test_medians_extreme_trades_and_direction(self):
        r=m.event_summary(self.examples(),3)
        self.assertEqual(r['median_mfe_bps_bounds'],[50,50]);self.assertEqual(r['median_mae_bps_bounds'],[-10,-10])
        self.assertEqual(r['worst_net_trade']['net_bps'],-5);self.assertEqual(r['best_net_trade']['net_bps'],20)
        self.assertEqual(r['correct_direction_endpoint_fraction'],2/3)

    def test_absolute_event_cash_concentration_not_absolute_group_net(self):
        r=m.concentration(self.examples(),'symbol')
        self.assertEqual([x['absolute_event_cash_pnl'] for x in r['rows']],[15,15])
        self.assertEqual([x['signed_cash_pnl'] for x in r['rows']],[5,15]);self.assertEqual(r['hhi_absolute_event_cash_pnl'],.5)

    def test_positive_active_weeks_and_calendar_zeros(self):
        r=m.event_summary(self.examples(),3)
        self.assertEqual(r['positive_active_week_fraction'],.5)
        self.assertEqual(r['positive_calendar_week_fraction_including_zeros'],1/3)
        self.assertEqual(r['zero_event_calendar_weeks'],1)

    def test_beta_exact_line_and_undefined_constant_btc(self):
        e=self.examples()
        for v,x in zip(e,[-10,0,10]):v.update(btc_net_lower_bps=x,net_bps=2*x+5)
        r=m.beta_fit(e,'btc_net_lower_bps');self.assertEqual(r['beta'],2);self.assertEqual(r['intercept_bps'],5)
        for v in e:v['btc_net_lower_bps']=10
        self.assertIsNone(m.beta_fit(e,'btc_net_lower_bps')['beta'])
        self.assertIsNone(m.beta_fit([],'btc_net_lower_bps')['beta'])

    def test_fixed_reference_cost_curve_uses_two_notional_sides(self):
        e=self.event(entry_price=100,endpoint_reference_price=110)
        r=m.reference_cost_curve([e]);self.assertEqual(r['cases']['40']['mean_net_bps'],10000*(1.1*.998/1.002-1))
        means=[r['cases'][str(c)]['mean_net_bps'] for c in (10,20,30,40,60,80)]
        self.assertTrue(all(a>b for a,b in zip(means,means[1:])))
        peak=m.excursion_details(self.event(),self.path())['hypothetical_peak_net_after_cost_bps_bounds'][0]
        self.assertAlmostEqual(peak,r['cases']['40']['mean_net_bps'],places=9)

    def test_signal_availability_clock_warmup_final_and_overlap(self):
        c=np.zeros((3,6));c[:,0]=np.arange(3)*28800000
        r=m.source_signal_clock(c,[True,True,True],1)['completion_clock']
        self.assertEqual(r['n'],3);self.assertEqual(r['exclusive_membership_counts'],{'Asia':1,'Asia+London':1,'New_York':1})
        r=m.source_signal_clock(c,[True,True,True],2)['completion_clock']
        self.assertEqual(r['utc_hour_counts'],{'0':1,'16':1})

    def test_no_mutation_empty_json_and_invalid_inputs(self):
        d=self.path();before=d.copy();e=self.event();original=copy.deepcopy(e)
        r=m.excursion_details(e,d);self.assertEqual(e,original);np.testing.assert_array_equal(d,before)
        json.dumps(r,allow_nan=False);json.dumps(m.event_summary([],3),allow_nan=False)
        for bad in [dict(e,status='unknown'),dict(e,entry_index=-1),dict(e,mfe_bps_bounds=[1,1]),dict(e,mae_bps_bounds=[0,0])]:
            with self.assertRaises(ValueError):m.excursion_details(bad,d)
        with self.assertRaises(ValueError):m.excursion_details(e,d,side_bps=-1)
        intraminute=dict(e,entry_price=101,mfe_bps_bounds=[10000*(110/101-1)]*2,mae_bps_bounds=[10000*(90/101-1)]*2)
        with self.assertRaisesRegex(ValueError,'entry.*OPEN'):m.excursion_details(intraminute,d)
        d[0,1]=np.nan
        with self.assertRaises(ValueError):m.excursion_details(e,d)
        with self.assertRaises(ValueError):m.event_summary(self.examples(),1)


if __name__=='__main__':unittest.main()

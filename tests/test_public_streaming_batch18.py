"""Own synthetic-only full-prototype regression fixtures; no market inputs."""
import copy
import json
import math
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch
import numpy as np

REPO = Path(__file__).resolve().parents[1]
ART = REPO / 'artifacts/public_streaming_batch18_registration_20261017'
sys.path.insert(0, str(REPO / 'src'))
from orderflow_edge_lab import public_streaming_batch18 as draft

import importlib.util
from importlib.machinery import SourceFileLoader
import tempfile

loader = SourceFileLoader('batch18_own_scalar_reference', str(ART / 'own-mathematical-reference.py.txt'))
reference_spec = importlib.util.spec_from_loader(loader.name, loader)
reference = importlib.util.module_from_spec(reference_spec)
sys.modules[loader.name] = reference
loader.exec_module(reference)
scalar_simulate = reference.simulate

FULL_PROOF = False
SPEC = json.loads((REPO / 'config/public_streaming_batch18_v1.json').read_text())
FIXTURES_PATH = ART / 'Quickstart-UpDown-selected-synthetic-fixtures.json'
NATIVE_PATH = ART / 'Quickstart-UpDown-selected-native-output.json'
FIXTURES = json.loads(FIXTURES_PATH.read_text())['funding_fixtures']
NATIVE = json.loads(NATIVE_PATH.read_text())
RESIDUALS = {'native_fills_compared': 0, 'native_fixtures_compared': 0,
             'native_max_absolute_fill_price_difference': 0., 'scalar_max_absolute_cash_difference': 0.,
             'scalar_fixtures_compared': 0, 'btc_manual_max_absolute_cash_difference': 0.}


def minutes(opens, closes):
    n = len(opens)
    a = np.zeros((n * 480, 6), dtype=float)
    a[:, 0] = 1577836800 + np.arange(n * 480) * 60
    a[:, 1] = np.repeat(opens, 480)
    a[:, 4] = a[:, 1]
    a[479::480, 4] = closes
    a[:, 2] = np.maximum(a[:, 1], a[:, 4]) + 1
    a[:, 3] = np.minimum(a[:, 1], a[:, 4]) * .99
    a[:, 5] = 1.
    return a


def run_fixture(kind, fixture, cost=40, btc=None, flags=None, gap=None):
    data = minutes(fixture['opens'], fixture['closes'])
    if btc is None:
        # Deliberately separate BTC path/cash, not source returns substituted.
        count = len(fixture['opens'])
        bp = 1000 + np.arange(count) * 1.7 + np.sin(np.arange(count))
        btc = minutes(bp, bp * 1.001)
    candles = draft.shared.bars8h(data)
    candidate = draft.CANDIDATES[0 if kind == 'quickstart' else 1]
    features = draft.source_features(candles, candidate, SPEC)
    state = draft.simulate(data, btc, candles, features, candidate, SPEC, cost,
                           gap or SPEC['gap_target_models'][0], entry_flags=flags)[0]
    return state, data, btc, candles, features


class Batch18DraftTests(unittest.TestCase):
    def test_registered_cli_help_resolves_runtime_names_without_loading_data(self):
        completed = subprocess.run([sys.executable, '-m', 'orderflow_edge_lab.public_streaming_batch18', '--help'],
                                   cwd=REPO, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('--raw', completed.stdout)
        self.assertIn('--cache', completed.stdout)

    def test_native_selected_streaming_fill_and_inventory_parity(self):
        cases = [('funded', 'funded'), ('created_unfunded_gapdown', 'created_unfunded_gapdown'),
                 ('execution_unfunded_gapup', 'execution_unfunded_gapup'),
                 ('origin239', 'origin_comparison'), ('final_cutoff', 'final_entry_cutoff'),
                 ('open_position_censored', 'final_exit_cutoff')]
        for kind in ('quickstart', 'updown'):
            examples=[(NATIVE[f'{kind}_{suffix}']['native'],FIXTURES[f'{kind}_{fixture}']) for suffix,fixture in cases]
            for native_name,fixture_name in [('baseline','prefix_future_baseline'),('mutated','prefix_future_mutated'),('prefix','prefix330')]:
                examples.append((NATIVE[kind+'_prefix_future'][native_name],FIXTURES[kind+'_'+fixture_name]))
            for native,fixture in examples:
                with self.subTest(kind=kind,length=len(fixture['opens'])):
                    result, *_ = run_fixture(kind, fixture)
                    expected = [(r['bar'], r['size'], r['price']) for r in native['notifications'] if r['status'] == 'Completed']
                    actual = [(r['fill_bar'], r['quantity'] * (1 if r['intent'] == 'ENTRY' else -1), r['fill_price'])
                              for r in result['orders'] if r['status'].startswith('FILLED')]
                    self.assertEqual([(i, q) for i, q, _ in expected], [(i, q) for i, q, _ in actual])
                    for (_, _, price), (_, _, ref) in zip(expected, actual, strict=True):
                        difference = abs(price - ref)
                        RESIDUALS['native_max_absolute_fill_price_difference'] = max(RESIDUALS['native_max_absolute_fill_price_difference'], difference)
                        self.assertLessEqual(difference, 1e-10)
                    expected_qty = float(native['final_quantity'])
                    self.assertEqual(result['position']['quantity'] if result['position'] else 0., expected_qty)
                    self.assertEqual(result['pending_order'] is not None, bool(native['pending_at_cutoff']))
                    traces={t['bar']:t for t in result['trace']}
                    created={o['created_bar'] for o in result['orders']}
                    for native_state in native['states']:
                        bar=native_state['bar']
                        if bar in traces:
                            self.assertEqual(traces[bar]['quantity'],native_state['quantity'])
                            self.assertEqual(bar in created,bool(native_state['pending']))
                    RESIDUALS['native_fills_compared'] += len(expected)
                    RESIDUALS['native_fixtures_compared'] += 1

    def test_all_selected_scalar_cash_and_source_state_parity(self):
        for name, fixture in FIXTURES.items():
            kind = name.split('_')[0]
            result, *_ = run_fixture(kind, fixture)
            helper, _ = scalar_simulate(kind, fixture['opens'], fixture['closes'], origin=239, final_cancel=False)
            error = abs(result['cash'] - helper.cash)
            RESIDUALS['scalar_max_absolute_cash_difference'] = max(RESIDUALS['scalar_max_absolute_cash_difference'], error)
            self.assertLessEqual(error, 1e-9)
            self.assertEqual(result['position']['quantity'] if result['position'] else 0., helper.quantity)
            ours = [(o['fill_bar'], o['intent'], o['quantity'], o['fill_price']) for o in result['orders'] if o['status'].startswith('FILLED')]
            scalar = [(o['bar'], o['intent'], o['quantity'], o['price']) for o in helper.events if o['status'].startswith('FILLED')]
            self.assertEqual(ours, scalar)
            RESIDUALS['scalar_fixtures_compared'] += 1

    def test_two_stage_funding_boundary_and_no_extra_cash_btc(self):
        for kind in ('quickstart', 'updown'):
            for suffix, reason in [('created_unfunded_gapdown', 'SUBMISSION_MARGIN'), ('execution_unfunded_gapup', 'EXECUTION_MARGIN')]:
                result, *_ = run_fixture(kind, FIXTURES[kind + '_' + suffix])
                self.assertTrue(any(o['status'] == reason for o in result['orders']))
                # Failed source entry must not debit benchmark wallet.
                first = next(o for o in result['orders'] if o['status'] == reason)
                snapshot = next(t for t in result['trace'] if t['bar'] == first['due_bar'])
                self.assertEqual(snapshot['cash'], 10000.)
                self.assertEqual(snapshot['btc_cash'], 10000.)
        for quantity in (1., 10.):
            price = 10000 / (quantity * 1.002)
            expected = (10000 - quantity * price) - quantity * price * .002
            self.assertEqual(draft.debit(10000, quantity, price, .002), expected)
            self.assertLess(draft.debit(10000, quantity, math.nextafter(price, math.inf), .002), 0)

    def test_full_btc_cash_lifecycle_and_nav_manual_reference(self):
        for kind in ('quickstart', 'updown'):
            result, data, btc, *_ = run_fixture(kind, FIXTURES[kind + '_prefix_future_baseline'])
            cash, bcash, active = 10000., 10000., None
            filled = {o['fill_bar']: o for o in result['orders'] if o['status'].startswith('FILLED')}
            for trace in result['trace']:
                b = trace['bar']
                order = filled.get(b)
                if order:
                    q, ap, bp = order['quantity'], float(data[b*480, 1]), float(btc[b*480, 1])
                    if order['intent'] == 'ENTRY':
                        fraction = q * ap / cash
                        bq = bcash * fraction / bp
                        cash = (cash - q * ap) - q * ap * .002
                        bcash = (bcash - bq * bp) - bq * bp * .002
                        active = (q, bq)
                    else:
                        bq = active[1]
                        cash = (cash + q * ap) - q * ap * .002
                        bcash = (bcash + bq * bp) - bq * bp * .002
                        active = None
                self.assertAlmostEqual(trace['cash'], cash, places=9)
                error = abs(trace['btc_cash'] - bcash)
                RESIDUALS['btc_manual_max_absolute_cash_difference'] = max(RESIDUALS['btc_manual_max_absolute_cash_difference'], error)
                self.assertLess(error, 1e-9)
                k = b - 240 + 1
                ap_close, bp_close = data[(b+1)*480-1, 4], btc[(b+1)*480-1, 4]
                expected = bcash if active is None else (bcash + active[1] * bp_close) - active[1] * bp_close * .002
                self.assertAlmostEqual(result['btc_nav_lower'][k], expected, places=8)
                self.assertEqual(result['btc_nav_lower'][k], result['btc_nav_upper'][k])
            for event in result['events']:
                self.assertEqual(event['source_signal_close'], data[event['entry_index']-1, 4])
                self.assertEqual(event['source_created_bar']+1, event['source_entry_bar'])
                self.assertTrue(0 < event['source_notional_fraction'] < 1)

    def test_cold_origin_and_no_same_open_reentry_quick_clock(self):
        for kind in ('quickstart', 'updown'):
            result, *_ = run_fixture(kind, FIXTURES[kind + '_origin_comparison'])
            self.assertTrue(all(o['created_bar'] >= 239 for o in result['orders']))
            entries = [o for o in result['orders'] if o['status'] == 'FILLED_ENTRY']
            self.assertEqual(entries[0]['fill_bar'], 240)
            fills = [o['fill_bar'] for o in result['orders'] if o['status'].startswith('FILLED')]
            self.assertEqual(len(fills), len(set(fills)))
            if kind == 'quickstart':
                for event in result['events']:
                    if event['status'] == 'COMPLETED':
                        self.assertEqual(event['endpoint_minute_index'] // 480, event['source_entry_bar'] + 6)

    def test_censor_queued_entries_and_final_pending_exits_separate(self):
        for kind in ('quickstart', 'updown'):
            entry, *_ = run_fixture(kind, FIXTURES[kind + '_final_entry_cutoff'])
            self.assertEqual(entry['pending_order']['status'], 'FINAL_QUEUED_UNFILLED')
            self.assertEqual(entry['pending_order']['intent'], 'ENTRY')
            self.assertEqual(entry['events'], [])
            self.assertEqual(entry['cash'], 10000.)
            exit_, *_ = run_fixture(kind, FIXTURES[kind + '_final_exit_cutoff'])
            self.assertEqual(exit_['events'][-1]['status'], 'CENSORED_MTM')
            self.assertIsNone(exit_['events'][-1]['exit_interval'])
            self.assertTrue(exit_['pending_source_exit'])
            self.assertEqual(exit_['pending_order']['intent'], 'EXIT')
            self.assertIsNotNone(exit_['position'])

    def test_mfe_excludes_future_exit_candle_and_censor_known_cutoff(self):
        fixture = FIXTURES['quickstart_origin_comparison']
        state, data, btc, candles, features = run_fixture('quickstart', fixture)
        event = next(e for e in state['events'] if e['status'] == 'COMPLETED')
        j = event['endpoint_minute_index']
        changed = data.copy();changed[j:j+480, 2] = 1000000.
        modified_candles = draft.shared.bars8h(changed)
        modified_features = draft.source_features(modified_candles, draft.CANDIDATES[0], SPEC)
        altered = draft.simulate(changed, btc, modified_candles, modified_features, draft.CANDIDATES[0], SPEC, 40, SPEC['gap_target_models'][0])[0]
        self.assertEqual(event['mfe_bps_bounds'], altered['events'][0]['mfe_bps_bounds'])
        censored, *_ = run_fixture('quickstart', FIXTURES['quickstart_final_exit_cutoff'])
        e = censored['events'][-1]
        self.assertEqual(e['mfe_bps_bounds'][0], e['mfe_bps_bounds'][1])
        self.assertEqual(e['mae_bps_bounds'][0], e['mae_bps_bounds'][1])

    def test_future_price_invariance_and_feature_prefix_causality(self):
        for kind in ('quickstart', 'updown'):
            base, *_ = run_fixture(kind, FIXTURES[kind+'_prefix_future_baseline'])
            changed, *_ = run_fixture(kind, FIXTURES[kind+'_prefix_future_mutated'])
            prefix, *_ = run_fixture(kind, FIXTURES[kind+'_prefix330'])
            self.assertEqual([o for o in base['orders'] if o.get('fill_bar',o['due_bar']) <330],
                             [o for o in changed['orders'] if o.get('fill_bar',o['due_bar']) <330])
            self.assertEqual(base['trace'][:90], prefix['trace'])
            self.assertEqual(base['nav'][:91], prefix['nav'])

    def test_control_replacement_keeps_quantity_funding_and_own_quick_clock(self):
        fixture = FIXTURES['quickstart_prefix_future_baseline']
        count = len(fixture['opens']);flags=np.zeros(count,dtype=bool);flags[250:260]=True;flags[280]=True
        state, *_ = run_fixture('quickstart', fixture, flags=flags)
        self.assertEqual(state['counts']['raw_entry_flags'], int(flags[239:].sum()))
        for order in state['orders']:
            self.assertEqual(order['quantity'], 1.)
        for e in state['events']:
            if e['status']=='COMPLETED':
                self.assertEqual(e['endpoint_minute_index']//480, e['source_entry_bar']+6)
        up, *_ = run_fixture('updown', FIXTURES['updown_prefix_future_baseline'], flags=flags)
        self.assertTrue(all(o['quantity']==10 for o in up['orders']))

    def test_gap_label_duplicate_costs_and_cash_only_rejection_invariants(self):
        fixture=FIXTURES['quickstart_origin_comparison']
        for cost in SPEC['cost_cases_bps']:
            first,*_=run_fixture('quickstart',fixture,cost=cost,gap=SPEC['gap_target_models'][0])
            second,*_=run_fixture('quickstart',fixture,cost=cost,gap=SPEC['gap_target_models'][1])
            self.assertEqual(first,second)
            self.assertTrue(all(t['cash']>=0 and t['btc_cash']>=0 and t['quantity']>=0 for t in first['trace']))

    def test_fixed_source_thresholds_and_longcash_refuses_flat_short(self):
        close=np.full(260,100.)
        close[239]=99.;close[240]=98.;close[241]=101.
        data=minutes(close,close);candles=draft.shared.bars8h(data)
        up=draft.source_features(candles,draft.CANDIDATES[1],SPEC)
        self.assertFalse(up['long'][239])
        self.assertTrue(up['long'][240])
        self.assertTrue(up['exit_long'][241])
        positive={'opens':np.full(260,102.).tolist(),'closes':np.full(260,102.).tolist()}
        positive['closes'][199]=100.;positive['closes'][239]=102.
        state,*_=run_fixture('updown',positive)
        self.assertEqual(state['counts'].get('accepted_entries',0),0)
        self.assertGreaterEqual(state['counts']['upstream_flat_short_refused'],1)

    def test_invalid_domains_and_cold_loader_registration_barrier(self):
        fixture=FIXTURES['quickstart_origin_comparison']
        state,data,btc,candles,features=run_fixture('quickstart',fixture)
        for bad in (0.,-1.,math.nan,math.inf):
            invalid=candles.copy();invalid[240,2]=bad
            with self.assertRaises(ValueError): draft.source_features(invalid,draft.CANDIDATES[0],SPEC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'
            config.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed frozen design'):
                draft.checked_spec(root, config)
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_PRE_OUTCOME_REVIEW_REQUIRED'):
                draft.require_pre_outcome_review(root, SPEC, Path(draft.__file__))
        for key,value in [('warmup_bars',239),('episode_initial_cash_per_symbol',100000),('max_joint_histories',4097)]:
            changed=copy.deepcopy(SPEC);changed[key]=value
            with self.assertRaises(ValueError): draft.simulate(data,btc,candles,features,draft.CANDIDATES[0],changed,40,SPEC['gap_target_models'][0])

    def test_full_shared_pipeline_500_controls_each_and_fixed_bootstrap(self):
        # Calendar adaptation is confined to this synthetic fixture, not draft config.
        spec=copy.deepcopy(SPEC)
        if not FULL_PROOF:
            spec['placebo_replicates']=3
            spec['bootstrap_replicates']=64
        spec['data_start']='2020-01-01T00:00:00Z'
        spec['data_end_exclusive']='2020-04-30T00:00:00Z'
        for kind,candidate in zip(('quickstart','updown'),draft.CANDIDATES,strict=True):
            fixture=FIXTURES[kind+'_prefix_future_baseline']
            state,data,btc,candles,features=run_fixture(kind,fixture)
            panel={s:data for s in spec['symbols']};panel[spec['benchmark']]=btc
            frames={s:candles for s in spec['symbols']};frames[spec['benchmark']]=draft.shared.bars8h(btc)
            allfeatures={s:features for s in spec['symbols']}
            evaluated=draft.evaluate_candidate(candidate,panel,frames,allfeatures,spec,output_progress=lambda *a,**k:None)
            control=evaluated['randomized_entry_control']
            self.assertEqual(control['replicates'],500 if FULL_PROOF else 3)
            self.assertFalse(control['endogenous_durations_reused'])
            self.assertEqual(len(evaluated['cost_and_gap_cases']),8)
            self.assertEqual(len(evaluated['seven_bar_lag_control']),2)
            for cost in spec['cost_cases_bps']:
                left=evaluated['cost_and_gap_cases'][f"{cost}:{spec['gap_target_models'][0]}"]
                right=evaluated['cost_and_gap_cases'][f"{cost}:{spec['gap_target_models'][1]}"]
                self.assertEqual(left,right)
                bootstrap=left['joint_histories'][0]['diagnostics']['bootstrap']
                self.assertEqual(bootstrap['replicates'],2000 if FULL_PROOF else 64)
                self.assertEqual(bootstrap['moving_calendar_block_weeks'],4)
                self.assertEqual(bootstrap['alpha_per_candidate'],.025)
                self.assertTrue(bootstrap['descriptive_only'])
            self.assertFalse(evaluated['viable'])
        RESIDUALS['full_pipeline_candidates']=2
        RESIDUALS['full_pipeline_placebo_repetitions_per_candidate']=500 if FULL_PROOF else 3
        RESIDUALS['full_pipeline_bootstrap_replicates_per_case']=2000 if FULL_PROOF else 64

    def test_exact_zero_and_any_negative_btc_rounding_abort_without_clamp(self):
        self.assertEqual(draft.debit(125.25,1.,125.,.002),0.)
        self.assertLess(draft.debit(math.nextafter(125.25,-math.inf),1.,125.,.002),0.)
        fixture=FIXTURES['quickstart_origin_comparison']
        original=draft.debit
        for rejected_btc_debit in (-1e-15,-math.inf,math.nan):
            calls=[]
            def boundary(cash,quantity,price,side):
                calls.append((cash,quantity,price,side))
                return rejected_btc_debit if len(calls)==3 else original(cash,quantity,price,side)
            with patch.object(draft,'debit',side_effect=boundary):
                with self.assertRaisesRegex(ValueError,'funded BTC reference margin'):
                    run_fixture('quickstart',fixture)
            self.assertEqual(len(calls),3) # no sourcefill, no clamp or benchmark-only continuation
        # Concrete independently supplied representable boundary, without mocks.
        price=9990.009990009989
        btc_price=1.0884333495915535
        self.assertEqual(draft.debit(10000.,1.,price,.001),1.4690471061840071e-12)
        bq=10000.*(price/10000.)/btc_price
        self.assertEqual(draft.debit(10000.,bq,btc_price,.001),-3.517186542012496e-13)
        fixture=copy.deepcopy(FIXTURES['quickstart_origin_comparison'])
        fixture['opens'][240]=price
        btc=minutes(np.full(len(fixture['opens']),btc_price),np.full(len(fixture['opens']),btc_price))
        with self.assertRaisesRegex(ValueError,'funded BTC reference margin'):
            run_fixture('quickstart',fixture,cost=20,btc=btc)
        RESIDUALS['unmocked_btc_negative_rounding_abort_verified']=True

    def test_shared_unchanged_gates_cap_and_registered_counts(self):
        self.assertEqual(SPEC['max_symbol_histories'],64);self.assertEqual(SPEC['max_joint_histories'],4096)
        baseline=json.loads((REPO/'config/public_emv_batch17_v1.json').read_text())
        self.assertEqual(SPEC['gates'],baseline['gates'])
        self.assertEqual(SPEC['placebo_replicates'],500);self.assertEqual(SPEC['bootstrap_replicates'],2000)
        self.assertEqual(SPEC['new_registered_trading_cells'],2)
        self.assertEqual(SPEC['minimum_attempted_trading_cells'],30)
        self.assertEqual(SPEC['minimum_attempted_signal_model_cells'],31)
        self.assertEqual(len(draft.shared.CANDIDATES),2) # frozen alpha .05/2 == .025



    def test_pre_outcome_review_forgery_and_uncommitted_receipt_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = copy.deepcopy(SPEC)
            spec['required_pre_outcome_review']['path'] = 'review.json'
            path = root / 'review.json'
            evaluator = root / 'evaluator.py'
            evaluator.write_bytes(b'# synthetic provenance fixture\n')
            receipt = dict(status=spec['required_pre_outcome_review']['required_status'],
                           blocking_findings=[], market_outcomes_inspected=False,
                           evaluator_exact_sha256='wrong',
                           canonical_config_sha256=draft.shared.digest(spec))
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_PRE_OUTCOME_REVIEW_BINDING_FAILED'):
                draft.require_pre_outcome_review(root, spec, evaluator)
            receipt['evaluator_exact_sha256'] = draft.shared.sha(evaluator)
            receipt['market_outcomes_inspected'] = True
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_PRE_OUTCOME_REVIEW_BINDING_FAILED'):
                draft.require_pre_outcome_review(root, spec, evaluator)
            receipt['market_outcomes_inspected'] = False
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'commit independent review before outcomes'):
                draft.require_pre_outcome_review(root, spec, evaluator)


if __name__ == '__main__':
    unittest.main()

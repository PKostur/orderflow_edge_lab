from __future__ import annotations

import copy
import json
import math
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from orderflow_edge_lab import btc_relative_state as study
from orderflow_edge_lab.public_strategy_shadow import Bar, iso, utc

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'config/public_btc_relative_state_v1.json'


def frames(days=240):
    start = utc('2020-01-01T00:00:00Z')
    result = {}
    for k, symbol in enumerate((study.BENCHMARK, *study.SYMBOLS)):
        bars = []
        for i in range(days * 3):
            price = 100 * math.exp(.0001 * i + .01 * math.sin(i / 13 + k))
            bars.append(Bar(start + i * study.STEP, price, price * 1.02, price * .98, price * 1.001, 10))
        result[symbol] = bars
    return result


def fixture_rows(weeks=160):
    start = utc('2023-01-02T00:00:00Z')
    rows = []
    for i in range(weeks):
        t = start + i * study.WEEK
        for s in study.SYMBOLS:
            target = 100 if i % 2 else -100
            rows.append({'symbol': s, 'forecast_time': iso(t), 'year': t.year, 'target_bps': target,
                         'baseline_bps': 0., 'extended_bps': target * .9, 'delayed_bps': -target * .9})
    return rows


class BTCRelativeStateTests(unittest.TestCase):
    def test_beta_and_strength_known_intercept(self):
        x = .001 + .004 * np.sin(np.arange(90))
        daily = np.column_stack((100 * np.exp(np.r_[0, np.cumsum(x)]),
                                 100 * np.exp(np.r_[0, np.cumsum(2 * x + .0003)])))
        beta, btc30, strength = study.strength(daily)
        self.assertAlmostEqual(beta, 2, places=10)
        self.assertAlmostEqual(btc30, x[-30:].sum())
        self.assertAlmostEqual(strength, .009)
        with self.assertRaisesRegex(ValueError, 'variance'):
            study.strength(np.ones((91, 2)))
        with self.assertRaises(ValueError):
            study.strength(np.full((91, 2), np.nan))

    def test_grid_and_feature_clock_future_prices(self):
        data = frames()
        weeks = study.weekly_observations(data)
        row = weeks[0][0]
        self.assertEqual(utc(row['entry_time']) - utc(row['forecast_time']), study.STEP)
        self.assertEqual(utc(row['exit_time']) - utc(row['entry_time']), study.WEEK)
        changed = copy.deepcopy(data)
        for s in changed:
            changed[s] = [replace(b, close=b.close * 2) if b.timestamp >= utc(row['forecast_time']) else b for b in changed[s]]
        after = study.weekly_observations(changed)[0][0]
        self.assertEqual(study.xrow(row, row['strength30']), study.xrow(after, after['strength30']))
        changed = copy.deepcopy(data)
        changed[study.BENCHMARK].pop(10)
        with self.assertRaisesRegex(ValueError, 'grid'):
            study.weekly_observations(changed)

    def test_rolling_window_scaler_and_future_label_isolation(self):
        weeks = study.weekly_observations(frames(200))
        out, records = study.rolling_forecasts(weeks, training_weeks=4)
        first = records[0]
        self.assertEqual(first['training_rows'], 12)
        self.assertEqual(first['training_first_forecast'], weeks[0][0]['forecast_time'])
        self.assertEqual(first['training_last_forecast'], weeks[3][0]['forecast_time'])
        self.assertLess(utc(first['latest_training_label_completed_at']), utc(first['forecast_time']))
        expected = np.mean([study.xrow(r) for week in weeks[:4] for r in week], axis=0)
        np.testing.assert_allclose(first['models'][0]['scaler_mean'], expected)
        self.assertIsNone(out[0]['delayed_bps'])
        self.assertIsNotNone(out[3]['delayed_bps'])
        changed = copy.deepcopy(weeks)
        for week in changed[4:]:
            for r in week:
                r['target_bps'] += 100000
        out2, records2 = study.rolling_forecasts(changed, training_weeks=4)
        self.assertEqual(out[0]['extended_bps'], out2[0]['extended_bps'])
        self.assertEqual(records[0], records2[0])

    def test_pairing_and_state_failure_does_not_run_economics(self):
        spec = json.loads(SPEC.read_text())
        rows = fixture_rows()
        for r in rows:
            r['extended_bps'] = r['baseline_bps']
        with patch.object(study, 'economic_assessment', side_effect=AssertionError('must not run')):
            report, trades, curves = study.analyze(rows, {}, spec)
        self.assertEqual(report['disposition'], 'REJECTED_AS_SPECIFIED')
        self.assertEqual(report['economics']['status'], 'NOT_RUN')
        self.assertIsNone(report['trade_count'])
        self.assertEqual(trades, [])
        self.assertEqual(curves, {})
        bad = copy.deepcopy(rows)
        bad[0]['symbol'] = 'SOL_USDT'
        with self.assertRaises(ValueError):
            study.uncertainty(bad)

    def test_state_success_advances_once_and_noise_fails(self):
        spec = json.loads(SPEC.read_text())
        rows = fixture_rows()
        self.assertTrue(study.state_assessment(rows, spec)['passed'])
        with patch.object(study, 'economic_assessment', return_value=({'status': 'RUN', 'passed': False}, [], {})) as economic:
            report, _, _ = study.analyze(rows, {}, spec)
            economic.assert_called_once()
        self.assertEqual(report['disposition'], 'REJECTED_AS_SPECIFIED')
        for r in rows:
            r['extended_bps'] = -r['target_bps']
        self.assertFalse(study.state_assessment(rows, spec)['passed'])

    def test_controls_keep_symbols_and_short_tail(self):
        rows = fixture_rows(9)
        a = study.placebo_controls(rows, replicates=20)
        self.assertEqual(a, study.placebo_controls(rows, replicates=20))
        self.assertEqual(a['fixed_tail_weeks_by_year'], {'2023': 1})
        self.assertFalse(a['formal_p_value'])
        result = study.uncertainty(rows, replicates=50)
        self.assertEqual(result['valid'], 50)
        self.assertAlmostEqual(result['descriptive_99pct_mse_reduction_interval'][0], .99)

    def test_multiplicative_cost_cash_and_btc_schedule(self):
        data = frames(20)
        cohort = []
        for i in (1, 22):
            for s in study.SYMBOLS:
                cohort.append({'symbol': s, 'entry_index': i, 'exit_index': i + 21})
        selected = [cohort[0], cohort[3]]  # Same sleeve closes and reopens.
        cost = 60
        factor = (1 - cost / 20000) ** 2
        p = study.portfolio(selected, cohort, data, cost)
        expected = data['ETH_USDT'][43].open / data['ETH_USDT'][1].open * factor ** 2
        self.assertAlmostEqual(p['return_pct'], ((expected + 2) / 3 - 1) * 100)
        btc = study.portfolio(selected, cohort, data, cost, btc=True)
        expected_btc = data[study.BENCHMARK][43].open / data[study.BENCHMARK][1].open * factor ** 2
        self.assertAlmostEqual(btc['return_pct'], ((expected_btc + 2) / 3 - 1) * 100)
        self.assertEqual(study.portfolio([], cohort, data, cost)['return_pct'], 0)
        self.assertAlmostEqual(study.net_bps(100, 60), (1.01 * factor - 1) * 10000)

    def test_excursions_exclude_exit_and_pre_mfe_order(self):
        data = frames(20)
        row = {'symbol': 'ETH_USDT', 'entry_index': 1, 'exit_index': 22}
        data['ETH_USDT'][22] = replace(data['ETH_USDT'][22], high=100000, low=.00001)
        result = study.excursions(row, data)
        self.assertEqual(result['held_bars'], 21)
        self.assertLess(result['mfe_bps'], 1000)
        self.assertGreater(result['mae_bps'], -1000)
        self.assertFalse(result['intrabar_order_known'])

    def test_committed_spec_and_source_hash_guard(self):
        # Read-only real provenance test, no predictor or outcomes evaluated.
        # HEAD is present even in a shallow CI checkout. The research CLI uses
        # the original immutable design commit, documented in the study report.
        design = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        spec, data, identity = study.load_verified(ROOT, SPEC, design)
        self.assertEqual(len(data[study.BENCHMARK]), 6726)
        self.assertEqual(identity['design_commit'], design)
        self.assertEqual(spec['study_id'], 'PSR4-BTC-RELATIVE-STRENGTH')
        with patch.object(study, 'sha256_file', return_value='bad'):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                study.load_verified(ROOT, SPEC, design)
        with patch.object(study.subprocess, 'check_output', side_effect=[design, b'{}']):
            with self.assertRaisesRegex(ValueError, 'specification differs'):
                study.load_verified(ROOT, SPEC, design)

    def test_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            study.write_json(path, {'status': 'NOT_RUN'})
            with self.assertRaises(FileExistsError):
                study.write_json(path, {})


if __name__ == '__main__':
    unittest.main()

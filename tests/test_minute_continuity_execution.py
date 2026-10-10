import io
import hashlib
import csv
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

from orderflow_edge_lab import minute_continuity_execution as audit
from orderflow_edge_lab.public_strategy_shadow import utc, iso

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / 'config/minute_continuity_execution_v1.json').read_text())


def monthly_zip(month='2024-02', skip=None, mutation=None):
    start, count = audit.month_bounds(month)
    scale = 1_000_000 if month >= '2025-01' else 1000
    lines = []
    for i in range(count):
        if i == skip:
            continue
        row = [(start + i * 60) * scale, 100, 101, 99, 100, 5,
               (start + (i + 1) * 60) * scale - 1, 500, 10, 2, 200, 0]
        if mutation and i == 10:
            row = mutation(row)
        lines.append(','.join(map(str, row)))
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'BTCUSDT-1m-{month}.csv', '\n'.join(lines))
    return output.getvalue()


def complete_daily(spec):
    start, end = utc(spec['start_utc']), utc(spec['end_exclusive_utc'])
    return [{'day': iso(start + timedelta(days=i))[:10], 'symbol': s, 'complete_day': True}
            for i in range((end - start).days) for s in audit.SYMBOLS]


class MinuteContinuityTests(unittest.TestCase):
    def audit(self, payload, month='2024-02'):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'month.zip'
            path.write_bytes(payload)
            return audit.audit_archive(path, 'BTCUSDT', month)

    def test_calendar_counts_and_leap_day(self):
        months = audit.months_between(SPEC['start_utc'], SPEC['end_exclusive_utc'])
        self.assertEqual(len(months), 69)
        self.assertEqual(sum(audit.month_bounds(m)[1] for m in months), 3022560)
        self.assertEqual(audit.month_bounds('2024-02')[1], 29 * 1440)
        with self.assertRaises(ValueError):
            audit.months_between('2024-01-02T00:00:00Z', '2024-02-01T00:00:00Z')

    def test_complete_grid_and_microsecond_transition(self):
        for month in ('2024-02', '2025-01'):
            result = self.audit(monthly_zip(month), month)
            self.assertTrue(result['complete_month'])
            self.assertEqual(result['missing_minutes'], 0)
            self.assertTrue(all(d['complete_day'] for d in result['daily']))
        bad = monthly_zip('2025-01', mutation=lambda r: [r[0] // 1000, *r[1:6], r[6] // 1000, *r[7:]])
        with self.assertRaisesRegex(ValueError, 'timestamp_units'):
            self.audit(bad, '2025-01')

    def test_missing_minute_is_retained_gap_not_filled(self):
        result = self.audit(monthly_zip(skip=1440))
        self.assertFalse(result['complete_month'])
        self.assertEqual(result['observed_minutes'], 29 * 1440 - 1)
        self.assertEqual(result['gaps'][0]['start_utc'], '2024-02-02T00:00:00Z')
        self.assertEqual(result['missing_minutes'], 1)
        self.assertFalse(result['daily'][1]['complete_day'])
        self.assertTrue(result['daily'][0]['complete_day'])

    def test_duplicate_nonfinite_and_impossible_taker_reject(self):
        def duplicate(r):
            r[0] -= 60000
            r[6] -= 60000
            return r
        def nonfinite(r):
            r[5] = float('nan')
            return r
        def taker(r):
            r[9] = 6
            return r
        for mutation, category in ((duplicate, 'duplicate'), (nonfinite, 'ohlcv'), (taker, 'ohlcv')):
            with self.assertRaisesRegex(ValueError, category):
                self.audit(monthly_zip(mutation=mutation))

    def test_all_symbols_share_full_weeks_and_partial_boundaries_excluded(self):
        daily = complete_daily(SPEC)
        full = audit.complete_panel_weeks(daily, SPEC)
        self.assertEqual(len(full), 299)
        self.assertEqual(full[0], '2021-01-04')
        for row in daily:
            if row['day'] == '2021-01-05' and row['symbol'] == 'LINKUSDT':
                row['complete_day'] = False
        self.assertEqual(len(audit.complete_panel_weeks(daily, SPEC)), 298)
        self.assertEqual(audit.complete_panel_weeks(daily, SPEC)[0], '2021-01-11')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            audit.complete_panel_weeks(daily + [daily[0]], SPEC)

    def test_power_never_claims_independence_or_adequacy_from_candle_counts(self):
        result = audit.planning_power(299, SPEC)
        self.assertEqual(result['independent_week_requirement'], 161)
        self.assertEqual(result['inflated_calendar_week_requirement'], 644)
        self.assertTrue(result['optimistic_independent_count_sufficient'])
        self.assertFalse(result['four_week_inflated_count_sufficient'])
        self.assertFalse(result['adequate_power_established'])
        self.assertIsNone(result['observed_paired_loss_variance'])

    def test_complete_sources_still_block_execution_and_dependent_power(self):
        records = [{'symbol': s, 'month': m, 'status': 'VERIFIED_COMPLETE', 'checksum_verified': True,
                    'expected_minutes': audit.month_bounds(m)[1],
                    'observed_minutes': audit.month_bounds(m)[1], 'missing_minutes': 0}
                   for m in audit.months_between(SPEC['start_utc'], SPEC['end_exclusive_utc']) for s in audit.SYMBOLS]
        result = audit.final_assessment(records, complete_daily(SPEC), [], SPEC)
        self.assertTrue(result['source_complete_continuous_panel'])
        self.assertFalse(result['research_readiness'])
        self.assertFalse(result['historical_execution_calibrated'])
        self.assertEqual([s['roundtrip_cost_bps'] for s in result['cost_scenarios_assumptions_only']], [20, 40, 60])
        self.assertIsNone(result['trade_count'])
        self.assertEqual(result['new_trading_cells'], 0)
        self.assertEqual(result['prediction'], 'NOT_DESIGNED_NOT_RUN')
        records[0]['status'] = 'SOURCE_FAILED'
        blocked = audit.final_assessment(records, complete_daily(SPEC), [], SPEC)
        self.assertIn('continuous_source_panel_failed', blocked['blocking_reasons'])

    def test_checksum_access_failure_retains_archive_and_safe_resume(self):
        payload = monthly_zip()
        name = 'BTCUSDT-1m-2024-02.zip'
        checksum = (hashlib.sha256(payload).hexdigest() + ' ' + name).encode()
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            with patch.object(audit, 'request_bytes', side_effect=[payload, OSError('checksum unavailable')]):
                record, _ = audit.source_task(raw, 'BTCUSDT', '2024-02')
            self.assertEqual(record['status'], 'SOURCE_FAILED')
            self.assertEqual((raw / name).read_bytes(), payload)
            receipt = (raw / (name + '.receipt.json')).read_bytes()
            with patch.object(audit, 'request_bytes', return_value=checksum) as fetch:
                record, _ = audit.source_task(raw, 'BTCUSDT', '2024-02')
                self.assertEqual(fetch.call_count, 1)
            self.assertEqual(record['status'], 'VERIFIED_COMPLETE')
            self.assertEqual((raw / (name + '.receipt.json')).read_bytes(), receipt)
            with patch.object(audit, 'request_bytes', side_effect=AssertionError('no refetch')):
                repeated, _ = audit.source_task(raw, 'BTCUSDT', '2024-02')
            self.assertEqual(repeated, record)
            (raw / name).write_bytes(b'tampered')
            with patch.object(audit, 'request_bytes', side_effect=AssertionError('no substitution')):
                tampered, _ = audit.source_task(raw, 'BTCUSDT', '2024-02')
            self.assertEqual(tampered['status'], 'SOURCE_FAILED')

    def test_prefix_probes_preserve_rerun_and_invalid_response_bytes(self):
        class Response(io.BytesIO):
            status = 200
        prefix = 'data/spot/monthly/bookDepth/BTCUSDT/'
        payload = ('<ListBucketResult><Prefix>' + prefix + '</Prefix><IsTruncated>false</IsTruncated></ListBucketResult>').encode()
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            with patch.object(audit.urllib.request, 'urlopen', side_effect=lambda *a, **kw: Response(payload)), patch.object(audit, 'datetime') as clock:
                # Windows can report identical microsecond timestamps for consecutive calls.
                clock.now.return_value = audit.utc('2026-10-10T00:00:00Z')
                a = audit.execution_prefix_probe(raw, 'bookDepth', 'BTCUSDT', 'https://example.invalid')
                b = audit.execution_prefix_probe(raw, 'bookDepth', 'BTCUSDT', 'https://example.invalid')
            self.assertEqual(a['status'], 'NO_OBJECTS_AT_PROBED_PREFIX')
            self.assertNotEqual(a['raw_relative_path'], b['raw_relative_path'])
            self.assertEqual((raw / a['raw_relative_path']).read_bytes(), payload)
            with patch.object(audit.urllib.request, 'urlopen', return_value=Response(b'<html>unexpected</html>')):
                invalid = audit.execution_prefix_probe(raw, 'bookDepth', 'BTCUSDT', 'https://example.invalid')
            self.assertEqual(invalid['status'], 'PREFIX_ACCESS_UNCONFIRMED')
            self.assertEqual((raw / invalid['raw_relative_path']).read_bytes(), b'<html>unexpected</html>')

    def test_retained_report_hashes_quality_totals_and_claim_boundaries(self):
        folder = ROOT / 'artifacts/minute_continuity_20261010'
        report = json.loads((folder / 'report.json').read_text())
        for name, digest in report['output_sha256'].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(report['spec_sha256'], hashlib.sha256((ROOT / 'config/minute_continuity_execution_v1.json').read_bytes()).hexdigest())
        self.assertEqual(report['design_commit'], '1f05a9c2e93d9f26b908ee9faeb00def487e8f52')
        self.assertEqual(report['implementation_sha256'], hashlib.sha256((ROOT / 'src/orderflow_edge_lab/minute_continuity_execution.py').read_bytes()).hexdigest())
        records = json.loads((folder / 'source_manifest.json').read_text())
        with (folder / 'daily_quality.csv').open(newline='', encoding='utf-8') as stream:
            daily = list(csv.DictReader(stream))
        for row in daily:
            self.assertIn(row['complete_day'], ('True', 'False'))
            row['complete_day'] = row['complete_day'] == 'True'
            for key in ('observed_minutes', 'missing_minutes', 'zero_trade_minutes', 'zero_volume_minutes'):
                row[key] = int(row[key]) if row[key] else None
        derived = audit.final_assessment(records, daily, report['execution_prefix_probes'], SPEC)
        for key, value in derived.items():
            self.assertEqual(report[key], value, key)
        observed, missing, unknown_slots = 0, 0, 0
        for record in records:
            if record['checksum_verified']:
                self.assertLessEqual(utc(record['request_utc']), utc(record['receipt_utc']))
                self.assertLessEqual(utc(record['receipt_utc']), utc(record['checksum_request_utc']))
                self.assertLessEqual(utc(record['checksum_request_utc']), utc(record['checksum_receipt_utc']))
            rows = [d for d in daily if d['symbol'] == record['symbol'] and d['day'].startswith(record['month'])]
            if record['status'] == 'SOURCE_FAILED':
                self.assertTrue(all(d['observed_minutes'] is None and not d['complete_day'] for d in rows))
                unknown_slots += audit.month_bounds(record['month'])[1]
            else:
                self.assertEqual(sum(d['observed_minutes'] for d in rows), record['observed_minutes'])
                self.assertEqual(sum(d['missing_minutes'] for d in rows), record['missing_minutes'])
                observed += record['observed_minutes']
                missing += record['missing_minutes']
        self.assertEqual(observed + missing + unknown_slots, SPEC['expected_panel_candles'])
        self.assertFalse(report['research_readiness'])
        self.assertFalse(report['verified_out_of_sample_evidence'])
        self.assertFalse(report['order_transmission_supported'])
        self.assertIsNone(report['trade_count'])


if __name__ == '__main__':
    unittest.main()

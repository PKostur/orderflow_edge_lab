import copy
import hashlib
import io
import json
import math
import unittest
import zipfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np

from orderflow_edge_lab import public_research_extensions as research
from orderflow_edge_lab.public_strategy_shadow import Bar, iso, utc

ROOT = Path(__file__).resolve().parents[1]


def frames(days=70):
    start = utc('2021-01-01T00:00:00Z')
    out = {}
    for k, s in enumerate(research.ALL):
        out[s] = []
        for i in range(days * 3):
            price = 100 * math.exp(.001 * math.sin(i / 7 + k))
            close = price * math.exp(.001 * (1 + math.sin(i / 5)))
            out[s].append(Bar(start + i * research.STEP, price, max(price, close) * 1.01,
                              min(price, close) * .99, close, 100 + i))
    return out


def archive(day, count=1440, unit=None):
    scale = unit or (1_000_000 if day >= '2025-01-01' else 1000)
    start = int(utc(day + 'T00:00:00Z').timestamp())
    rows = []
    for i in range(count):
        rows.append(','.join(map(str, [(start + i * 60) * scale, 100, 102, 99, 101, 5,
                                      (start + (i + 1) * 60) * scale - 1, 505, 10, 2, 202, 0])))
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('sample.csv', '\n'.join(rows))
    return output.getvalue()


class ResearchExtensionTests(unittest.TestCase):
    def test_volume_features_and_target_clock(self):
        data = frames()
        days = research.volume_observations(data)
        row = days[0][0]
        t = utc(row['forecast_time'])
        self.assertEqual(t, utc('2021-01-31T00:00:00Z'))
        self.assertEqual(utc(row['target_start']), t + research.STEP)
        self.assertEqual(utc(row['target_end']), t + research.DAY + research.STEP)
        changed = copy.deepcopy(data)
        for s in changed:
            changed[s] = [replace(b, close=b.close * 1.005, high=b.high * 1.01, volume=b.volume * 4)
                          if b.timestamp >= t else b for b in changed[s]]
        after = research.volume_observations(changed)[0][0]
        self.assertEqual(row['x'], after['x'])
        self.assertEqual(row['volume_log_ratio'], after['volume_log_ratio'])
        self.assertNotEqual(row['target'], after['target'])
        held = data[row['symbol']][91:94]
        self.assertAlmostEqual(row['target'], math.log(sum(math.log(b.close / b.open) ** 2 for b in held) + 1e-12))

    def test_no_gaps_or_turnover_imputation(self):
        data = frames()
        data['ETH_USDT'].pop(20)
        with self.assertRaisesRegex(ValueError, 'grids'):
            research.volume_observations(data)
        data = frames()
        data['ETH_USDT'][:3] = [replace(b, volume=0) for b in data['ETH_USDT'][:3]]
        with self.assertRaisesRegex(ValueError, 'turnover'):
            research.volume_observations(data)

    def test_training_only_scaler_and_unavailable_day_label(self):
        days = research.volume_observations(frames())
        rows, models = research.volume_forecasts(days, training_days=5)
        self.assertEqual(models[0]['training_rows'], 15)
        self.assertEqual(models[0]['last_training_forecast'], days[4][0]['forecast_time'])
        self.assertLess(utc(models[0]['latest_training_label_end']), utc(models[0]['forecast_time']))
        expected = np.mean([r['x'] for d in days[:5] for r in d], axis=0)
        np.testing.assert_allclose(expected, models[0]['models'][0]['scaler_mean'])
        changed = copy.deepcopy(days)
        for d in changed[5:]:
            for r in d:
                r['target'] += 1000
        other, _ = research.volume_forecasts(changed, training_days=5)
        self.assertEqual(rows[0]['extended'], other[0]['extended'])
        self.assertIsNone(rows[0]['delayed'])
        self.assertIsNotNone(rows[3]['delayed'])

    def test_archive_units_and_complete_grid(self):
        for day in ('2024-01-01', '2025-01-01'):
            parsed = research.decode_archive(archive(day), day)
            self.assertEqual(len(parsed), 1440)
            self.assertEqual(parsed[-1]['time_s'] - parsed[0]['time_s'], 1439 * 60)
        with self.assertRaisesRegex(ValueError, '1440'):
            research.decode_archive(archive('2024-01-01', count=1439), '2024-01-01')
        with self.assertRaisesRegex(ValueError, 'units'):
            research.decode_archive(archive('2025-01-01', unit=1000), '2025-01-01')

    def test_book_walk_both_sides_and_depth_gate(self):
        result = research.walk_book({'asks': [['101', '20']], 'bids': [['100', '20']]})
        self.assertAlmostEqual(result['loss_excluding_fees_bps'], (1 - 100 / 101) * 10000)
        self.assertEqual(research.walk_book({'asks': [['101', '1']], 'bids': [['100', '20']]})['insufficient_side'], 'asks')
        self.assertEqual(research.walk_book({'asks': [['101', '20']], 'bids': [['100', '1']]})['insufficient_side'], 'bids')
        with self.assertRaisesRegex(ValueError, 'crossed'):
            research.walk_book({'asks': [['100', '20']], 'bids': [['101', '20']]})
        with self.assertRaises(ValueError):
            research.walk_book({'asks': [['101', '5'], ['101', '5']], 'bids': [['100', '20']]})

    def test_checksum_rejects_empty_wrong_name_and_content(self):
        payload = b'archive'
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(research.validate_checksum(payload, (digest + ' file.zip').encode(), 'file.zip'), digest)
        for invalid in (b'', b'bad file.zip', (digest + ' wrong.zip').encode(), ('0' * 64 + ' file.zip').encode()):
            with self.assertRaises(ValueError):
                research.validate_checksum(payload, invalid, 'file.zip')

    def test_null_feature_rejected_without_trading(self):
        rows = []
        t = utc('2023-01-01T00:00:00Z')
        for d in range(800):
            date = t + timedelta(days=d)
            week = iso(date - timedelta(days=date.weekday()))
            for s in research.SYMBOLS:
                rows.append({'symbol': s, 'forecast_time': iso(date), 'year': date.year, 'week': week,
                             'target': 1 if d % 2 else -1, 'baseline': 0, 'extended': 0, 'delayed': 0})
        result = research.volume_analysis(rows)
        self.assertEqual(result['disposition'], 'REJECTED_AS_SPECIFIED')
        self.assertEqual(result['economics'], 'NOT_DESIGNED_NOT_RUN')
        self.assertIsNone(result['trade_count'])

    def test_committed_design_has_no_trading_cells(self):
        spec = json.loads((ROOT / 'config/public_research_extensions_v1.json').read_text())
        self.assertEqual(len(spec['minute']['dates']), 12)
        self.assertFalse(spec['order_transmission_supported'])
        self.assertEqual(spec['trial_accounting']['new_trading_cells'], 0)


if __name__ == '__main__':
    unittest.main()

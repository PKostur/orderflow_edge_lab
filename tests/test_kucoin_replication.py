import hashlib
import json
import unittest
from pathlib import Path

from scripts.collect_public_kucoin_8h import validate
from orderflow_edge_lab.kucoin_replication import book_cost


class KucoinReplicationTests(unittest.TestCase):
    def test_grid_rejects_missing_duplicate_and_non_utc(self):
        row = ['0', '10', '11', '12', '9', '1', '10']
        self.assertEqual(validate([row], 0, 28800), [row])
        for rows in ([], [row, row], [['1', *row[1:]]]):
            with self.assertRaises(ValueError):
                validate(rows, 0, 28800)

    def test_invalid_ohlcv_rejected(self):
        for close in ('13', 'nan'):
            with self.assertRaises(ValueError):
                validate([['0', '10', close, '12', '9', '1', '10']], 0, 28800)

    def test_depth_walk_includes_spread_once(self):
        book = {'time': 0, 'asks': [['101', '100']], 'bids': [['100', '100']]}
        self.assertAlmostEqual(book_cost(book)['displayed_buy_then_sell_loss_bps_excluding_fees'], (1 - 100 / 101) * 10000)
        with self.assertRaises(ValueError):
            book_cost({'time': 0, 'asks': [['101', '1']], 'bids': [['100', '1']]})

    def test_committed_source_bytes_match_manifest(self):
        root = Path(__file__).resolve().parents[1]
        folder = root / 'artifacts/public_kucoin_8h_20261010'
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertTrue(manifest['complete'])
        for request in manifest['requests']:
            self.assertEqual(hashlib.sha256((folder / 'raw' / request['file']).read_bytes()).hexdigest(), request['sha256'])
        for symbol, meta in manifest['symbols'].items():
            self.assertEqual(meta['bars'], 5649)
            self.assertEqual(hashlib.sha256((folder / 'aligned_csv' / (symbol.replace('-', '_') + '.csv')).read_bytes()).hexdigest(), meta['csv_sha256'])

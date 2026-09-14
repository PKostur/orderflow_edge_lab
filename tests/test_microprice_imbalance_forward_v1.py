import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_microprice_imbalance_forward_v1.py"
spec = importlib.util.spec_from_file_location("microprice_forward_v1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class MicropriceImbalanceForwardV1Tests(unittest.TestCase):
    def _write_features(self, path: Path) -> None:
        rows = []
        symbols = ["ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT"]
        for s_idx, symbol in enumerate(symbols):
            base = 100.0 + s_idx
            for sec in range(180):
                drift = 0.001 * sec
                bid = base + drift
                ask = bid + 0.02
                mid = (bid + ask) / 2.0
                pressure = ((sec % 20) - 10) / 10.0
                micro = mid + pressure * 0.003
                rows.append({
                    "feature_schema_version": 2,
                    "event_type": "depth",
                    "symbol": symbol,
                    "exchange_ts_ms": 1_800_000_000_000 + sec * 1000,
                    "best_bid": bid,
                    "best_ask": ask,
                    "microprice": micro,
                    "book_imbalance_10": pressure,
                })
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def test_batch_and_aggregate_keep_pnl_closed_before_six_batches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            features = root / "features.jsonl"
            batch = root / "batch.json"
            aggregate = root / "aggregate.json"
            self._write_features(features)
            module.run_batch(features, "batch-1", batch, epochs=20)
            payload = json.loads(batch.read_text(encoding="utf-8"))
            self.assertFalse(payload["claims"]["strategy_pnl_inspected"])
            self.assertEqual(len(payload["state_metrics"]), 8)
            module.run_aggregate([batch], aggregate)
            result = json.loads(aggregate.read_text(encoding="utf-8"))
            self.assertEqual(result["independent_batches_seen"], 1)
            self.assertEqual(result["state_passes"], 0)
            self.assertFalse(result["strategy_pnl_layer_open"])

    def test_same_second_events_collapse_to_one_sample_per_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            features = root / "features.jsonl"
            self._write_features(features)
            rows = module._read_features(features)
            counts = rows.groupby("symbol").size().tolist()
            self.assertTrue(counts)
            self.assertTrue(all(count == 180 for count in counts))


if __name__ == "__main__":
    unittest.main()

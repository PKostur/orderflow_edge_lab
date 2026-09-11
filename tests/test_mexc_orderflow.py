import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.mexc_orderflow import (
    AppendOnlyJsonl,
    FeatureEngine,
    MexcOrderFlowError,
    OrderBook,
    SequenceGapError,
    apply_recovery_commits,
    decode_ws_message,
)
from orderflow_edge_lab.cli.mexc_replay import replay


class MexcOrderFlowTests(unittest.TestCase):
    def snapshot(self, version=10):
        return {
            "success": True,
            "code": 0,
            "data": {
                "asks": [[101, 2, 4], [102, 1, 2]],
                "bids": [[100, 3, 6], [99, 1, 1]],
                "version": version,
                "timestamp": 1_780_000_000_000,
            },
        }

    def test_snapshot_uses_absolute_quantity_and_book_features(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        self.assertEqual(book.version, 10)
        self.assertEqual(book.best_bid()[0], 100)
        self.assertEqual(book.best_bid()[1], 6)
        self.assertEqual(book.best_ask()[0], 101)
        self.assertEqual(float(book.spread()), 1.0)
        self.assertAlmostEqual(float(book.microprice()), 100.6)
        self.assertAlmostEqual(float(book.imbalance(1)), 0.2)

    def test_contiguous_depth_update_tracks_adds_pulls_and_deletes(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        delta = book.apply_update(
            {
                "version": 11,
                "cts": 1_780_000_000_100,
                "bids": [[100, 4, 8], [99, 0, 0]],
                "asks": [[101, 1, 2], [102, 0, 0]],
            }
        )
        self.assertTrue(delta.applied)
        self.assertEqual(float(delta.bid_added), 2.0)
        self.assertEqual(float(delta.bid_pulled), 1.0)
        self.assertEqual(float(delta.ask_pulled), 4.0)
        self.assertEqual(float(delta.depth_flow_imbalance), 5.0)
        self.assertNotIn(99, book.bids)
        self.assertNotIn(102, book.asks)

    def test_gap_fails_before_mutating_book(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        with self.assertRaises(SequenceGapError):
            book.apply_update({"version": 12, "bids": [[100, 3, 8]], "asks": []})
        self.assertEqual(book.version, 10)
        self.assertEqual(book.best_bid()[1], 6)

    def test_crossed_update_rolls_back(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        with self.assertRaisesRegex(MexcOrderFlowError, "locked or crossed"):
            book.apply_update({"version": 11, "bids": [[101, 1, 1]], "asks": []})
        self.assertEqual(book.version, 10)
        self.assertNotIn(101, book.bids)

    def test_recovery_commits_are_sorted_by_version(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        payload = {
            "success": True,
            "code": 0,
            "data": [
                {"version": 12, "bids": [[100, 3, 8]], "asks": []},
                {"version": 11, "bids": [[100, 3, 7]], "asks": []},
            ],
        }
        self.assertEqual(apply_recovery_commits(book, payload), 2)
        self.assertEqual(book.version, 12)
        self.assertEqual(book.best_bid()[1], 8)

    def test_trade_stream_is_sorted_and_cvd_uses_exchange_side(self):
        engine = FeatureEngine(["ENA_USDT"], trade_window_ms=10_000, imbalance_levels=1)
        engine.load_snapshot("ENA_USDT", self.snapshot())
        features = engine.on_deals(
            "ENA_USDT",
            [
                {"p": 100, "v": 2, "T": 2, "t": 1001, "i": "2"},
                {"p": 100, "v": 5, "T": 1, "t": 1000, "i": "1"},
            ],
        )
        self.assertEqual([row["aggressor_side"] for row in features], ["BUY", "SELL"])
        self.assertEqual(features[-1]["rolling_buy_volume"], 5.0)
        self.assertEqual(features[-1]["rolling_sell_volume"], 2.0)
        self.assertEqual(features[-1]["rolling_cvd"], 3.0)

    def test_trade_timestamp_regression_fails_closed(self):
        engine = FeatureEngine(["ENA_USDT"])
        engine.load_snapshot("ENA_USDT", self.snapshot())
        engine.on_deals("ENA_USDT", [{"p": 100, "v": 1, "T": 1, "t": 1000}])
        with self.assertRaisesRegex(MexcOrderFlowError, "regression"):
            engine.on_deals("ENA_USDT", [{"p": 100, "v": 1, "T": 1, "t": 999}])

    def test_decode_supports_plain_and_gzip_json(self):
        payload = {"channel": "pong", "data": 123}
        text = json.dumps(payload)
        self.assertEqual(dict(decode_ws_message(text)), payload)
        self.assertEqual(dict(decode_ws_message(gzip.compress(text.encode()))), payload)

    def test_append_only_writer_refuses_overwrite_and_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "raw.jsonl"
            writer = AppendOnlyJsonl(path)
            writer.write({"a": 1})
            manifest = writer.close()
            self.assertEqual(manifest["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(path.with_name("raw.jsonl.manifest.json").exists())
            with self.assertRaises(FileExistsError):
                AppendOnlyJsonl(path)

    def test_replay_recovers_gap_from_recorded_commits(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw.jsonl"
            output = Path(td) / "features.jsonl"
            records = [
                {
                    "record_type": "session",
                    "schema_version": 1,
                    "symbols": ["ENA_USDT"],
                    "started_at_ns": 1,
                },
                {
                    "record_type": "rest_snapshot",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 10,
                    "payload": self.snapshot(),
                },
                {
                    "record_type": "ws_message",
                    "symbol": "ENA_USDT",
                    "channel": "push.depth",
                    "received_at_ns": 20,
                    "payload": {
                        "channel": "push.depth",
                        "symbol": "ENA_USDT",
                        "data": {"version": 12, "bids": [[100, 3, 8]], "asks": []},
                    },
                },
                {
                    "record_type": "rest_depth_commits",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 30,
                    "payload": {
                        "success": True,
                        "code": 0,
                        "data": [
                            {"version": 12, "bids": [[100, 3, 8]], "asks": []},
                            {"version": 11, "bids": [[100, 3, 7]], "asks": []},
                        ],
                    },
                },
                {
                    "record_type": "ws_message",
                    "symbol": "ENA_USDT",
                    "channel": "push.deal",
                    "received_at_ns": 40,
                    "payload": {
                        "channel": "push.deal",
                        "symbol": "ENA_USDT",
                        "data": [{"p": 100, "v": 2, "T": 1, "t": 1000, "i": "abc"}],
                    },
                },
            ]
            raw.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            emitted = replay(raw, output, trade_window_seconds=10.0, imbalance_levels=1)
            self.assertEqual(emitted, 3)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            recovered = [row for row in rows if row.get("replayed_after_recovery")]
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["book_version"], 12)
            trades = [row for row in rows if row.get("event_type") == "trade"]
            self.assertEqual(trades[0]["rolling_cvd"], 2.0)

    def test_replay_rejects_unresolved_gap(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw.jsonl"
            output = Path(td) / "features.jsonl"
            records = [
                {"record_type": "session", "schema_version": 1, "symbols": ["ENA_USDT"], "started_at_ns": 1},
                {
                    "record_type": "rest_snapshot",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 10,
                    "payload": self.snapshot(),
                },
                {
                    "record_type": "ws_message",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 20,
                    "payload": {
                        "channel": "push.depth",
                        "symbol": "ENA_USDT",
                        "data": {"version": 99, "bids": [], "asks": []},
                    },
                },
            ]
            raw.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            with self.assertRaisesRegex(MexcOrderFlowError, "unresolved"):
                replay(raw, output, trade_window_seconds=10.0, imbalance_levels=1)


if __name__ == "__main__":
    unittest.main()

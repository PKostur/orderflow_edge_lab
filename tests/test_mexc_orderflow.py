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
    depth_version_range,
)
from orderflow_edge_lab.cli.mexc_replay import replay


class MexcOrderFlowTests(unittest.TestCase):
    def snapshot(self, version=10):
        return {
            "success": True,
            "code": 0,
            "data": {
                # MEXC depth rows are [price, contract volume, order count].
                "asks": [[101, 4, 2], [102, 2, 1]],
                "bids": [[100, 6, 3], [99, 1, 1]],
                "version": version,
                "timestamp": 1_780_000_000_000,
            },
        }

    def test_snapshot_uses_contract_volume_not_order_count(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        self.assertEqual(book.version, 10)
        self.assertEqual(book.best_bid()[0], 100)
        self.assertEqual(book.best_bid()[1], 6)
        self.assertEqual(book.best_ask()[0], 101)
        self.assertEqual(book.best_ask()[1], 4)
        self.assertEqual(float(book.spread()), 1.0)
        self.assertAlmostEqual(float(book.microprice()), 100.6)
        self.assertAlmostEqual(float(book.imbalance(1)), 0.2)

    def test_depth_level_order_count_must_be_integral(self):
        bad = self.snapshot()
        bad["data"]["bids"] = [[100, 6, 1.5]]
        with self.assertRaisesRegex(MexcOrderFlowError, "nonnegative integer"):
            OrderBook("ENA_USDT").load_snapshot(bad)

    def test_contiguous_depth_update_tracks_contract_volume_adds_pulls_deletes(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        delta = book.apply_update(
            {
                "version": 11,
                "cts": 1_780_000_000_100,
                "bids": [[100, 8, 4], [99, 0, 0]],
                "asks": [[101, 2, 1], [102, 0, 0]],
            }
        )
        self.assertTrue(delta.applied)
        self.assertEqual(float(delta.bid_added), 2.0)
        self.assertEqual(float(delta.bid_pulled), 1.0)
        self.assertEqual(float(delta.ask_pulled), 4.0)
        self.assertEqual(float(delta.depth_flow_imbalance), 5.0)
        self.assertNotIn(99, book.bids)
        self.assertNotIn(102, book.asks)

    def test_merged_depth_range_covering_expected_version_is_contiguous(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        delta = book.apply_update(
            {
                "begin": 11,
                "end": 13,
                "version": 13,
                "bids": [[100, 9, 4]],
                "asks": [],
            }
        )
        self.assertTrue(delta.applied)
        self.assertEqual(delta.begin_version, 11)
        self.assertEqual(delta.end_version, 13)
        self.assertEqual(delta.range_span, 3)
        self.assertTrue(delta.merged_range)
        self.assertEqual(book.version, 13)
        self.assertEqual(book.best_bid()[1], 9)

    def test_overlapping_merged_range_is_safe_with_absolute_depth_values(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        book.apply_update(
            {"version": 11, "bids": [[100, 7, 3]], "asks": []}
        )
        delta = book.apply_update(
            {
                "begin": 10,
                "end": 12,
                "version": 12,
                "bids": [[100, 8, 4]],
                "asks": [],
            }
        )
        self.assertTrue(delta.applied)
        self.assertEqual(book.version, 12)
        self.assertEqual(book.best_bid()[1], 8)

    def test_real_range_gap_fails_before_mutating_book(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        with self.assertRaises(SequenceGapError) as ctx:
            book.apply_update(
                {
                    "begin": 12,
                    "end": 13,
                    "version": 13,
                    "bids": [[100, 8, 4]],
                    "asks": [],
                }
            )
        self.assertEqual(ctx.exception.expected, 11)
        self.assertEqual(ctx.exception.received_begin, 12)
        self.assertEqual(ctx.exception.received_end, 13)
        self.assertEqual(book.version, 10)
        self.assertEqual(book.best_bid()[1], 6)

    def test_range_metadata_must_be_consistent(self):
        with self.assertRaisesRegex(MexcOrderFlowError, "both begin and end"):
            depth_version_range({"version": 12, "begin": 11})
        with self.assertRaisesRegex(MexcOrderFlowError, "must equal depth end"):
            depth_version_range({"version": 12, "begin": 11, "end": 13})

    def test_stale_merged_range_is_ignored(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot(version=20))
        delta = book.apply_update(
            {
                "begin": 15,
                "end": 19,
                "version": 19,
                "bids": [[100, 999, 1]],
                "asks": [],
            }
        )
        self.assertFalse(delta.applied)
        self.assertEqual(book.version, 20)
        self.assertEqual(book.best_bid()[1], 6)

    def test_crossed_update_rolls_back(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        with self.assertRaisesRegex(MexcOrderFlowError, "locked or crossed"):
            book.apply_update(
                {"version": 11, "bids": [[101, 1, 1]], "asks": []}
            )
        self.assertEqual(book.version, 10)
        self.assertNotIn(101, book.bids)

    def test_recovery_commits_are_sorted_and_can_stop_at_target(self):
        book = OrderBook("ENA_USDT")
        book.load_snapshot(self.snapshot())
        payload = {
            "success": True,
            "code": 0,
            "data": [
                {"version": 13, "bids": [[100, 9, 4]], "asks": []},
                {"version": 12, "bids": [[100, 8, 4]], "asks": []},
                {"version": 11, "bids": [[100, 7, 3]], "asks": []},
            ],
        }
        self.assertEqual(
            apply_recovery_commits(book, payload, stop_version=12),
            2,
        )
        self.assertEqual(book.version, 12)
        self.assertEqual(book.best_bid()[1], 8)

    def test_depth_stats_separate_merged_ranges_from_true_gaps(self):
        engine = FeatureEngine(["ENA_USDT"], imbalance_levels=1)
        engine.load_snapshot("ENA_USDT", self.snapshot())
        row = engine.on_depth(
            "ENA_USDT",
            {
                "begin": 11,
                "end": 12,
                "version": 12,
                "bids": [[100, 7, 3]],
                "asks": [],
            },
        )
        self.assertEqual(row["compressed_depth_ranges_seen"], 1)
        self.assertEqual(row["true_depth_gaps_seen"], 0)
        with self.assertRaises(SequenceGapError):
            engine.on_depth(
                "ENA_USDT",
                {
                    "begin": 14,
                    "end": 14,
                    "version": 14,
                    "bids": [],
                    "asks": [],
                },
            )
        stats = engine.depth_stats_snapshot()["ENA_USDT"]
        self.assertEqual(stats["depth_messages_seen"], 2)
        self.assertEqual(stats["compressed_depth_ranges_seen"], 1)
        self.assertEqual(stats["true_depth_gaps_seen"], 1)

    def test_trade_stream_is_sorted_and_cvd_uses_exchange_side(self):
        engine = FeatureEngine(
            ["ENA_USDT"],
            trade_window_ms=10_000,
            imbalance_levels=1,
        )
        engine.load_snapshot("ENA_USDT", self.snapshot())
        features = engine.on_deals(
            "ENA_USDT",
            [
                {
                    "p": 100,
                    "v": 2,
                    "T": 2,
                    "t": 1001,
                    "i": "2",
                    "M": 2,
                },
                {
                    "p": 100,
                    "v": 5,
                    "T": 1,
                    "t": 1000,
                    "i": "1",
                    "M": 1,
                },
            ],
        )
        self.assertEqual(
            [row["aggressor_side"] for row in features],
            ["BUY", "SELL"],
        )
        self.assertEqual(features[-1]["rolling_buy_volume"], 5.0)
        self.assertEqual(features[-1]["rolling_sell_volume"], 2.0)
        self.assertEqual(features[-1]["rolling_cvd"], 3.0)
        self.assertEqual(features[0]["exchange_m_flag"], 1)
        self.assertNotIn("self_trade_flag", features[0])

    def test_trade_timestamp_regression_fails_closed(self):
        engine = FeatureEngine(["ENA_USDT"])
        engine.load_snapshot("ENA_USDT", self.snapshot())
        engine.on_deals(
            "ENA_USDT",
            [{"p": 100, "v": 1, "T": 1, "t": 1000}],
        )
        with self.assertRaisesRegex(MexcOrderFlowError, "regression"):
            engine.on_deals(
                "ENA_USDT",
                [{"p": 100, "v": 1, "T": 1, "t": 999}],
            )

    def test_decode_supports_plain_and_gzip_json(self):
        payload = {"channel": "pong", "data": 123}
        text = json.dumps(payload)
        self.assertEqual(dict(decode_ws_message(text)), payload)
        self.assertEqual(
            dict(decode_ws_message(gzip.compress(text.encode()))),
            payload,
        )

    def test_append_only_writer_refuses_overwrite_and_hashes_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "raw.jsonl"
            writer = AppendOnlyJsonl(path)
            writer.write({"a": 1})
            manifest = writer.close()
            self.assertEqual(
                manifest["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            self.assertTrue(
                path.with_name("raw.jsonl.manifest.json").exists()
            )
            with self.assertRaises(FileExistsError):
                AppendOnlyJsonl(path)

    def test_replay_recovers_real_gap_from_recorded_commits(self):
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
                        "data": {
                            "version": 12,
                            "bids": [[100, 8, 4]],
                            "asks": [],
                        },
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
                            {
                                "version": 13,
                                "bids": [[100, 9, 4]],
                                "asks": [],
                            },
                            {
                                "version": 12,
                                "bids": [[100, 8, 4]],
                                "asks": [],
                            },
                            {
                                "version": 11,
                                "bids": [[100, 7, 3]],
                                "asks": [],
                            },
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
                        "data": [
                            {
                                "p": 100,
                                "v": 2,
                                "T": 1,
                                "t": 1000,
                                "i": "abc",
                            }
                        ],
                    },
                },
            ]
            raw.write_text(
                "".join(json.dumps(row) + "\n" for row in records),
                encoding="utf-8",
            )
            emitted = replay(
                raw,
                output,
                trade_window_seconds=10.0,
                imbalance_levels=1,
            )
            self.assertEqual(emitted, 3)
            rows = [
                json.loads(line)
                for line in output.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            recovered = [
                row
                for row in rows
                if row.get("replayed_after_recovery")
            ]
            self.assertEqual(len(recovered), 1)
            self.assertEqual(
                recovered[0]["book_version"],
                12,
            )
            trades = [
                row
                for row in rows
                if row.get("event_type") == "trade"
            ]
            self.assertEqual(
                trades[0]["rolling_cvd"],
                2.0,
            )

    def test_replay_v1_ignores_false_gap_recovery_after_valid_merged_range(self):
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
                        "data": {
                            "begin": 11,
                            "end": 12,
                            "version": 12,
                            "bids": [[100, 8, 4]],
                            "asks": [],
                        },
                    },
                },
                {
                    "record_type": "depth_gap",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 21,
                    "expected_version": 11,
                    "received_version": 12,
                },
                {
                    "record_type": "rest_depth_commits",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 30,
                    "payload": {
                        "success": True,
                        "code": 0,
                        "data": [
                            {
                                "version": 13,
                                "bids": [[100, 999, 1]],
                                "asks": [],
                            }
                        ],
                    },
                },
                {
                    "record_type": "rest_snapshot",
                    "reason": "depth_gap_fallback",
                    "symbol": "ENA_USDT",
                    "received_at_ns": 31,
                    "payload": self.snapshot(version=99),
                },
            ]
            raw.write_text(
                "".join(json.dumps(row) + "\n" for row in records),
                encoding="utf-8",
            )
            emitted = replay(
                raw,
                output,
                trade_window_seconds=10.0,
                imbalance_levels=1,
            )
            self.assertEqual(emitted, 2)
            rows = [
                json.loads(line)
                for line in output.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            depth_rows = [
                row
                for row in rows
                if row.get("event_type") == "depth"
            ]
            self.assertEqual(len(depth_rows), 1)
            self.assertEqual(depth_rows[0]["book_version"], 12)
            self.assertEqual(
                depth_rows[0]["compressed_depth_ranges_seen"],
                1,
            )
            self.assertEqual(
                depth_rows[0]["true_depth_gaps_seen"],
                0,
            )

    def test_replay_rejects_unresolved_gap(self):
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
                    "received_at_ns": 20,
                    "payload": {
                        "channel": "push.depth",
                        "symbol": "ENA_USDT",
                        "data": {
                            "begin": 99,
                            "end": 99,
                            "version": 99,
                            "bids": [],
                            "asks": [],
                        },
                    },
                },
            ]
            raw.write_text(
                "".join(json.dumps(row) + "\n" for row in records),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                MexcOrderFlowError,
                "unresolved",
            ):
                replay(
                    raw,
                    output,
                    trade_window_seconds=10.0,
                    imbalance_levels=1,
                )


if __name__ == "__main__":
    unittest.main()

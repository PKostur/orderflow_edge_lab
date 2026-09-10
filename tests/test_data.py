from datetime import datetime, timezone
import unittest

from orderflow_edge_lab.data import (
    DataQualityPolicy, Side, normalize_rows, parse_timestamp_ns, quality_report,
)


class DataTests(unittest.TestCase):
    def test_nanosecond_precision_is_preserved(self):
        expected = 1700000000123456789
        for value in (expected, str(expected), "1700000000.123456789",
                      "1700000000123.456789", "1700000000123456.789",
                      "2023-11-14T22:13:20.123456789Z",
                      "2023-11-15T00:13:20.123456789+02:00"):
            self.assertEqual(parse_timestamp_ns(value), expected)
        for value in ("NaN", "Infinity", "1700000000.1234567891", "2023-11-14T22:13:20.1234567891Z"):
            with self.assertRaises(ValueError):
                parse_timestamp_ns(value)

    def test_prior_bbo_is_causal_bounded_and_symbol_specific(self):
        quote = {"timestamp": 1700000000, "symbol": "NQ", "event": "Quote", "bid": 99, "ask": 100}
        for offset, symbol, expected in ((0.5, "NQ", "quote"), (2, "NQ", "unknown"),
                                          (-0.5, "NQ", "unknown"), (0, "NQ", "unknown"),
                                          (0.5, "MNQ", "unknown")):
            events = normalize_rows([quote, {"timestamp": 1700000000 + offset,
                                            "symbol": symbol, "price": 100}])
            self.assertEqual(events[-1].side_source, expected)

    def test_explicit_trade_updates_tick_rule_without_future_lookahead(self):
        rows = [{"timestamp": 1700000000, "symbol": "NQ", "price": 100, "side": "buy"},
                {"timestamp": 1700000001, "symbol": "NQ", "price": 99},
                {"timestamp": 1699999999, "symbol": "NQ", "price": 98}]
        events = normalize_rows(rows)
        self.assertEqual(events[1].side, Side.SELL)
        self.assertEqual(events[1].side_source, "tick_rule")
        self.assertEqual(events[2].side, Side.UNKNOWN)

    def test_invalid_quote_update_does_not_reuse_older_bbo(self):
        for bid, ask in ((101, 100), (100, 100), (None, 100)):
            events = normalize_rows([
                {"timestamp": 1700000000, "symbol": "NQ", "event": "Quote", "bid": 99, "ask": 100},
                {"timestamp": 1700000000.1, "symbol": "NQ", "event": "Quote", "bid": bid, "ask": ask},
                {"timestamp": 1700000000.2, "symbol": "NQ", "price": 100},
            ])
            self.assertEqual(events[-1].side, Side.UNKNOWN)

    def test_missing_clock_future_clock_and_quote_only_fail(self):
        events = normalize_rows([{"timestamp": 1700000000, "symbol": "NQ", "price": 100, "side": "buy"}])
        policy = DataQualityPolicy(min_events=1, max_latest_age_seconds=1)
        self.assertIn("missing_freshness_reference", quality_report(events, policy).failures)
        self.assertIn("future_latest_event", quality_report(events, policy, now_ns=1699999999000000000).failures)
        quotes = normalize_rows([{"timestamp": 1700000000, "symbol": "NQ", "event": "Quote", "bid": 99, "ask": 100}])
        self.assertIn("no_trades", quality_report(quotes, DataQualityPolicy(min_events=1)).failures)

    def test_unsupported_and_priceless_trades_are_rejected(self):
        for row in ({"event": "Trade"}, {"event": "Summary", "price": 100}, {"price": True}):
            with self.assertRaises(ValueError):
                normalize_rows([{"timestamp": 1700000000, "symbol": "NQ", **row}])

    def test_timestamp_units_and_iso(self):
        values = [
            1_700_000_000,
            1_700_000_000_000,
            1_700_000_000_000_000,
            1_700_000_000_000_000_000,
            "2023-11-14T22:13:20+00:00",
        ]
        parsed = [parse_timestamp_ns(x) for x in values]
        self.assertTrue(max(parsed) - min(parsed) < 1_000)

    def test_naive_iso_rejected(self):
        with self.assertRaises(ValueError):
            parse_timestamp_ns("2026-09-10T12:00:00")

    def test_side_precedence(self):
        rows = [
            {"timestamp": 1700000000, "symbol": "NQ", "event": "Trade", "price": 100, "bid": 99.75, "ask": 100, "side": "sell"},
            {"timestamp": 1700000001, "symbol": "NQ", "event": "Trade", "price": 101, "bid": 100.75, "ask": 101},
            {"timestamp": 1700000003, "symbol": "NQ", "event": "Trade", "price": 100.5},
        ]
        events = normalize_rows(rows)
        self.assertEqual(events[0].side, Side.SELL)
        self.assertEqual(events[0].side_source, "explicit")
        self.assertEqual(events[1].side, Side.BUY)
        self.assertEqual(events[1].side_source, "quote")
        self.assertEqual(events[2].side, Side.SELL)
        self.assertEqual(events[2].side_source, "tick_rule")

    def test_quality_gate_catches_crossed_and_duplicates(self):
        rows = [
            {"timestamp": 1700000000, "symbol": "NQ", "event": "Quote", "bid": 101, "ask": 100},
            {"timestamp": 1700000000, "symbol": "NQ", "event": "Quote", "bid": 101, "ask": 100},
        ]
        events = normalize_rows(rows)
        report = quality_report(events, DataQualityPolicy(min_events=1))
        self.assertFalse(report.passed)
        self.assertIn("crossed_quote_fraction", report.failures)
        self.assertIn("duplicate_fraction", report.failures)

    def test_non_monotonic_detected(self):
        rows = [
            {"timestamp": 1700000002, "symbol": "NQ", "event": "Trade", "price": 100},
            {"timestamp": 1700000001, "symbol": "NQ", "event": "Trade", "price": 101},
        ]
        report = quality_report(
            normalize_rows(rows),
            DataQualityPolicy(
                min_events=1,
                max_unknown_trade_side_fraction=1.0,
                max_tick_rule_trade_fraction=1.0,
                min_trade_bbo_fraction_when_explicit_side_low=0.0,
            ),
        )
        self.assertFalse(report.monotonic_timestamps)
        self.assertIn("non_monotonic_timestamps", report.failures)

    def test_low_bbo_rejected_unless_explicit_side_is_strong(self):
        weak = normalize_rows([
            {"timestamp": 1700000000 + i, "symbol": "NQ", "event": "Trade", "price": 100 + i}
            for i in range(4)
        ])
        report = quality_report(
            weak,
            DataQualityPolicy(
                min_events=1,
                max_unknown_trade_side_fraction=1.0,
                max_tick_rule_trade_fraction=1.0,
            ),
        )
        self.assertIn("trade_bbo_fraction", report.failures)

        explicit = normalize_rows([
            {"timestamp": 1700000100 + i, "symbol": "NQ", "event": "Trade", "price": 100 + i, "side": "buy"}
            for i in range(10)
        ])
        report2 = quality_report(explicit, DataQualityPolicy(min_events=1))
        self.assertNotIn("trade_bbo_fraction", report2.failures)


if __name__ == "__main__":
    unittest.main()

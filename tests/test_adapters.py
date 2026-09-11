from datetime import timezone
import unittest

from orderflow_edge_lab.adapters import attach_prior_bbo, normalize_dxfeed_rows
from orderflow_edge_lab.data import MarketEvent, Side

UTC = timezone.utc
BASE = 1_700_000_000_000_000_000


class AdapterTests(unittest.TestCase):
    def test_custom_tight_age_is_not_bypassed_by_normalization(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "quote", "bid": 20000.0, "ask": 20000.25},
            {"timestamp": BASE + 100_000_000, "symbol": "MNQ", "kind": "trade", "price": 20000.25},
        ], max_quote_age_seconds=0.01)
        self.assertIsNone(result.events[-1].bid)
        self.assertEqual(result.stats.stale_prior_quotes_ignored, 1)

    def test_equal_timestamp_and_invalid_updates_cannot_supply_bbo(self):
        tied = attach_prior_bbo([
            MarketEvent(BASE, "MNQ", "QUOTE", bid=100, ask=101),
            MarketEvent(BASE, "MNQ", "TRADE", price=101),
        ])
        self.assertIsNone(tied.events[-1].bid)
        self.assertEqual(tied.stats.same_timestamp_quotes_ignored, 1)
        for bid, ask in ((102, 101), (101, 101), (None, 101)):
            result = attach_prior_bbo([
                MarketEvent(BASE, "MNQ", "QUOTE", bid=100, ask=101),
                MarketEvent(BASE + 1, "MNQ", "QUOTE", bid=bid, ask=ask),
                MarketEvent(BASE + 2, "MNQ", "TRADE", price=101),
            ])
            self.assertIsNone(result.events[-1].bid)
            self.assertEqual(result.events[-1].side, Side.UNKNOWN)

    def test_separate_quote_is_causally_attached_to_trade(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "quote", "bid": 20000.0, "ask": 20000.25},
            {"timestamp": BASE + 100_000_000, "symbol": "MNQ", "kind": "trade", "price": 20000.25, "size": 2},
        ])
        trade = result.events[1]
        self.assertEqual((trade.bid, trade.ask), (20000.0, 20000.25))
        self.assertEqual(trade.side, Side.BUY)
        self.assertEqual(trade.side_source, "quote")
        self.assertEqual(result.stats.trades_enriched_from_prior_bbo, 1)
        self.assertEqual(result.stats.trade_bbo_fraction, 1.0)

    def test_trade_embedded_bbo_is_not_reused_as_quote_history(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "trade", "price": 101, "bid": 100, "ask": 101},
            {"timestamp": BASE + 1, "symbol": "MNQ", "kind": "trade", "price": 101},
        ])
        first, second = result.events
        self.assertEqual((first.bid, first.ask), (100, 101))
        self.assertEqual(first.side, Side.BUY)
        self.assertIsNone(second.bid)
        self.assertIsNone(second.ask)
        self.assertEqual(result.stats.quote_events, 0)
        self.assertEqual(result.stats.trades_enriched_from_prior_bbo, 0)

    def test_stale_quote_is_not_attached(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "quote", "bid": 20000.0, "ask": 20000.25},
            {"timestamp": BASE + 3_000_000_000, "symbol": "MNQ", "kind": "trade", "price": 20000.25},
        ], max_quote_age_seconds=2.0)
        trade = result.events[1]
        self.assertIsNone(trade.bid)
        self.assertIsNone(trade.ask)
        self.assertEqual(result.stats.stale_prior_quotes_ignored, 1)

    def test_out_of_order_future_quote_is_never_looked_back_into_trade(self):
        events = [
            MarketEvent(BASE + 1_000_000_000, "MNQ", "QUOTE", bid=20000.0, ask=20000.25),
            MarketEvent(BASE, "MNQ", "TRADE", price=20000.25),
        ]
        result = attach_prior_bbo(events)
        self.assertIsNone(result.events[1].bid)
        self.assertEqual(result.stats.future_prior_quotes_ignored, 1)
        self.assertEqual(result.stats.timestamp_regressions, 1)

    def test_timestamp_regression_can_fail_closed(self):
        events = [
            MarketEvent(BASE + 2, "MNQ", "QUOTE", bid=100, ask=101),
            MarketEvent(BASE + 1, "NQ", "QUOTE", bid=200, ask=201),
        ]
        with self.assertRaisesRegex(ValueError, "source timestamp regression"):
            attach_prior_bbo(events, reject_timestamp_regressions=True)

    def test_timestamp_regression_is_exposed_even_without_bbo_interaction(self):
        result = attach_prior_bbo([
            MarketEvent(BASE + 2, "MNQ", "TRADE", price=101),
            MarketEvent(BASE + 1, "NQ", "TRADE", price=201),
        ])
        self.assertEqual(result.stats.timestamp_regressions, 1)
        self.assertEqual(len(result.events), 2)

    def test_normalize_dxfeed_rows_forwards_strict_timestamp_mode(self):
        rows = [
            {"timestamp": BASE + 2, "symbol": "MNQ", "kind": "trade", "price": 101},
            {"timestamp": BASE + 1, "symbol": "MNQ", "kind": "trade", "price": 100},
        ]
        with self.assertRaisesRegex(ValueError, "source timestamp regression"):
            normalize_dxfeed_rows(rows, reject_timestamp_regressions=True)

    def test_invalid_strict_timestamp_flag_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "reject_timestamp_regressions must be a bool"):
            attach_prior_bbo([], reject_timestamp_regressions=1)

    def test_explicit_side_wins_over_quote_inference(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "quote", "bid": 20000.0, "ask": 20000.25},
            {"timestamp": BASE + 1, "symbol": "MNQ", "kind": "trade", "price": 20000.25, "side": "SELL"},
        ])
        trade = result.events[1]
        self.assertEqual(trade.side, Side.SELL)
        self.assertEqual(trade.side_source, "explicit")

    def test_bbo_cache_is_symbol_isolated(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "quote", "bid": 20000.0, "ask": 20000.25},
            {"timestamp": BASE + 1, "symbol": "NQ", "kind": "trade", "price": 20000.25},
        ])
        self.assertIsNone(result.events[1].bid)
        self.assertEqual(result.stats.trades_enriched_from_prior_bbo, 0)

    def test_crossed_quote_is_not_cached(self):
        result = normalize_dxfeed_rows([
            {"timestamp": BASE, "symbol": "MNQ", "kind": "quote", "bid": 20001.0, "ask": 20000.0},
            {"timestamp": BASE + 1, "symbol": "MNQ", "kind": "trade", "price": 20000.25},
        ])
        self.assertIsNone(result.events[1].bid)
        self.assertEqual(result.stats.crossed_quotes_ignored, 1)

    def test_invalid_quote_age_fails_closed(self):
        for value in (0, -1, float("inf"), float("nan"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                attach_prior_bbo([], max_quote_age_seconds=value)


if __name__ == "__main__":
    unittest.main()

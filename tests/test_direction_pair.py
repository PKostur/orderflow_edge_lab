from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.direction_pair import evaluate_pair
from orderflow_edge_lab.orderflow_backtest import BacktestConfig


class DirectionPairTests(unittest.TestCase):
    def _write(self, rows):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "features.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return path

    @staticmethod
    def _trade(symbol, exchange_ts, observed_ms, *, bid, ask, buy, sell, imbalance, micro):
        return {
            "event_type": "trade",
            "symbol": symbol,
            "exchange_ts_ms": exchange_ts,
            "received_at_ns": observed_ms * 1_000_000,
            "best_bid": bid,
            "best_ask": ask,
            "microprice": micro,
            "book_imbalance_10": imbalance,
            "rolling_buy_volume": buy,
            "rolling_sell_volume": sell,
            "rolling_trade_count": 10,
            "trade_price": (bid + ask) / 2,
        }

    def test_reversed_stream_flips_direction_and_recalculates_executable_quotes(self):
        rows = [
            self._trade("BTC_USDT", 900, 900, bid=100, ask=101, buy=9, sell=1, imbalance=.5, micro=100.8),
            self._trade("ENA_USDT", 1000, 1000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("ENA_USDT", 2000, 2000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        report = evaluate_pair(
            self._write(rows),
            BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0,), cooldown_ms=0),
        )

        original = next(
            row for row in report["streams"]["original"]["observations"] if row["family"] == "aligned_btc"
        )
        reversed_trade = next(
            row for row in report["streams"]["reversed"]["observations"] if row["family"] == "aligned_btc"
        )

        self.assertEqual(original["signal_side"], 1)
        self.assertEqual(original["side"], 1)
        self.assertEqual(reversed_trade["signal_side"], 1)
        self.assertEqual(reversed_trade["side"], -1)
        self.assertEqual(original["signal_observed_at_ns"], reversed_trade["signal_observed_at_ns"])
        self.assertEqual(original["exit_observed_at_ns"], reversed_trade["exit_observed_at_ns"])

        self.assertAlmostEqual(original["entry_price"], 10.01)
        self.assertAlmostEqual(original["exit_price"], 10.03)
        self.assertAlmostEqual(reversed_trade["entry_price"], 10.00)
        self.assertAlmostEqual(reversed_trade["exit_price"], 10.04)
        self.assertGreater(original["gross_bps"], 0)
        self.assertLess(reversed_trade["gross_bps"], 0)

    def test_pair_has_identical_group_counts_and_remains_exploratory(self):
        rows = [
            self._trade("BTC_USDT", 900, 900, bid=100, ask=101, buy=9, sell=1, imbalance=.5, micro=100.8),
            self._trade("ENA_USDT", 1000, 1000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("ENA_USDT", 2000, 2000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        report = evaluate_pair(
            self._write(rows),
            BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0, 4.0), cooldown_ms=0),
        )

        original = {
            (r["family"], r["horizon_ms"], r["fee_bps_round_trip"]): r["observations"]
            for r in report["streams"]["original"]["summary"]
        }
        reversed_stream = {
            (r["family"], r["horizon_ms"], r["fee_bps_round_trip"]): r["observations"]
            for r in report["streams"]["reversed"]["summary"]
        }
        self.assertEqual(original, reversed_stream)
        self.assertTrue(report["claims"]["exploratory_only"])
        self.assertTrue(report["claims"]["paired_control_only"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])


if __name__ == "__main__":
    unittest.main()

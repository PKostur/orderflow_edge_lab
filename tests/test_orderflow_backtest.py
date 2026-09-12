from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.orderflow_backtest import BacktestConfig, OrderFlowBacktestError, evaluate


class OrderFlowBacktestTests(unittest.TestCase):
    def _write(self, rows):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "features.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return path

    @staticmethod
    def _trade(symbol, exchange_ts, observed_ms, *, bid, ask, buy, sell, imbalance, micro):
        return {
            "event_type": "trade", "symbol": symbol,
            "exchange_ts_ms": exchange_ts, "received_at_ns": observed_ms * 1_000_000,
            "best_bid": bid, "best_ask": ask, "microprice": micro,
            "book_imbalance_10": imbalance,
            "rolling_buy_volume": buy, "rolling_sell_volume": sell,
            "rolling_trade_count": 10, "trade_price": (bid + ask) / 2,
        }

    def test_crossing_spread_and_fees_are_charged(self):
        rows = [
            self._trade("BTC_USDT", 900, 900, bid=100, ask=101, buy=9, sell=1, imbalance=.5, micro=100.8),
            self._trade("ENA_USDT", 1000, 1000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("ENA_USDT", 2000, 2000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        report = evaluate(self._write(rows), BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0, 4.0), cooldown_ms=0))
        aligned = [x for x in report["summary"] if x["family"] == "aligned_btc"]
        self.assertEqual(len(aligned), 2)
        gross = next(x for x in aligned if x["fee_bps_round_trip"] == 0.0)
        net = next(x for x in aligned if x["fee_bps_round_trip"] == 4.0)
        self.assertGreater(gross["gross_mean_bps"], 0)
        self.assertAlmostEqual(net["net_mean_bps"], gross["gross_mean_bps"] - 4.0)
        self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_btc_confirmation_blocks_opposite_context(self):
        rows = [
            self._trade("BTC_USDT", 900, 900, bid=100, ask=101, buy=1, sell=9, imbalance=-.5, micro=100.2),
            self._trade("ENA_USDT", 1000, 1000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("ENA_USDT", 2000, 2000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        report = evaluate(self._write(rows), BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0,), cooldown_ms=0))
        families = {x["family"] for x in report["summary"]}
        self.assertIn("aligned", families)
        self.assertNotIn("aligned_btc", families)

    def test_future_context_does_not_leak_backward(self):
        rows = [
            self._trade("ENA_USDT", 1000, 1000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("BTC_USDT", 1500, 1500, bid=100, ask=101, buy=9, sell=1, imbalance=.5, micro=100.8),
            self._trade("ENA_USDT", 2000, 2000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        report = evaluate(self._write(rows), BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0,), cooldown_ms=0))
        first = [x for x in report["observations"] if x["signal_observed_at_ns"] == 1_000_000_000 and x["family"] == "aligned"]
        self.assertTrue(first)
        self.assertTrue(all(x["btc_flow_side"] == 0 for x in first))

    def test_exchange_timestamp_regression_does_not_reorder_observations(self):
        rows = [
            self._trade("ENA_USDT", 2000, 1000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("ENA_USDT", 1500, 2000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        report = evaluate(self._write(rows), BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0,), cooldown_ms=0))
        self.assertEqual(report["causal_clock"], "received_at_ns")
        self.assertFalse(report["exchange_timestamps_used_for_ordering"])

    def test_observation_time_regression_fails_closed(self):
        rows = [
            self._trade("ENA_USDT", 1000, 2000, bid=10.00, ask=10.01, buy=9, sell=1, imbalance=.6, micro=10.008),
            self._trade("ENA_USDT", 2000, 1000, bid=10.03, ask=10.04, buy=9, sell=1, imbalance=.6, micro=10.038),
        ]
        with self.assertRaises(OrderFlowBacktestError):
            evaluate(self._write(rows), BacktestConfig(horizons_ms=(1000,), fee_bps_round_trip=(0.0,), cooldown_ms=0))


if __name__ == "__main__":
    unittest.main()

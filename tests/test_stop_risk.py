from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.orderflow_backtest import BacktestConfig
from orderflow_edge_lab.stop_risk import StopRiskConfig, evaluate_stop_risk


class StopRiskTests(unittest.TestCase):
    def _write(self, rows):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "features.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_fee_is_included_in_position_risk_sizing(self):
        rows = [
            {"event_type":"depth","symbol":"ENA_USDT","received_at_ns":0,"best_bid":9.99,"best_ask":10.00,"book_imbalance_10":0.0,"microprice":9.995},
            {"event_type":"trade","symbol":"ENA_USDT","received_at_ns":1_000_000_000,"best_bid":10.00,"best_ask":10.01,"book_imbalance_10":0.5,"microprice":10.005,"rolling_buy_volume":5,"rolling_sell_volume":5,"rolling_trade_count":10},
            {"event_type":"depth","symbol":"ENA_USDT","received_at_ns":2_000_000_000,"best_bid":9.99,"best_ask":10.00,"book_imbalance_10":0.0,"microprice":9.995},
            {"event_type":"depth","symbol":"ENA_USDT","received_at_ns":31_000_000_000,"best_bid":9.99,"best_ask":10.00,"book_imbalance_10":0.0,"microprice":9.995},
        ]
        cfg = StopRiskConfig(rr_targets=(1.0,), risk_fractions=(0.01,), fee_bps_round_trip=(4.0,), max_exposure_multiple=100.0)
        report = evaluate_stop_risk(self._write(rows), BacktestConfig(cooldown_ms=0), cfg)
        book = next(row for row in report["trades"] if row["family"] == "book" and row["stream"] == "original")
        self.assertFalse(book["exposure_capped"])
        self.assertAlmostEqual(book["actual_stop_risk_fraction"], 0.01, places=10)
        naive = 0.01 / (book["stop_distance_bps"] / 10_000.0)
        self.assertLess(book["exposure_multiple"], naive)
        self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_reversed_stream_is_present(self):
        rows = [
            {"event_type":"depth","symbol":"ENA_USDT","received_at_ns":0,"best_bid":9.99,"best_ask":10.00,"book_imbalance_10":0.0,"microprice":9.995},
            {"event_type":"trade","symbol":"ENA_USDT","received_at_ns":1_000_000_000,"best_bid":10.00,"best_ask":10.01,"book_imbalance_10":0.5,"microprice":10.005,"rolling_buy_volume":5,"rolling_sell_volume":5,"rolling_trade_count":10},
            {"event_type":"depth","symbol":"ENA_USDT","received_at_ns":2_000_000_000,"best_bid":10.02,"best_ask":10.03,"book_imbalance_10":0.0,"microprice":10.025},
            {"event_type":"depth","symbol":"ENA_USDT","received_at_ns":31_000_000_000,"best_bid":10.02,"best_ask":10.03,"book_imbalance_10":0.0,"microprice":10.025},
        ]
        cfg = StopRiskConfig(rr_targets=(1.0,), risk_fractions=(0.01,), fee_bps_round_trip=(4.0,))
        report = evaluate_stop_risk(self._write(rows), BacktestConfig(cooldown_ms=0), cfg)
        streams = {row["stream"] for row in report["summary"]}
        self.assertEqual(streams, {"original", "reversed"})


if __name__ == "__main__":
    unittest.main()

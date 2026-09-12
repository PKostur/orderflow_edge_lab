from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.market_state_scan import MarketStateScanConfig, scan_market_state


class MarketStateScanTests(unittest.TestCase):
    def _capture(self, root: Path) -> Path:
        path = root / "features.jsonl"
        rows = []
        base_ns = 1_800_000_000_000_000_000
        for second in range(240):
            trend = second / 240.0
            eth_mid = 100.0 + second * 0.01 + (0.04 if (second // 30) % 2 else 0.0)
            btc_mid = 200.0 + second * 0.008
            book = -0.8 + 1.6 * trend
            micro_edge = book * 0.4
            for offset, symbol, mid in (
                (0, "ETH_USDT", eth_mid),
                (2, "BTC_USDT", btc_mid),
            ):
                bid = mid - 0.005
                ask = mid + 0.005
                rows.append(
                    {
                        "symbol": symbol,
                        "event_type": "depth",
                        "received_at_ns": base_ns + second * 1_000_000_000 + offset,
                        "best_bid": bid,
                        "best_ask": ask,
                        "best_bid_contract_volume": 1000.0 + second,
                        "best_ask_contract_volume": 900.0 + second,
                        "book_imbalance_10": book if symbol == "ETH_USDT" else 0.2,
                        "microprice": mid + (micro_edge * 0.005 if symbol == "ETH_USDT" else 0.001),
                        "depth_flow_imbalance": book if symbol == "ETH_USDT" else 0.1,
                    }
                )
                rows.append(
                    {
                        "symbol": symbol,
                        "event_type": "trade",
                        "received_at_ns": base_ns + second * 1_000_000_000 + offset + 1,
                        "best_bid": bid,
                        "best_ask": ask,
                        "best_bid_contract_volume": 1000.0 + second,
                        "best_ask_contract_volume": 900.0 + second,
                        "book_imbalance_10": book if symbol == "ETH_USDT" else 0.2,
                        "microprice": mid + (micro_edge * 0.005 if symbol == "ETH_USDT" else 0.001),
                        "rolling_buy_volume": 10.0 + second * (1.0 + trend),
                        "rolling_sell_volume": 10.0 + second * (1.0 - 0.5 * trend),
                        "rolling_trade_count": 5 + second % 20,
                        "trade_velocity_per_second": 2.0 + second % 10,
                    }
                )
        rows.sort(key=lambda row: row["received_at_ns"])
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def test_scan_separates_market_state_from_strategy_pnl(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._capture(Path(temp))
            report = scan_market_state(
                path,
                MarketStateScanConfig(
                    symbol="ETH_USDT",
                    context_symbol="BTC_USDT",
                    sample_seconds=5,
                    directionality_horizons_seconds=(15, 30),
                    volatility_horizons_seconds=(30,),
                    liquidity_horizons_seconds=(5, 15),
                    continuation_horizons_seconds=(15, 30),
                    minimum_association_observations=10,
                ),
                batch_id="synthetic-batch",
            )
        self.assertEqual(report["experiment"], "regime_research_v1_market_state_scan")
        self.assertEqual(report["batch_id"], "synthetic-batch")
        self.assertGreater(report["sampling"]["observations"], 20)
        self.assertTrue(report["claims"]["market_state_first"])
        self.assertFalse(report["claims"]["strategy_pnl_used"])
        self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])
        targets = report["observations"][10]["targets"]
        self.assertIn("directionality_efficiency_15s", targets)
        self.assertIn("future_range_bps_30s", targets)
        self.assertIn("future_spread_bps_5s", targets)
        self.assertIn("continuation_fraction_15s", targets)
        self.assertTrue(report["associations"])

    def test_redundancy_scan_reports_feature_relationships(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._capture(Path(temp))
            report = scan_market_state(
                path,
                MarketStateScanConfig(
                    symbol="ETH_USDT",
                    context_symbol="BTC_USDT",
                    sample_seconds=5,
                    directionality_horizons_seconds=(15,),
                    volatility_horizons_seconds=(30,),
                    liquidity_horizons_seconds=(5,),
                    continuation_horizons_seconds=(15,),
                    minimum_association_observations=10,
                    redundancy_abs_spearman_threshold=0.70,
                ),
            )
        pairs = report["feature_redundancy"]["pairs"]
        self.assertTrue(any(item["left_feature"] == "book_imbalance_10" for item in pairs))
        self.assertTrue(report["feature_redundancy"]["clusters"])


if __name__ == "__main__":
    unittest.main()

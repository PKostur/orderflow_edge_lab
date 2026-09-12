from __future__ import annotations

import unittest
from unittest.mock import patch

from orderflow_edge_lab.pair_screen import PairScreenConfig, screen_pairs


class PairScreenTests(unittest.TestCase):
    def test_selection_uses_market_compatibility_not_pnl(self):
        details = {
            "success": True,
            "data": [
                {"symbol": "BTC_USDT", "baseCoin": "BTC", "quoteCoin": "USDT", "apiAllowed": True},
                {"symbol": "ETH_USDT", "baseCoin": "ETH", "quoteCoin": "USDT", "apiAllowed": True},
                {"symbol": "SOL_USDT", "baseCoin": "SOL", "quoteCoin": "USDT", "apiAllowed": False},
                {"symbol": "THIN_USDT", "baseCoin": "THIN", "quoteCoin": "USDT", "apiAllowed": True},
            ],
        }
        tickers = {
            "success": True,
            "data": [
                {"symbol": "BTC_USDT", "bid1": 100, "ask1": 100.01, "lastPrice": 100, "amount24": 500_000_000, "high24Price": 105, "lower24Price": 95, "fundingRate": 0.0001},
                {"symbol": "ETH_USDT", "bid1": 50, "ask1": 50.005, "lastPrice": 50, "amount24": 200_000_000, "high24Price": 53, "lower24Price": 47, "fundingRate": 0.0002},
                {"symbol": "SOL_USDT", "bid1": 20, "ask1": 20.005, "lastPrice": 20, "amount24": 100_000_000, "high24Price": 22, "lower24Price": 18, "fundingRate": -0.0001},
                {"symbol": "THIN_USDT", "bid1": 1, "ask1": 1.01, "lastPrice": 1, "amount24": 5_000_000, "high24Price": 1.1, "lower24Price": 0.9, "fundingRate": 0.0},
            ],
        }
        with patch("orderflow_edge_lab.pair_screen._fetch_json", side_effect=[details, tickers]):
            report = screen_pairs(PairScreenConfig(top_n=2, max_spread_bps=5.0, min_turnover_usdt_24h=10_000_000))
        self.assertEqual(report["selected_symbols"], ["ETH_USDT", "SOL_USDT"])
        self.assertFalse(report["selection_rule"]["backtest_performance_used_for_selection"])
        sol = next(row for row in report["selected"] if row["symbol"] == "SOL_USDT")
        self.assertFalse(sol["api_allowed"])
        self.assertTrue(sol["research_screen_pass"])

    def test_non_crypto_tradfi_contracts_are_excluded_from_coin_panel(self):
        details = {
            "success": True,
            "data": [
                {"symbol": "ETH_USDT", "baseCoin": "ETH", "quoteCoin": "USDT", "conceptPlate": ["mc-trade-zone-layer2"]},
                {"symbol": "XAU_USDT", "baseCoin": "XAU", "quoteCoin": "USDT", "conceptPlate": ["mc-trade-zone-metals", "mc-trade-zone-tradfi", "mc-trade-zone-Commodities"]},
            ],
        }
        tickers = {
            "success": True,
            "data": [
                {"symbol": "ETH_USDT", "bid1": 50, "ask1": 50.005, "lastPrice": 50, "amount24": 100_000_000, "high24Price": 55, "lower24Price": 45},
                {"symbol": "XAU_USDT", "bid1": 4000, "ask1": 4000.1, "lastPrice": 4000, "amount24": 500_000_000, "high24Price": 4100, "lower24Price": 3900},
            ],
        }
        with patch("orderflow_edge_lab.pair_screen._fetch_json", side_effect=[details, tickers]):
            report = screen_pairs(PairScreenConfig(top_n=2))
        self.assertEqual(report["selected_symbols"], ["ETH_USDT"])
        xau = next(row for row in report["universe"] if row["symbol"] == "XAU_USDT")
        self.assertIn("non_crypto_contract", xau["screen_fail_reasons"])
        self.assertFalse(xau["research_screen_pass"])


if __name__ == "__main__":
    unittest.main()

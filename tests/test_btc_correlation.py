from __future__ import annotations

import unittest

from orderflow_edge_lab.btc_correlation import CorrelationPanelConfig, select_panel


class BtcCorrelationPanelTests(unittest.TestCase):
    def test_panel_diversifies_high_and_low_btc_correlation_without_pnl(self):
        screen = {
            "experiment": "market_compatibility_pair_screen",
            "selected": [
                {"symbol": "ETH_USDT", "amount24_usdt": 900_000_000},
                {"symbol": "SOL_USDT", "amount24_usdt": 800_000_000},
                {"symbol": "DOGE_USDT", "amount24_usdt": 700_000_000},
                {"symbol": "XRP_USDT", "amount24_usdt": 600_000_000},
                {"symbol": "SUI_USDT", "amount24_usdt": 500_000_000},
                {"symbol": "HYPE_USDT", "amount24_usdt": 400_000_000},
            ],
        }
        correlations = {
            "ETH_USDT": {"correlation": 0.86, "samples": 300},
            "SOL_USDT": {"correlation": 0.74, "samples": 300},
            "DOGE_USDT": {"correlation": 0.12, "samples": 300},
            "XRP_USDT": {"correlation": -0.08, "samples": 300},
            "SUI_USDT": {"correlation": 0.31, "samples": 300},
            "HYPE_USDT": {"correlation": 0.42, "samples": 300},
        }
        report = select_panel(
            screen,
            correlations,
            CorrelationPanelConfig(panel_size=5, high_target=2, low_target=2, min_samples=200),
        )
        self.assertEqual(report["selected_symbols"][:4], ["ETH_USDT", "SOL_USDT", "DOGE_USDT", "XRP_USDT"])
        self.assertEqual(report["selected_symbols"][4], "SUI_USDT")
        self.assertEqual(report["bucket_counts"]["high_positive"], 2)
        self.assertEqual(report["bucket_counts"]["low_absolute"], 2)
        self.assertFalse(report["selection_rule"]["correlation_selection_used_strategy_pnl"])
        self.assertTrue(report["claims"]["transfer_evidence_is_not_untouched_oos"])

    def test_insufficient_correlation_samples_cannot_fill_panel(self):
        screen = {"experiment": "market_compatibility_pair_screen", "selected": [{"symbol": "ETH_USDT", "amount24_usdt": 1}]}
        report = select_panel(
            screen,
            {"ETH_USDT": {"correlation": 0.9, "samples": 20}},
            CorrelationPanelConfig(panel_size=1, high_target=0, low_target=0, min_samples=200),
        )
        self.assertEqual(report["selected_symbols"], [])
        self.assertEqual(report["candidate_correlations"][0]["btc_correlation_bucket"], "insufficient")


if __name__ == "__main__":
    unittest.main()

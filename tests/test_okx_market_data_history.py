from __future__ import annotations

import unittest
from unittest.mock import patch

from orderflow_edge_lab.okx_market_data_history import (
    OkxMarketDataHistoryError,
    build_okx_historical_funding_source_probe,
    fetch_okx_historical_funding_manifest,
)


class OkxMarketDataHistoryTests(unittest.TestCase):
    def _payload(self):
        return {
            "code": "0",
            "msg": "",
            "data": [
                {
                    "ts": "1",
                    "totalSizeMB": "2.5",
                    "dateAggrType": "monthly",
                    "details": [
                        {
                            "instId": "",
                            "instFamily": "BTC-USDT",
                            "instType": "SWAP",
                            "dateRangeStart": "1",
                            "dateRangeEnd": "2",
                            "groupSizeMB": "2.5",
                            "groupDetails": [
                                {
                                    "filename": "BTC-USDT-funding-2025-09.zip",
                                    "dateTs": "1756656000000",
                                    "sizeMB": "2.5",
                                    "url": "https://example.invalid/btc.zip",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    def test_monthly_funding_manifest_parses_download_metadata(self):
        with patch(
            "orderflow_edge_lab.okx_market_data_history._get_json",
            return_value=self._payload(),
        ) as mocked:
            result = fetch_okx_historical_funding_manifest(
                aggregation="monthly",
                begin="2025-09-01T00:00:00+08:00",
                end="2025-09-01T00:00:00+08:00",
                instrument_families=["BTC-USDT"],
            )
        self.assertEqual(result["module"], "3")
        self.assertEqual(result["instrument_type"], "SWAP")
        self.assertEqual(result["date_aggregation_type"], "monthly")
        self.assertEqual(result["manifest_count"], 1)
        self.assertEqual(result["download_url_count"], 1)
        self.assertEqual(
            result["manifests"][0]["filename"],
            "BTC-USDT-funding-2025-09.zip",
        )
        url = mocked.call_args.args[0]
        self.assertIn("/api/v5/public/market-data-history?", url)
        self.assertIn("module=3", url)
        self.assertIn("instType=SWAP", url)
        self.assertIn("dateAggrType=monthly", url)
        self.assertIn("instFamilyList=BTC-USDT", url)

    def test_more_than_five_families_fails_closed(self):
        with self.assertRaises(OkxMarketDataHistoryError):
            fetch_okx_historical_funding_manifest(
                aggregation="monthly",
                begin="2025-09-01T00:00:00+08:00",
                end="2025-09-01T00:00:00+08:00",
                instrument_families=[f"ASSET{i}-USDT" for i in range(6)],
            )

    def test_daily_funding_requires_any(self):
        with self.assertRaises(OkxMarketDataHistoryError):
            fetch_okx_historical_funding_manifest(
                aggregation="daily",
                begin="2026-09-01T00:00:00+08:00",
                end="2026-09-02T00:00:00+08:00",
                instrument_families=["BTC-USDT"],
            )

    def test_any_cannot_mix_with_families(self):
        with self.assertRaises(OkxMarketDataHistoryError):
            fetch_okx_historical_funding_manifest(
                aggregation="daily",
                begin="2026-09-01T00:00:00+08:00",
                end="2026-09-02T00:00:00+08:00",
                instrument_families=["BTC-USDT"],
                any_instrument=True,
            )

    def test_source_probe_is_engineering_only(self):
        config = {
            "probe_id": "fixture",
            "rest_base": "https://www.okx.com",
            "request_pause_seconds": 0,
            "queries": [
                {
                    "aggregation": "monthly",
                    "begin": "2025-09-01T00:00:00+08:00",
                    "end": "2025-09-01T00:00:00+08:00",
                    "instrument_families": ["BTC-USDT"],
                }
            ],
        }
        with patch(
            "orderflow_edge_lab.okx_market_data_history._get_json",
            return_value=self._payload(),
        ):
            result = build_okx_historical_funding_source_probe(config)
        self.assertTrue(result["source_available"])
        self.assertEqual(result["evidence_use"], "engineering_source_discovery_only")
        claims = result["claims"]
        self.assertFalse(claims["candidate_pnl_computed"])
        self.assertFalse(claims["candidate_retested"])
        self.assertFalse(claims["historical_result_repaired"])
        self.assertFalse(claims["candidate_promoted"])
        self.assertFalse(claims["live_trading_authorized"])
        self.assertFalse(claims["leverage_authorized"])


if __name__ == "__main__":
    unittest.main()

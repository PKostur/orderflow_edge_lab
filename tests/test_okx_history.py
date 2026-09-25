from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from orderflow_edge_lab.okx_history import (
    OkxHistoryError,
    fetch_okx_swap_funding_history,
    fetch_okx_swap_klines,
    okx_swap_instrument,
)


class OkxHistoryTests(unittest.TestCase):
    def test_symbol_mapping(self):
        self.assertEqual(okx_swap_instrument("BTC_USDT"), "BTC-USDT-SWAP")
        self.assertEqual(okx_swap_instrument("ENAUSDT"), "ENA-USDT-SWAP")
        with self.assertRaises(OkxHistoryError):
            okx_swap_instrument("BTC_USD")

    def test_daily_history_parses_confirmed_rows(self):
        payload = {
            "code": "0",
            "msg": "",
            "data": [
                [
                    "1735776000000",
                    "100",
                    "105",
                    "95",
                    "102",
                    "10",
                    "0",
                    "0",
                    "1",
                ],
                [
                    "1735689600000",
                    "98",
                    "103",
                    "94",
                    "100",
                    "9",
                    "0",
                    "0",
                    "1",
                ],
            ],
        }
        with patch(
            "orderflow_edge_lab.okx_history._get_json",
            return_value=payload,
        ):
            frame = fetch_okx_swap_klines(
                "BTC_USDT",
                "1d",
                "2025-01-01T00:00:00Z",
                "2025-01-03T00:00:00Z",
                limit=100,
                request_pause_seconds=0.0,
            )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.index.tz, pd.Timestamp.now(tz="UTC").tz)
        self.assertAlmostEqual(float(frame.iloc[-1]["close"]), 102.0)

    def test_funding_history_uses_realized_rate_only(self):
        payload = {
            "code": "0",
            "msg": "",
            "data": [
                {
                    "fundingTime": "1735776000000",
                    "fundingRate": "0.0009",
                    "realizedRate": "0.0001",
                },
                {
                    "fundingTime": "1735747200000",
                    "fundingRate": "0.0008",
                    "realizedRate": "0.0002",
                },
            ],
        }
        with patch(
            "orderflow_edge_lab.okx_history._get_json",
            return_value=payload,
        ):
            frame = fetch_okx_swap_funding_history(
                "BTC_USDT",
                "2025-01-01T00:00:00Z",
                "2025-01-03T00:00:00Z",
                limit=400,
                request_pause_seconds=0.0,
            )
        self.assertEqual(len(frame), 2)
        self.assertEqual(
            sorted(round(float(v), 7) for v in frame["funding_rate"]),
            [0.0001, 0.0002],
        )


if __name__ == "__main__":
    unittest.main()

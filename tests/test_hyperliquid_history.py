from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from orderflow_edge_lab import hyperliquid_history as hh

H8 = 8 * 3600 * 1000


def _c(t, v=1.0, close=None):
    return {"t": t, "T": t + H8 - 1, "o": "1", "h": "2", "l": "0.5", "c": str(close or 1.5), "v": str(v)}


class SymbolMapTests(unittest.TestCase):
    def test_mapping(self):
        names = {"BTC", "kPEPE", "FIL", "TRUMP", "PUMP"}
        self.assertEqual(hh.hyperliquid_coin("BTC_USDT", names), "BTC")
        self.assertEqual(hh.hyperliquid_coin("PEPE_USDT", names), "kPEPE")
        self.assertEqual(hh.hyperliquid_coin("FILECOIN_USDT", names), "FIL")
        self.assertEqual(hh.hyperliquid_coin("TRUMPOFFICIAL_USDT", names), "TRUMP")
        self.assertEqual(hh.hyperliquid_coin("PUMPFUN_USDT", names), "PUMP")
        self.assertIsNone(hh.hyperliquid_coin("AKE_USDT", names))


class CandleTests(unittest.TestCase):
    def test_pagination_zero_volume_cut_and_dedupe(self):
        end = pd.Timestamp("2024-01-02", tz="UTC")
        e = int(end.timestamp() * 1000)
        t0 = e - 5 * H8
        page1 = [_c(t0, v=0.0), _c(t0 + H8), _c(t0 + 2 * H8)]
        page2 = [_c(t0 + 2 * H8), _c(t0 + 3 * H8), _c(t0 + 4 * H8)]  # t0+2*H8 duplicated
        page3 = [_c(t0 + 4 * H8 + 1)]  # closes at/after end -> cut
        page3[0]["T"] = e + 5
        calls = []

        def fake(body, timeout=30):
            calls.append(body["req"]["startTime"])
            return [page1, page2, page3, []][len(calls) - 1]

        with mock.patch.object(hh, "_post", fake):
            df = hh.fetch_hyperliquid_candles("BTC", "8h", pd.Timestamp(t0, unit="ms", tz="UTC"), end)
        self.assertEqual(calls[1], t0 + 2 * H8 + 1)
        self.assertEqual(calls[2], t0 + 4 * H8 + 1)  # page3 requested from last t + 1
        self.assertEqual(list(df.index), [pd.Timestamp(t0 + k * H8, unit="ms", tz="UTC") for k in (1, 2, 3, 4)])
        self.assertTrue(df.index.is_unique and df.index.is_monotonic_increasing)
        self.assertEqual(df.index.name, "timestamp")
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertTrue((df["volume"] > 0).all())

    def test_empty(self):
        with mock.patch.object(hh, "_post", lambda body, timeout=30: []):
            df = hh.fetch_hyperliquid_candles("X", "8h", "2024-01-01", "2024-02-01")
        self.assertTrue(df.empty)


class FundingTests(unittest.TestCase):
    def test_pagination_and_dedupe(self):
        base = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
        hr = 3600 * 1000
        p1 = [{"time": base + i * hr, "fundingRate": "0.0001"} for i in range(3)]
        p2 = [{"time": base + i * hr, "fundingRate": "0.0001"} for i in (2, 3, 4)]
        calls = []

        def fake(body, timeout=30):
            calls.append(body["startTime"])
            return [p1, p2, []][len(calls) - 1]

        with mock.patch.object(hh, "_post", fake), mock.patch.object(hh.time, "sleep"):
            s = hh.fetch_hyperliquid_funding("BTC", "2024-01-01", "2024-01-02")
        self.assertEqual(calls[1], base + 2 * hr + 1)
        self.assertEqual(len(s), 5)
        self.assertTrue(s.index.is_unique and s.index.is_monotonic_increasing)
        self.assertEqual(s.dtype, float)


if __name__ == "__main__":
    unittest.main()

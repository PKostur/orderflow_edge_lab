from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from orderflow_edge_lab.bybit_history import (
    _get_json,
    _mainnet_fallback_url,
)


class BybitHistoryEndpointTests(unittest.TestCase):
    def test_official_mainnet_fallback_preserves_path_and_query(self):
        url = (
            "https://api.bybit.com/v5/market/kline"
            "?category=linear&symbol=BTCUSDT&interval=D"
        )
        self.assertEqual(
            _mainnet_fallback_url(url),
            (
                "https://api.bytick.com/v5/market/kline"
                "?category=linear&symbol=BTCUSDT&interval=D"
            ),
        )

    def test_http_403_falls_back_to_official_alternate_mainnet_host(self):
        url = (
            "https://api.bybit.com/v5/market/kline"
            "?category=linear&symbol=BTCUSDT&interval=D"
        )
        failure = HTTPError(url, 403, "Forbidden", None, None)
        payload = b'{"retCode":0,"retMsg":"OK","result":{"list":[]}}'
        with patch(
            "orderflow_edge_lab.bybit_history._read_json",
            side_effect=[failure, payload],
        ) as read:
            result = _get_json(url)

        self.assertEqual(result["retCode"], 0)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(read.call_args_list[0].args[0], url)
        self.assertTrue(
            read.call_args_list[1].args[0].startswith(
                "https://api.bytick.com/v5/market/kline?"
            )
        )

    def test_non_bybit_403_does_not_change_source(self):
        url = "https://example.invalid/v5/market/kline"
        failure = HTTPError(url, 403, "Forbidden", None, None)
        with patch(
            "orderflow_edge_lab.bybit_history._read_json",
            side_effect=failure,
        ):
            with self.assertRaises(HTTPError):
                _get_json(url)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest.mock import MagicMock, patch

from orderflow_edge_lab.dxfeed import (
    DEFAULT_ENDPOINT,
    DEFAULT_SYMBOL,
    FUTURES_DEPTH_SOURCE,
    probe_connection,
    probe_depth_snapshot,
)


class DxFeedDepthProbeTests(unittest.TestCase):
    def response(self, payload):
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        return response

    def test_quote_probe_reports_level1_size_component_separately(self):
        payload = {
            "status": "OK",
            "Quote": {
                DEFAULT_SYMBOL: {
                    "eventSymbol": DEFAULT_SYMBOL,
                    "bidPrice": 20000.0,
                    "askPrice": 20000.25,
                    "bidSize": 12,
                    "askSize": 9,
                }
            },
        }
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(payload)
            code, result = probe_connection(DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL)
        self.assertEqual(code, 0)
        self.assertTrue(result["quote_received"])
        self.assertTrue(result["quote_sizes_received"])
        self.assertTrue(result["research_eligibility"]["CMF_H3_live_capture_component"])
        self.assertFalse(result["research_eligibility"]["historical_quote_stream_verified"])
        self.assertNotIn("secret", json.dumps(result))

    @staticmethod
    def order_payload(levels_each_side: int):
        rows = []
        for i in range(levels_each_side):
            rows.append(
                {
                    "eventSymbol": DEFAULT_SYMBOL,
                    "orderSide": "BUY",
                    "price": 20000.0 - i * 0.25,
                    "size": i + 1,
                }
            )
            rows.append(
                {
                    "eventSymbol": DEFAULT_SYMBOL,
                    "orderSide": "SELL",
                    "price": 20000.25 + i * 0.25,
                    "size": i + 1,
                }
            )
        return {"status": "OK", "Order": {DEFAULT_SYMBOL: rows}}

    def test_depth_probe_verifies_top10_each_side_but_not_history(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(
                self.order_payload(10)
            )
            code, result = probe_depth_snapshot(
                DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL
            )
            request = factory.return_value.open.call_args.args[0]

        self.assertEqual(code, 0)
        self.assertTrue(result["current_depth_snapshot_verified"])
        self.assertEqual(result["bid_price_levels"], 10)
        self.assertEqual(result["ask_price_levels"], 10)
        self.assertTrue(result["top10_each_side_verified"])
        self.assertTrue(result["research_eligibility"]["CMF_H2_current_depth_component"])
        self.assertFalse(result["historical_depth_verified"])
        self.assertFalse(result["research_eligibility"]["CMF_H2_historical_replay"])
        self.assertIn("event=Order", request.full_url)
        self.assertIn(f"source={FUTURES_DEPTH_SOURCE}", request.full_url)
        self.assertNotIn("secret", json.dumps(result))

    def test_partial_depth_is_entitled_snapshot_but_not_h2_top10(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(
                self.order_payload(4)
            )
            code, result = probe_depth_snapshot(
                DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL
            )
        self.assertEqual(code, 0)
        self.assertTrue(result["current_depth_snapshot_verified"])
        self.assertFalse(result["top10_each_side_verified"])
        self.assertFalse(result["research_eligibility"]["CMF_H2_current_depth_component"])

    def test_empty_depth_fails_closed(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(
                {"status": "OK", "Order": {DEFAULT_SYMBOL: []}}
            )
            code, result = probe_depth_snapshot(
                DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL
            )
        self.assertEqual(code, 4)
        self.assertEqual(result["error_type"], "NoDepthSnapshot")
        self.assertFalse(result["current_depth_snapshot_verified"])


if __name__ == "__main__":
    unittest.main()

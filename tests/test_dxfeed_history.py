import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from orderflow_edge_lab.dxfeed import (
    DEFAULT_ENDPOINT,
    DEFAULT_SYMBOL,
    probe_history,
)


class DxFeedHistoryProbeTests(unittest.TestCase):
    def response(self, payload):
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        return response

    def test_historical_time_and_sale_success_reports_coverage_without_raw_events(self):
        payload = {
            "status": "OK",
            "TimeAndSale": {
                DEFAULT_SYMBOL: [
                    {
                        "eventSymbol": DEFAULT_SYMBOL,
                        "time": 1789723800000,
                        "sequence": 7,
                        "price": 25000.25,
                        "size": 3,
                        "bidPrice": 25000.00,
                        "askPrice": 25000.25,
                        "aggressorSide": "BUY",
                    },
                    {
                        "eventSymbol": DEFAULT_SYMBOL,
                        "time": 1789723800100,
                        "sequence": 8,
                        "price": 25000.00,
                        "size": 1,
                        "bidPrice": 25000.00,
                        "askPrice": 25000.25,
                        "aggressorSide": "SELL",
                    },
                ]
            },
        }
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(payload)
            code, result = probe_history(
                DEFAULT_ENDPOINT,
                "secret",
                DEFAULT_SYMBOL,
                "2026-09-18T13:30:00Z",
                "2026-09-18T13:31:00Z",
            )
            request = factory.return_value.open.call_args.args[0]

        self.assertEqual(code, 0)
        self.assertTrue(result["historical_access_verified"])
        self.assertTrue(result["time_and_sale_received"])
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["valid_price_events"], 2)
        self.assertEqual(result["events_with_size"], 2)
        self.assertEqual(result["events_with_bid_ask"], 2)
        self.assertEqual(result["events_with_aggressor_side"], 2)
        self.assertEqual(result["events_with_sequence"], 2)
        self.assertNotIn("TimeAndSale", result)
        self.assertNotIn("secret", json.dumps(result))
        self.assertIn("event=TimeAndSale", request.full_url)
        self.assertIn("fromTime=", request.full_url)
        self.assertIn("toTime=", request.full_url)

    def test_nested_symbol_container_can_omit_redundant_event_symbol(self):
        payload = {
            "status": "OK",
            "TimeAndSale": {
                DEFAULT_SYMBOL: [
                    {"price": 25000.25, "size": 2, "bidPrice": 25000, "askPrice": 25000.25}
                ]
            },
        }
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(payload)
            code, result = probe_history(
                DEFAULT_ENDPOINT,
                "secret",
                DEFAULT_SYMBOL,
                "2026-09-18T13:30:00Z",
                "2026-09-18T13:30:30Z",
            )
        self.assertEqual(code, 0)
        self.assertTrue(result["historical_access_verified"])

    def test_invalid_or_too_large_window_fails_before_network(self):
        for start, end in [
            ("2026-09-18T13:31:00Z", "2026-09-18T13:30:00Z"),
            ("2026-09-18T13:30:00Z", "2026-09-18T13:41:00Z"),
            ("2026-09-18T13:30:00", "2026-09-18T13:31:00"),
        ]:
            with self.subTest(start=start, end=end), patch("urllib.request.build_opener") as factory:
                code, result = probe_history(
                    DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL, start, end
                )
                self.assertEqual(code, 3)
                self.assertEqual(result["error_type"], "InvalidConfiguration")
                factory.assert_not_called()

    def test_empty_or_unrecognized_history_fails_closed(self):
        for payload in [
            {"status": "OK", "TimeAndSale": {DEFAULT_SYMBOL: []}},
            {"status": "OK", "TimeAndSale": {"OTHER": [{"price": 1.0}]}},
            {"status": "OK", "unexpected": []},
        ]:
            with self.subTest(payload=payload), patch("urllib.request.build_opener") as factory:
                factory.return_value.open.return_value.__enter__.return_value = self.response(payload)
                code, result = probe_history(
                    DEFAULT_ENDPOINT,
                    "secret",
                    DEFAULT_SYMBOL,
                    "2026-09-18T13:30:00Z",
                    "2026-09-18T13:31:00Z",
                )
                self.assertEqual(code, 4)
                self.assertFalse(result["historical_access_verified"])
                self.assertEqual(result["error_type"], "NoHistoricalTimeAndSale")

    def test_history_redirect_refuses_to_forward_auth(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError(
                DEFAULT_ENDPOINT,
                302,
                "Found",
                {"Location": "https://demo.dxfeed.com/webservice/rest/events.json"},
                io.BytesIO(),
            )
            code, result = probe_history(
                DEFAULT_ENDPOINT,
                "secret",
                DEFAULT_SYMBOL,
                "2026-09-18T13:30:00Z",
                "2026-09-18T13:31:00Z",
            )
            self.assertEqual(factory.return_value.open.call_count, 1)
        self.assertEqual(code, 3)
        self.assertTrue(result["redirect_to_public_demo"])
        self.assertNotIn("secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()

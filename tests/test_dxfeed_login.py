import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from orderflow_edge_lab.dxfeed import DEFAULT_ENDPOINT, DEFAULT_SYMBOL, probe_connection


class LoginTests(unittest.TestCase):
    def test_public_demo_redirect_is_identified_without_forwarding_auth(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError(
                DEFAULT_ENDPOINT, 302, "Found", {"Location": "https://demo.dxfeed.com/webservice/rest/events.json"}, io.BytesIO())
            code, result = probe_connection(DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL)
            self.assertEqual(factory.return_value.open.call_count, 1)
        self.assertEqual(code, 3)
        self.assertTrue(result["redirect_to_public_demo"])
        self.assertNotIn("secret", json.dumps(result))

    def response(self, payload):
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        return response

    def test_quote_success_does_not_certify_account_or_historical_rights(self):
        payload = {"status": "OK", "Quote": {DEFAULT_SYMBOL: {
            "eventSymbol": DEFAULT_SYMBOL, "bidPrice": 20000, "askPrice": 20000.25}}}
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response(payload)
            code, result = probe_connection(DEFAULT_ENDPOINT, None, DEFAULT_SYMBOL, username="user", password="secret")
        self.assertEqual(code, 0)
        self.assertTrue(result["quote_received"])
        self.assertFalse(result["account_entitlement_verified"])
        self.assertFalse(result["historical_access_verified"])

    def test_http_200_service_error_is_not_success(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value = self.response({"status": "ERROR", "message": "secret"})
            code, result = probe_connection(DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL)
        self.assertEqual(code, 4)
        self.assertNotIn("secret", json.dumps(result))

    def test_http_auth_denial_is_reported_without_body_or_headers(self):
        with patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError(DEFAULT_ENDPOINT, 401, "secret", {}, io.BytesIO(b"secret"))
            code, result = probe_connection(DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL)
        self.assertEqual(code, 3)
        self.assertEqual(result["http_status"], 401)
        self.assertNotIn("secret", json.dumps(result))

    def test_response_limit_and_wrong_symbol_do_not_pass_quote_check(self):
        with patch("urllib.request.build_opener") as factory:
            response = self.response({"status": "OK", "Quote": {"OTHER": {"bidPrice": 1, "askPrice": 2}}})
            factory.return_value.open.return_value.__enter__.return_value = response
            self.assertFalse(probe_connection(DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL)[1]["quote_received"])
            response.read.return_value = b"x" * 64_001
            self.assertEqual(probe_connection(DEFAULT_ENDPOINT, "secret", DEFAULT_SYMBOL)[0], 4)

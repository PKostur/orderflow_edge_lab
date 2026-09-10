import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error


spec = importlib.util.spec_from_file_location(
    "probe", Path(__file__).resolve().parents[1] / "scripts/dxfeed_entitlement_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_bad_endpoints_never_send_credentials(self):
        for endpoint in ("http://example.com", "https://u:p@example.com",
                         "https://example.com?token=secret", "https://example.com/#secret",
                         "https://example.com:bad", "https://example.com/\n"):
            with self.subTest(endpoint=endpoint), patch.object(probe.urllib.request, "build_opener") as opener:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.probe_rest(endpoint, "secret", "NQ"), 3)
                opener.assert_not_called()

    def test_server_errors_and_bodies_are_not_logged(self):
        for failure in (False, True):
            with self.subTest(failure=failure), patch.object(probe.urllib.request, "build_opener") as factory:
                response = MagicMock()
                response.status = 200
                response.read.return_value = b"secret-token"
                factory.return_value.open.return_value.__enter__.return_value = response
                if failure:
                    factory.return_value.open.side_effect = OSError("secret-token")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = probe.probe_rest("https://example.com/events", "secret-token", "NQ")
                self.assertEqual(result, 3 if failure else 0)
                self.assertNotIn("secret-token", output.getvalue())

    def test_redirect_is_refused(self):
        handler = probe._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://other.test"))

    def test_basic_auth_is_supported_without_logging_credentials(self):
        import base64
        with patch.object(probe.urllib.request, "build_opener") as factory:
            response = MagicMock()
            response.status = 200
            response.read.return_value = b""
            factory.return_value.open.return_value.__enter__.return_value = response
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(probe.probe_rest("https://example.com/events", None, "NQ",
                                                 username="partner-user", password="secret-password"), 0)
            request = factory.return_value.open.call_args.args[0]
            encoded = base64.b64encode(b"partner-user:secret-password").decode()
            self.assertEqual(request.get_header("Authorization"), "Basic " + encoded)
            for value in ("partner-user", "secret-password", encoded):
                self.assertNotIn(value, output.getvalue())

    def test_mixed_or_incomplete_auth_fails_without_network(self):
        for token, username, password in (("token", "user", "password"), (None, "user", None),
                                          (None, "user:invalid", "password")):
            with patch.object(probe.urllib.request, "build_opener") as factory:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.probe_rest("https://example.com", token, "NQ",
                                                     username=username, password=password), 3)
                factory.assert_not_called()

    def test_nonempty_bad_export_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trades.csv"
            path.write_text("timestamp,symbol,price,bid,ask\n2026-09-01T00:00:00Z,NQ,100,102,101\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.probe_export(str(path), None), 2)

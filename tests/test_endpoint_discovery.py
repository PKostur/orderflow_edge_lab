import json
import subprocess
import unittest

from orderflow_edge_lab.endpoint_discovery import (
    classify_dxfeed,
    discover_windows_endpoints,
    discovery_report,
    normalize_rows,
)


class EndpointDiscoveryTests(unittest.TestCase):
    def test_hostname_classification(self):
        self.assertTrue(classify_dxfeed("feed.dxfeed.com", 443))
        self.assertTrue(classify_dxfeed("DXFEED.EXAMPLE.COM.", 443))
        self.assertTrue(classify_dxfeed(None, 7300))
        self.assertFalse(classify_dxfeed("example.com", 443))

    def test_normalize_rows_filters_invalid_and_deduplicates(self):
        rows = [
            {"ProcessName": "VolumetricaBridge", "PID": 42, "RemoteAddress": "203.0.113.10", "RemotePort": 443, "State": "Established"},
            {"ProcessName": "VolumetricaBridge", "PID": 42, "RemoteAddress": "203.0.113.10", "RemotePort": 443, "State": "Established"},
            {"ProcessName": "VolumetricaBridge", "PID": 42, "RemoteAddress": "not-an-ip", "RemotePort": 443, "State": "Established"},
            {"ProcessName": "", "PID": 42, "RemoteAddress": "203.0.113.11", "RemotePort": 7300, "State": "Established"},
        ]

        def resolver(address):
            return ("customer.dxfeed.com", [], [address])

        result = normalize_rows(rows, resolver=resolver)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].remote_address, "203.0.113.10")
        self.assertEqual(result[0].reverse_dns, "customer.dxfeed.com")
        self.assertTrue(result[0].likely_dxfeed)

    def test_discover_parses_single_powershell_object(self):
        payload = {
            "ProcessName": "VolumetricaBridge",
            "PID": 100,
            "RemoteAddress": "198.51.100.7",
            "RemotePort": 7300,
            "State": "Established",
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr="")

        def resolver(address):
            raise OSError("no PTR")

        result = discover_windows_endpoints(("VolumetricaBridge",), runner=runner, resolver=resolver)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].reverse_dns)
        self.assertTrue(result[0].likely_dxfeed)

    def test_discover_does_not_expose_powershell_error_text(self):
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="secret-bearing diagnostic")

        with self.assertRaisesRegex(RuntimeError, "intentionally not persisted"):
            discover_windows_endpoints(("VolumetricaBridge",), runner=runner)

    def test_report_is_explicitly_non_authenticating(self):
        report = discovery_report([])
        self.assertFalse(report["credential_access"])
        self.assertEqual(report["endpoint_count"], 0)
        self.assertEqual(report["likely_dxfeed_count"], 0)
        self.assertTrue(any("not cryptographic proof" in item for item in report["limitations"]))


if __name__ == "__main__":
    unittest.main()

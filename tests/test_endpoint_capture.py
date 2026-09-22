from copy import deepcopy
import unittest

from orderflow_edge_lab.endpoint_capture import EndpointCaptureError, analyze_capture


class EndpointCaptureTests(unittest.TestCase):
    def base_report(self):
        return {
            "schema_version": 1,
            "method": "powershell_established_tcp_watch",
            "started_at_utc": "2026-09-11T08:00:00+00:00",
            "ended_at_utc": "2026-09-11T08:00:45+00:00",
            "duration_seconds": 45,
            "interval_milliseconds": 750,
            "sample_count": 60,
            "credential_access": False,
            "process_memory_access": False,
            "command_line_access": False,
            "endpoint_count": 1,
            "observations": [
                {
                    "process_name": "VolumetricaBridge",
                    "pid": 1234,
                    "remote_address": "203.0.113.10",
                    "remote_port": 443,
                    "reverse_dns": "customer.dxfeed.com",
                    "confidence": "high",
                    "evidence": ["reverse_dns_contains_dxfeed", "tls_port_443"],
                    "first_seen_utc": "2026-09-11T08:00:02+00:00",
                    "last_seen_utc": "2026-09-11T08:00:42+00:00",
                    "samples_seen": 20,
                }
            ],
        }

    def test_explicit_dxfeed_dns_yields_network_candidate_but_never_api_authorization(self):
        result = analyze_capture(self.base_report())
        self.assertTrue(result["candidate_is_unambiguous"])
        self.assertEqual(result["candidate"]["remote_address"], "203.0.113.10")
        self.assertGreaterEqual(result["candidate"]["score"], 100)
        self.assertTrue(result["candidate"]["provider_candidate_eligible"])
        self.assertEqual(result["candidate"]["network_scope"], "public")
        self.assertFalse(result["external_api_authorized"])
        self.assertFalse(result["safe_for_independent_connection"])
        self.assertIn("entitlement", result["next_gate"])

    def test_port_7300_is_only_indicator(self):
        report = self.base_report()
        row = report["observations"][0]
        row.update({
            "remote_port": 7300,
            "reverse_dns": None,
            "confidence": "medium",
            "evidence": ["remote_port_7300"],
        })
        result = analyze_capture(report)
        self.assertTrue(result["candidate_is_unambiguous"])
        self.assertIn("native_demo_port_indicator", result["candidate"]["reasons"])
        self.assertFalse(result["safe_for_independent_connection"])

    def test_generic_tls_alone_is_not_promoted_to_candidate(self):
        report = self.base_report()
        row = report["observations"][0]
        row.update({
            "reverse_dns": "example.net",
            "confidence": "low",
            "evidence": ["tls_port_443"],
        })
        result = analyze_capture(report)
        self.assertIsNone(result["candidate"])
        self.assertFalse(result["candidate_is_unambiguous"])

    def test_repeated_generic_tls_still_is_not_promoted(self):
        report = self.base_report()
        row = report["observations"][0]
        row.update({
            "reverse_dns": "ec2-203-0-113-10.compute.amazonaws.com",
            "confidence": "low",
            "evidence": ["tls_port_443"],
            "samples_seen": 50,
        })
        result = analyze_capture(report)
        self.assertIsNone(result["candidate"])
        self.assertFalse(result["candidate_is_unambiguous"])
        self.assertIn("repeated_observation", result["ranked_endpoints"][0]["reasons"])
        self.assertFalse(result["ranked_endpoints"][0]["provider_candidate_eligible"])

    def test_loopback_native_port_never_becomes_provider_candidate(self):
        report = self.base_report()
        row = report["observations"][0]
        row.update({
            "remote_address": "::1",
            "remote_port": 7300,
            "reverse_dns": "localhost",
            "confidence": "medium",
            "evidence": ["remote_port_7300"],
        })
        result = analyze_capture(report)
        self.assertIsNone(result["candidate"])
        self.assertFalse(result["candidate_is_unambiguous"])
        self.assertTrue(result["local_bridge_observed"])
        self.assertEqual(result["local_bridge_ports"], [7300])
        ranked = result["ranked_endpoints"][0]
        self.assertEqual(ranked["network_scope"], "loopback")
        self.assertFalse(ranked["provider_candidate_eligible"])
        self.assertIn("local_loopback_peer", ranked["reasons"])
        self.assertIn("supported DeepCharts export", result["next_gate"])

    def test_loopback_bridge_ports_are_reported_separately(self):
        report = self.base_report()
        report["observations"] = []
        for port in (20024, 20025, 20026, 20027):
            row = deepcopy(self.base_report()["observations"][0])
            row.update({
                "process_name": "Deepchart",
                "remote_address": "::1",
                "remote_port": port,
                "reverse_dns": "desktop-local",
                "confidence": "unclassified",
                "evidence": [],
                "samples_seen": 5,
            })
            report["observations"].append(row)
        report["endpoint_count"] = 4
        result = analyze_capture(report)
        self.assertTrue(result["local_bridge_observed"])
        self.assertEqual(result["local_bridge_ports"], [20024, 20025, 20026, 20027])
        self.assertEqual(result["public_endpoint_count"], 0)
        self.assertEqual(result["nonpublic_endpoint_count"], 4)
        self.assertIsNone(result["candidate"])
        self.assertFalse(result["safe_for_independent_connection"])

    def test_tied_high_signal_candidates_fail_closed(self):
        report = self.base_report()
        second = deepcopy(report["observations"][0])
        second["remote_address"] = "203.0.113.11"
        second["reverse_dns"] = "backup.dxfeed.com"
        report["observations"].append(second)
        report["endpoint_count"] = 2
        result = analyze_capture(report)
        self.assertIsNone(result["candidate"])
        self.assertFalse(result["candidate_is_unambiguous"])

    def test_sensitive_access_flags_must_be_false(self):
        for field in ("credential_access", "process_memory_access", "command_line_access"):
            report = self.base_report()
            report[field] = True
            with self.subTest(field=field), self.assertRaises(EndpointCaptureError):
                analyze_capture(report)

    def test_declared_count_and_evidence_consistency_are_enforced(self):
        report = self.base_report()
        report["endpoint_count"] = 2
        with self.assertRaisesRegex(EndpointCaptureError, "endpoint_count"):
            analyze_capture(report)

        report = self.base_report()
        report["observations"][0]["reverse_dns"] = "example.net"
        with self.assertRaisesRegex(EndpointCaptureError, "inconsistent"):
            analyze_capture(report)

    def test_invalid_time_order_is_rejected(self):
        report = self.base_report()
        report["ended_at_utc"] = report["started_at_utc"]
        with self.assertRaisesRegex(EndpointCaptureError, "positive duration"):
            analyze_capture(report)

        report = self.base_report()
        report["observations"][0]["last_seen_utc"] = "2026-09-11T07:59:59+00:00"
        with self.assertRaisesRegex(EndpointCaptureError, "precedes"):
            analyze_capture(report)


if __name__ == "__main__":
    unittest.main()

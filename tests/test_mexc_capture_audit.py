import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.mexc_capture_audit import CaptureAuditPolicy, audit_capture


class MexcCaptureAuditTests(unittest.TestCase):
    def _write_capture(self, td: str, *, stale_depth: bool = False, gaps: int = 0):
        root = Path(td)
        raw = root / "sample_mexc_raw.jsonl"
        features = root / "sample_mexc_features.jsonl"
        start = 1_780_000_000_000_000_000
        end = start + 120_000_000_000

        raw_rows = [
            {"record_type": "session", "received_at_ns": start},
            {"record_type": "rest_snapshot", "symbol": "ENA_USDT", "received_at_ns": start},
        ]
        for i in range(gaps):
            raw_rows.extend(
                [
                    {"record_type": "depth_gap", "symbol": "ENA_USDT", "received_at_ns": start + i + 1},
                    {"record_type": "rest_depth_commits", "symbol": "ENA_USDT", "received_at_ns": start + i + 1},
                ]
            )
        raw_rows.append({"record_type": "ws_message", "symbol": "ENA_USDT", "received_at_ns": end})
        raw.write_text("".join(json.dumps(row) + "\n" for row in raw_rows), encoding="utf-8")

        feature_rows = []
        for i in range(100):
            feature_rows.append(
                {
                    "event_type": "depth",
                    "symbol": "ENA_USDT",
                    "received_at_ns": start + i * 1_000_000_000,
                    "depth_applied": not stale_depth or i < 10,
                    "best_bid": 100.0,
                    "best_ask": 101.0,
                }
            )
        feature_rows.append(
            {
                "event_type": "trade",
                "symbol": "ENA_USDT",
                "received_at_ns": end,
                "best_bid": 100.0,
                "best_ask": 101.0,
            }
        )
        features.write_text("".join(json.dumps(row) + "\n" for row in feature_rows), encoding="utf-8")

        for path in (raw, features):
            manifest = {
                "schema_version": 1,
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            path.with_name(path.name + ".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return raw, features

    def test_clean_capture_passes_integrity_gate(self):
        with tempfile.TemporaryDirectory() as td:
            raw, features = self._write_capture(td)
            report = audit_capture(raw, features)
            self.assertTrue(report.passed)
            self.assertEqual(report.symbols[0].depth_apply_fraction, 1.0)
            self.assertTrue(report.raw_manifest_valid)
            self.assertTrue(report.features_manifest_valid)

    def test_stale_depth_heavy_capture_fails(self):
        with tempfile.TemporaryDirectory() as td:
            raw, features = self._write_capture(td, stale_depth=True)
            report = audit_capture(raw, features)
            self.assertFalse(report.passed)
            self.assertIn("ENA_USDT:low_depth_apply_fraction", report.failures)

    def test_gap_storm_fails(self):
        with tempfile.TemporaryDirectory() as td:
            raw, features = self._write_capture(td, gaps=10)
            report = audit_capture(raw, features, policy=CaptureAuditPolicy(max_gap_rate_per_minute=1.0))
            self.assertFalse(report.passed)
            self.assertIn("ENA_USDT:excessive_depth_gap_rate", report.failures)

    def test_manifest_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            raw, features = self._write_capture(td)
            raw.write_text(raw.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            report = audit_capture(raw, features)
            self.assertFalse(report.passed)
            self.assertIn("raw_manifest_invalid", report.failures)


if __name__ == "__main__":
    unittest.main()

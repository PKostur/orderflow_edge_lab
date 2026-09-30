"""Tests for the daily wait-window ops digest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.ops_digest import build_ops_digest, digest_markdown
from orderflow_edge_lab.review_clock import DEFAULT_CONFIG as CLOCK_CONFIG

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _write_capture(root: Path, ts: str, kind: str) -> None:
    name = f"{ts}_mexc_{kind}.jsonl"
    (root / name).write_bytes(b'{"symbol":"ENA_USDT"}\n')
    (root / f"{name}.manifest.json").write_text("{}", encoding="utf-8")


class DigestTests(unittest.TestCase):
    def test_fresh_capture_and_manifest_report_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = root / "captures"
            captures.mkdir()
            _write_capture(captures, "20260929T110000Z", "raw")
            _write_capture(captures, "20260929T110000Z", "features")
            manifest = root / "ledger.json"
            manifest.write_text(
                json.dumps({"batch_count": 157, "updated_at_utc": "2026-09-29T11:30:00Z"}),
                encoding="utf-8",
            )
            digest = build_ops_digest(
                clock_config=CLOCK_CONFIG,
                data_dir=captures,
                ledger_manifest=manifest,
                now=NOW,
            )
            self.assertEqual(digest["digest_status"], "ok")
            self.assertEqual(digest["ledger"]["batch_count"], 157)
            self.assertFalse(digest["capture_health"]["stale"])
            self.assertEqual(digest["capture_health"]["capture_counts"]["complete"], 1)
            self.assertIn(
                "evidence_v2_cross_strategy_session_forward_v1",
                " ".join(w["watch_id"] for w in digest["watch_clock"]["watches"]),
            )

    def test_stopped_capture_raises_attention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = root / "captures"
            captures.mkdir()
            _write_capture(captures, "20260920T110000Z", "raw")
            _write_capture(captures, "20260920T110000Z", "features")
            digest = build_ops_digest(
                clock_config=CLOCK_CONFIG,
                data_dir=captures,
                ledger_manifest=None,
                now=NOW,
                stale_after_hours=26.0,
            )
            self.assertEqual(digest["digest_status"], "attention_required")
            codes = {alert["code"] for alert in digest["alerts"]}
            self.assertIn("capture_no_recent_capture", codes)
            self.assertIn("capture_capture_stopped", codes)
            self.assertIn("ledger_manifest_unavailable", codes)
            self.assertEqual(digest["highest_alert_severity"], "error")

    def test_absent_directory_is_reported_not_fatal(self):
        digest = build_ops_digest(
            clock_config=CLOCK_CONFIG,
            data_dir=Path("definitely/not/here"),
            ledger_manifest=None,
            now=NOW,
        )
        codes = {alert["code"] for alert in digest["alerts"]}
        self.assertIn("capture_directory_absent", codes)
        self.assertFalse(digest["capture_health"]["data_dir_exists"])

    def test_coverage_report_is_folded_in(self):
        coverage = {
            "requirements_total": 4,
            "requirements_satisfied": 3,
            "coverage_ok": False,
            "report_sha256": "a" * 64,
            "findings": [
                {"severity": "error", "code": "artifact_missing", "requirement_id": "r1", "detail": "gone"}
            ],
        }
        digest = build_ops_digest(
            clock_config=CLOCK_CONFIG,
            data_dir=Path("definitely/not/here"),
            ledger_manifest=None,
            coverage_report=coverage,
            now=NOW,
        )
        self.assertEqual(digest["coverage"]["report_sha256"], "a" * 64)
        codes = {alert["code"] for alert in digest["alerts"]}
        self.assertIn("coverage_artifact_missing", codes)

    def test_unicode_free_markdown_and_self_hash(self):
        digest = build_ops_digest(
            clock_config=CLOCK_CONFIG,
            data_dir=Path("definitely/not/here"),
            ledger_manifest=None,
            now=NOW,
        )
        text = digest_markdown(digest)
        self.assertIn("# Wait-window ops digest", text)
        canonical = json.dumps(
            {key: value for key, value in digest.items() if key != "digest_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), digest["digest_sha256"])

    def test_claims_and_determinism(self):
        first = build_ops_digest(clock_config=CLOCK_CONFIG, data_dir=Path("x"), ledger_manifest=None, now=NOW)
        second = build_ops_digest(clock_config=CLOCK_CONFIG, data_dir=Path("x"), ledger_manifest=None, now=NOW)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        claims = first["claims"]
        self.assertFalse(claims["computes_strategy_verdicts"])
        self.assertFalse(claims["counts_prospective_batches"])
        self.assertFalse(claims["promotes_any_strategy"])
        self.assertFalse(claims["live_order_transmission_supported"])

    def test_ledger_manifest_reads_the_committed_archive(self):
        committed = Path("research/DISCOVERY_LEDGER_MANIFEST_2026_09_29.json")
        if not committed.is_file():
            self.skipTest("committed ledger manifest not present")
        digest = build_ops_digest(
            clock_config=CLOCK_CONFIG,
            data_dir=Path("definitely/not/here"),
            ledger_manifest=committed,
            now=NOW,
        )
        self.assertTrue(digest["ledger"]["available"])
        self.assertEqual(digest["ledger"]["batch_count"], 157)


if __name__ == "__main__":
    unittest.main()

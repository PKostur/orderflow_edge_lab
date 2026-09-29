"""Tests for the descriptive MEXC capture health summary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.capture_health import (
    build_health_summary,
    peek_symbols,
    scan_capture_directory,
)

TS = "20260920T120000Z"


def _write_capture(root: Path, ts: str, kind: str, *, manifest: bool = True, partial: bool = False, body: bytes = b"") -> None:
    name = f"{ts}_mexc_{kind}.jsonl{'.partial' if partial else ''}"
    (root / name).write_bytes(body)
    if manifest and not partial:
        (root / f"{name}.manifest.json").write_text("{}", encoding="utf-8")


class ScanTests(unittest.TestCase):
    def test_missing_directory_is_reported_not_fatal(self):
        inventory = scan_capture_directory(Path("definitely/not/here"))
        self.assertFalse(inventory["exists"])
        self.assertEqual(inventory["captures"], [])

    def test_recognizes_complete_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_capture(root, TS, "raw", body=b'{"symbol":"ENA_USDT"}\n')
            _write_capture(root, TS, "features")
            inventory = scan_capture_directory(root)
            self.assertEqual(len(inventory["captures"]), 1)
            entry = inventory["captures"][0]
            self.assertTrue(entry["raw_manifest_present"])
            self.assertTrue(entry["features_manifest_present"])
            self.assertEqual(entry["symbols_observed"], ["ENA_USDT"])

    def test_orphans_are_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "random_note.txt").write_text("x", encoding="utf-8")
            inventory = scan_capture_directory(root)
            self.assertEqual(inventory["orphans"], ["random_note.txt"])

    def test_peek_symbols_tolerates_bad_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl"
            path.write_bytes(b'not json\n{"symbol":"BTC_USDT"}\n\n{"other":1}\n', )
            self.assertEqual(peek_symbols(path), ["BTC_USDT"])


class SummaryTests(unittest.TestCase):
    def test_counts_and_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_capture(root, "20260919T100000Z", "raw")
            _write_capture(root, "20260919T100000Z", "features")
            _write_capture(root, "20260920T120000Z", "raw", manifest=False)
            _write_capture(root, "20260921T080000Z", "features", partial=True)
            now = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
            report = build_health_summary(root, now=now, stale_after_hours=26.0)
            self.assertEqual(report["capture_counts"]["complete"], 1)
            self.assertEqual(report["capture_counts"]["interrupted"], 1)
            self.assertEqual(report["capture_counts"]["missing_manifests"], 1)
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("raw_manifest_missing", codes)
            self.assertIn("interrupted_capture", codes)
            self.assertEqual(report["newest_capture_started_utc"], "2026-09-21T08:00:00Z")
            self.assertEqual(report["hours_since_newest_capture"], 1.0)
            self.assertFalse(report["stale"])

    def test_stale_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_capture(root, TS, "raw")
            _write_capture(root, TS, "features")
            now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)  # 24h later
            fresh = build_health_summary(root, now=now, stale_after_hours=26.0)
            self.assertFalse(fresh["stale"])
            later = build_health_summary(root, now=now + timedelta(hours=3), stale_after_hours=26.0)
            self.assertTrue(later["stale"])

    def test_empty_existing_directory_finding(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_health_summary(Path(directory))
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("no_captures_found", codes)

    def test_claims_and_self_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_health_summary(Path(directory))
            self.assertFalse(report["claims"]["counts_prospective_batches"])
            self.assertFalse(report["claims"]["certifies_data_quality"])
            self.assertFalse(report["claims"]["live_order_transmission_supported"])
            canonical = json.dumps(
                {k: v for k, v in report.items() if k != "report_sha256"},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            import hashlib

            self.assertEqual(
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                report["report_sha256"],
            )

    def test_deterministic_for_fixed_now(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_capture(root, TS, "raw")
            _write_capture(root, TS, "features")
            now = datetime(2026, 9, 21, tzinfo=timezone.utc)
            first = build_health_summary(root, now=now)
            second = build_health_summary(root, now=now)
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class GuardTests(unittest.TestCase):
    def test_impossible_timestamp_is_flagged_not_swallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "20260920T120000Z_mexc_raw.jsonl").write_bytes(b"")  # valid group
            (root / "20260920T120000Z_mexc_raw.jsonl.manifest.json").write_text("{}", encoding="utf-8")
            (root / "99999999T999999Z_mexc_features.jsonl").write_bytes(b"")
            # The name regex accepts the impossible timestamp as format-valid;
            # the summary must surface it as an error finding, never crash,
            # and never let it poison the staleness computation.
            report = build_health_summary(root)
            codes = {(f["code"], f["severity"]) for f in report["findings"]}
            self.assertIn(("unparsable_capture_timestamp", "error"), codes)
            self.assertEqual(report["capture_counts"]["total_groups"], 2)
            self.assertEqual(report["newest_capture_started_utc"], "2026-09-20T12:00:00Z")


if __name__ == "__main__":
    unittest.main()

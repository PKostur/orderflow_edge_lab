"""Tests for the observability-only prospective review clock."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.review_clock import (
    ReviewClockError,
    clock_report,
    load_clock_config,
    parse_utc,
    review_target,
)

REPO_CONFIG = Path("config/prospective_review_clock_v1.json")


def _write_config(root: Path, payload: dict) -> Path:
    path = root / "clock.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sample_watch(**overrides) -> dict:
    watch = {
        "watch_id": "TEST_WATCH",
        "priority": 1,
        "family": "test_family",
        "prospective_start_utc": "2026-01-01T00:00:00Z",
        "review_gate": {"type": "calendar_days", "minimum_days": 30},
        "canonical_artifacts": ["docs/example.md"],
    }
    watch.update(overrides)
    return watch


def _sample_config(**watch_overrides) -> dict:
    return {
        "schema_version": 1,
        "protocol_name": "test-clock",
        "status": "observability_only",
        "watches": [_sample_watch(**watch_overrides)],
    }


class ParseUtcTests(unittest.TestCase):
    def test_parses_z_suffix(self):
        self.assertEqual(
            parse_utc("2026-01-01T00:00:00Z", "test"),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_parses_offset_and_normalizes(self):
        self.assertEqual(
            parse_utc("2026-01-01T02:00:00+02:00", "test"),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_rejects_naive_and_garbage(self):
        with self.assertRaisesRegex(ReviewClockError, "UTC offset"):
            parse_utc("2026-01-01T00:00:00", "test")
        with self.assertRaises(ReviewClockError):
            parse_utc("not-a-time", "test")


class ConfigTests(unittest.TestCase):
    def test_repo_config_loads_and_matches_freeze_document(self):
        payload = load_clock_config(REPO_CONFIG)
        ids = [w["watch_id"] for w in payload["watches"]]
        self.assertIn("evidence_v2_cross_strategy_session_forward_v1", ids)
        self.assertIn("SESSION_W1_ALIGNED_SHORT_ASIA_OPENING", ids)
        self.assertIn("SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING", ids)
        self.assertIn("SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST", ids)

    def test_w3_watch_id_matches_the_frozen_pipeline_id(self):
        # The clock must report the frozen watch_id verbatim: the ID in
        # config/session_development_watch_v1.json carries no version suffix.
        clock_ids = {w["watch_id"] for w in load_clock_config(REPO_CONFIG)["watches"]}
        frozen = json.loads(
            Path("config/session_development_watch_v1.json").read_text(encoding="utf-8")
        )
        for watch in frozen["watches"]:
            if str(watch["watch_id"]).startswith("SESSION_W3"):
                self.assertIn(watch["watch_id"], clock_ids)

    def test_malformed_configs_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [
                {"no_watches_key": True},
                {"watches": []},
                {"watches": [{"prospective_start_utc": "2026-01-01T00:00:00Z"}]},
                {
                    "watches": [
                        {
                            "watch_id": "X",
                            "prospective_start_utc": "2026-01-01T00:00:00Z",
                        }
                    ]
                },
            ]
            for payload in cases:
                path = _write_config(root, payload)
                with self.assertRaises(ReviewClockError):
                    load_clock_config(path)


class ReviewTargetTests(unittest.TestCase):
    def test_calendar_days_gate_produces_target(self):
        target = review_target(_sample_watch())
        self.assertEqual(target, datetime(2026, 1, 31, tzinfo=timezone.utc))

    def test_count_gate_has_no_derivable_target(self):
        watch = _sample_watch(
            review_gate={"type": "batches_and_days", "minimum_batches": 10, "minimum_days": 5}
        )
        self.assertIsNone(review_target(watch))

    def test_negative_days_rejected(self):
        with self.assertRaises(ReviewClockError):
            review_target(
                _sample_watch(review_gate={"type": "calendar_days", "minimum_days": -1})
            )


class ClockReportTests(unittest.TestCase):
    def test_report_before_start(self):
        config = _write_config(Path(tempfile.mkdtemp()), _sample_config())
        now = datetime(2025, 12, 15, tzinfo=timezone.utc)
        report = clock_report(config, now=now)
        watch = report["watches"][0]
        self.assertFalse(watch["started"])
        self.assertAlmostEqual(watch["elapsed_days"], -17.0)
        self.assertEqual(watch["earliest_review_utc"], "2026-01-31T00:00:00Z")
        self.assertAlmostEqual(watch["days_until_earliest_review"], 47.0)
        self.assertFalse(watch["review_window_matured"])
        self.assertTrue(report["summary"]["all_windows_still_accumulating"])

    def test_report_midwindow_and_at_boundary(self):
        root = Path(tempfile.mkdtemp())
        config = _write_config(root, _sample_config())
        mid = clock_report(config, now=datetime(2026, 1, 16, tzinfo=timezone.utc))
        self.assertAlmostEqual(mid["watches"][0]["elapsed_days"], 15.0)
        self.assertAlmostEqual(mid["watches"][0]["days_until_earliest_review"], 15.0)
        self.assertFalse(mid["watches"][0]["review_window_matured"])
        boundary = clock_report(config, now=datetime(2026, 1, 31, tzinfo=timezone.utc))
        self.assertTrue(boundary["watches"][0]["review_window_matured"])
        self.assertAlmostEqual(boundary["watches"][0]["days_until_earliest_review"], 0.0)
        self.assertFalse(boundary["summary"]["all_windows_still_accumulating"])

    def test_count_gate_report_carries_note_and_authority(self):
        config = _write_config(
            Path(tempfile.mkdtemp()),
            _sample_config(
                review_gate={
                    "type": "signals_batches_and_days",
                    "minimum_signals": 20,
                    "minimum_batches": 8,
                    "minimum_days": 7,
                },
                batch_counting="frozen pipeline",
            ),
        )
        report = clock_report(config, now=datetime(2026, 2, 1, tzinfo=timezone.utc))
        watch = report["watches"][0]
        self.assertIsNone(watch["earliest_review_utc"])
        self.assertIsNone(watch["review_window_matured"])
        self.assertIn("frozen", watch["note"])
        self.assertEqual(watch["counting_authority"], "frozen pipeline")

    def test_report_claims_stay_safety_preserving(self):
        report = clock_report(REPO_CONFIG)
        self.assertEqual(report["status"], "observability_only")
        claims = report["claims"]
        self.assertFalse(claims["computes_strategy_verdicts"])
        self.assertFalse(claims["inspects_strategy_pnl"])
        self.assertFalse(claims["promotes_any_strategy"])
        self.assertFalse(claims["live_order_transmission_supported"])
        don8 = next(
            w
            for w in report["watches"]
            if w["watch_id"] == "evidence_v2_cross_strategy_session_forward_v1"
        )
        self.assertEqual(don8["earliest_review_utc"], "2026-10-23T00:00:00Z")

    def test_terminal_watches_are_marked_and_not_counted_as_open(self):
        report = clock_report(REPO_CONFIG, now=datetime(2026, 9, 29, tzinfo=timezone.utc))
        by_id = {watch["watch_id"]: watch for watch in report["watches"]}
        self.assertEqual(by_id["SESSION_W1_ALIGNED_SHORT_ASIA_OPENING"]["terminal_state"], "FALSIFIED")
        self.assertEqual(by_id["SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING"]["terminal_state"], "FALSIFIED")
        self.assertFalse(by_id["SESSION_W1_ALIGNED_SHORT_ASIA_OPENING"]["open_watch"])
        self.assertTrue(by_id["evidence_v2_cross_strategy_session_forward_v1"]["open_watch"])
        self.assertTrue(by_id["SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST"]["open_watch"])
        self.assertEqual(report["summary"]["open_watch_count"], 2)
        self.assertEqual(report["summary"]["terminal_watch_count"], 2)

    def test_report_is_deterministic_for_fixed_now(self):
        first = clock_report(REPO_CONFIG, now=datetime(2026, 9, 29, tzinfo=timezone.utc))
        second = clock_report(REPO_CONFIG, now=datetime(2026, 9, 29, tzinfo=timezone.utc))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


if __name__ == "__main__":
    unittest.main()

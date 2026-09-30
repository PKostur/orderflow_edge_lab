"""Tests for the review packet skeleton generator."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import unittest

from orderflow_edge_lab.review_packet import (
    DEFAULT_FORWARD_WATCH_CONFIG,
    DEFAULT_SESSION_WATCH_CONFIG,
    ReviewPacketError,
    build_review_packet,
    review_packet_markdown,
)

NOW = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
COMMITTED_REPORT = Path("research/SESSION_WATCH_REPORT_2026_09_29.json")
COMMITTED_FALSIFIED_WATCH = "SESSION_W1_ALIGNED_SHORT_ASIA_OPENING"


def _session_report(*, ready: bool = True, signals: int = 24) -> dict:
    return {
        "schema_version": 1,
        "analysis": "prospective_session_development_watch",
        "symbol": "ENA_USDT",
        "prospective_watch_start_utc": "2026-09-22T15:39:58Z",
        "watches": [
            {
                "watch_id": "SESSION_TEST_1",
                "family": "aligned",
                "direction": "SHORT",
                "session_phase": "ASIA_OPENING",
                "conditions": None,
                "prospective_watch_start_utc": "2026-09-22T15:39:58Z",
                "prospective_unique_signals": signals,
                "prospective_independent_batches": 10,
                "prospective_calendar_days": 6,
                "review_requirement": {
                    "minimum_new_signals": 0,
                    "minimum_new_independent_batches": 10,
                    "minimum_new_calendar_days": 5,
                },
                "ready_for_review": ready,
                "status": "READY_FOR_REVIEW" if ready else "ACCUMULATING",
                "cells": [
                    {
                        "horizon_ms": 30000,
                        "fee_bps_round_trip": 4.0,
                        "observations": signals,
                        "independent_batches": 10,
                        "gross_mean_bps": 1.5,
                        "net_mean_bps": -2.5,
                        "cumulative_net_bps": -60.0,
                        "profit_factor": 0.5,
                    }
                ],
            }
        ],
    }


def _forward_report(*, days_elapsed: float) -> dict:
    return {
        "watch_id": "evidence_v2_cross_strategy_session_forward_v1",
        "status": "ACCUMULATING",
        "as_of_utc": "2026-09-29T16:00:00Z",
        "days_elapsed": days_elapsed,
        "primary_observation": {"DON8": {"compounded_return": 0.01}},
        "prospective_start_utc": "2026-09-23T00:00:00+00:00",
        "claims": {"candidate_promoted": False, "live_trading_authorized": False, "leverage_authorized": False},
    }


class SessionWatchPacketTests(unittest.TestCase):
    def build(self, report: dict) -> dict:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            return build_review_packet(path, session_watch_config=DEFAULT_SESSION_WATCH_CONFIG, now=NOW)

    def test_counts_are_copied_verbatim_and_verdicts_stay_empty(self):
        packet = self.build(_session_report(signals=24))
        watch = packet["watches"][0]
        self.assertEqual(watch["pipeline_counts"]["prospective_unique_signals"], 24)
        self.assertEqual(watch["pipeline_status"], "READY_FOR_REVIEW")
        self.assertEqual(packet["open_verdict_cells"], 1)
        for cell in watch["cells_awaiting_verdict"]:
            self.assertIsNone(cell["verdict"])
            self.assertTrue(cell["verdict_requires_human_review"])
            self.assertEqual(cell["pipeline_reported_metrics"]["net_mean_bps"], -2.5)

    def test_packet_never_claims_a_verdict(self):
        packet = self.build(_session_report())
        claims = packet["claims"]
        self.assertFalse(claims["computes_strategy_verdicts"])
        self.assertFalse(claims["inspects_strategy_pnl"])
        self.assertFalse(claims["recomputes_pipeline_counts"])
        self.assertFalse(claims["promotes_any_strategy"])
        self.assertFalse(claims["live_order_transmission_supported"])
        self.assertEqual(packet["status"], "skeleton_only")
        self.assertIn("no verdict", " ".join(packet["notes"]))

    def test_unready_watch_is_marked_awaiting_window(self):
        packet = self.build(_session_report(ready=False))
        self.assertEqual(packet["packet_status"], "AWAITING_REVIEW_WINDOW")
        self.assertFalse(packet["window_matured"])
        self.assertEqual(packet["watches_ready_for_review"], 0)

    def test_source_hash_is_pinned(self):
        packet = self.build(_session_report())
        source = packet["source_reports"][0]
        self.assertEqual(len(source["sha256"]), 64)
        canonical = json.dumps(
            {key: value for key, value in packet.items() if key != "packet_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), packet["packet_sha256"])

    def test_unknown_watch_id_is_flagged_not_invented(self):
        report = _session_report()
        report["watches"][0]["watch_id"] = "SESSION_NOT_FROZEN"
        packet = self.build(report)
        self.assertFalse(packet["watches"][0]["present_in_frozen_config"])

    def test_markdown_leaves_verdict_cells_blank(self):
        text = review_packet_markdown(self.build(_session_report()))
        self.assertIn("_(to be recorded)_", text)
        self.assertIn("skeleton", text)

    def test_unrecognised_report_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps({"analysis": "something_else"}), encoding="utf-8")
            with self.assertRaisesRegex(ReviewPacketError, "unrecognised counting report"):
                build_review_packet(path, now=NOW)

    def test_missing_report_file_is_rejected(self):
        with self.assertRaisesRegex(ReviewPacketError, "file not found"):
            build_review_packet("research/does-not-exist.json", now=NOW)


class CommittedArtifactTests(unittest.TestCase):
    """The packet tool must work on the real frozen counting report."""

    def test_committed_report_produces_a_skeleton(self):
        if not COMMITTED_REPORT.is_file():
            self.skipTest("committed counting report not present")
        packet = build_review_packet(COMMITTED_REPORT, now=NOW)
        # W1/W2 had met their gates when this report was produced; W3 had not.
        self.assertEqual(packet["packet_status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(packet["watches_ready_for_review"], 2)
        self.assertEqual(packet["watches_total"], 3)
        watch_ids = {watch["watch_id"] for watch in packet["watches"]}
        self.assertIn(COMMITTED_FALSIFIED_WATCH, watch_ids)
        accumulating = [w for w in packet["watches"] if not w["ready_for_review"]]
        self.assertEqual(len(accumulating), 1)
        self.assertEqual(accumulating[0]["pipeline_status"], "ACCUMULATING")
        falsified = next(w for w in packet["watches"] if w["watch_id"] == COMMITTED_FALSIFIED_WATCH)
        self.assertEqual(falsified["pipeline_counts"]["prospective_unique_signals"], 73)
        self.assertEqual(falsified["pipeline_counts"]["prospective_independent_batches"], 10)
        for cell in falsified["cells_awaiting_verdict"]:
            self.assertIsNone(cell["verdict"])


class ForwardWatchPacketTests(unittest.TestCase):
    def build(self, report: dict) -> dict:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            return build_review_packet(path, forward_watch_config=DEFAULT_FORWARD_WATCH_CONFIG, now=NOW)

    def test_immature_window_renders_no_review_body(self):
        packet = self.build(_forward_report(days_elapsed=6.0))
        self.assertEqual(packet["packet_status"], "AWAITING_REVIEW_WINDOW")
        self.assertFalse(packet["window_matured"])
        text = review_packet_markdown(packet)
        self.assertIn("has not matured", text)
        for cell in packet["metric_cells_awaiting_verdict"]:
            self.assertIsNone(cell["verdict"])

    def test_matured_window_opens_the_review_body(self):
        packet = self.build(_forward_report(days_elapsed=30.0))
        self.assertTrue(packet["window_matured"])
        self.assertEqual(packet["packet_status"], "READY_FOR_HUMAN_REVIEW")
        self.assertGreater(packet["open_verdict_cells"], 0)
        text = review_packet_markdown(packet)
        self.assertIn("Metric", text)
        self.assertIn("_(to be recorded)_", text)

    def test_frozen_forbidden_actions_are_surfaced(self):
        packet = self.build(_forward_report(days_elapsed=30.0))
        self.assertIn("parameter_changes", packet["forbidden_actions"])


if __name__ == "__main__":
    unittest.main()

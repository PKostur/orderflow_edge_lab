from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.causal_audit import audit_outcome_maturity


class CausalAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.registry = root / "registry.json"
        self.observations = root / "observations.jsonl"
        self.candidate = {
            "candidate_id": "P1",
            "timeframe": "1m",
            "setup_family": "test",
            "direction": "long",
            "path": [],
            "numeric_filters": [],
            "spent_through": "2026-08-22T18:01:00Z",
            "frozen_at": "2026-09-01T00:00:00Z",
            "minimum_events": 1,
            "minimum_active_days": 1,
        }
        self.registry.write_text(json.dumps({"candidates": [self.candidate]}), encoding="utf-8")

    def write_rows(self, rows):
        self.observations.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    def test_outcome_within_event_window_is_causally_safe(self):
        self.write_rows([
            {
                "candidate_id": "P1",
                "observation_id": "a",
                "event_time": "2026-09-02T00:00:00Z",
                "outcome_time": "2026-09-02T00:05:00Z",
            }
        ])
        report = audit_outcome_maturity(self.registry, self.observations, window_days=7)
        self.assertTrue(report["causal_window_summaries_safe"])
        self.assertEqual(report["cross_window_outcome_count"], 0)
        self.assertEqual(report["candidates"][0]["matured_within_window"], 1)

    def test_outcome_crossing_window_end_is_flagged(self):
        self.write_rows([
            {
                "candidate_id": "P1",
                "observation_id": "crosses",
                "event_time": "2026-09-07T23:59:59Z",
                "outcome_time": "2026-09-08T00:00:02Z",
            }
        ])
        report = audit_outcome_maturity(self.registry, self.observations, window_days=7)
        self.assertFalse(report["causal_window_summaries_safe"])
        self.assertEqual(report["cross_window_outcome_count"], 1)
        self.assertEqual(report["candidates"][0]["crossing_observation_ids"], ["crosses"])
        self.assertGreater(report["candidates"][0]["max_seconds_past_window"], 0)

    def test_future_only_and_duplicate_identity_fail_closed(self):
        self.write_rows([
            {
                "candidate_id": "P1",
                "observation_id": "a",
                "event_time": "2026-09-01T00:00:00Z",
                "outcome_time": "2026-09-01T00:01:00Z",
            }
        ])
        with self.assertRaisesRegex(ValueError, "future-only"):
            audit_outcome_maturity(self.registry, self.observations)

        row = {
            "candidate_id": "P1",
            "observation_id": "dup",
            "event_time": "2026-09-02T00:00:00Z",
            "outcome_time": "2026-09-02T00:01:00Z",
        }
        self.write_rows([row, row])
        with self.assertRaisesRegex(ValueError, "duplicate observation identity"):
            audit_outcome_maturity(self.registry, self.observations)

    def test_invalid_window_length_rejected(self):
        self.write_rows([])
        with self.assertRaisesRegex(ValueError, "window_days"):
            audit_outcome_maturity(self.registry, self.observations, window_days=0)


if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest

from orderflow_edge_lab.research import (
    Candidate, benjamini_hochberg, enforce_future_only, partition_records,
    research_manifest, sequential_windows,
)


UTC = timezone.utc


class ResearchTests(unittest.TestCase):
    def setUp(self):
        boundary = datetime(2026, 8, 22, 18, 1, tzinfo=UTC)
        self.candidate = Candidate(
            candidate_id="P001",
            timeframe="3m",
            setup_family="failed_bear_breakout_long",
            direction="long",
            spent_through=boundary,
            frozen_at=boundary,
            minimum_events=3,
            minimum_active_days=2,
        )

    def test_future_only_is_strict(self):
        with self.assertRaises(ValueError):
            enforce_future_only(self.candidate, [self.candidate.spent_through])
        enforce_future_only(
            self.candidate,
            [self.candidate.spent_through + timedelta(microseconds=1)],
        )

    def test_sequential_window_completeness(self):
        start = self.candidate.spent_through + timedelta(hours=1)
        times = [start, start + timedelta(hours=2), start + timedelta(days=1)]
        windows = sequential_windows(self.candidate, times, window_days=7)
        self.assertEqual(len(windows), 1)
        self.assertTrue(windows[0].complete)

    def test_bh_monotonic_adjustment(self):
        q = benjamini_hochberg([0.01, 0.04, 0.03, 0.20])
        self.assertEqual(len(q), 4)
        self.assertTrue(all(0 <= x <= 1 for x in q))
        self.assertLessEqual(q[0], q[1])

    def test_unrevealed_holdout_is_absent(self):
        t0 = datetime(2026, 9, 1, tzinfo=UTC)
        records = [
            {"t": t0 + timedelta(days=i), "x": i}
            for i in range(9)
        ]
        part = partition_records(
            records,
            timestamp_key="t",
            discovery_end=t0 + timedelta(days=3),
            validation_end=t0 + timedelta(days=6),
            holdout_end=t0 + timedelta(days=9),
            reveal_holdout=False,
        )
        self.assertNotIn("holdout", part)
        self.assertEqual(len(part["discovery"]), 3)
        self.assertEqual(len(part["validation"]), 3)

    def test_manifest_redacts_holdout_config_and_hashes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "input.csv"
            p.write_text("a,b\n1,2\n", encoding="utf-8")
            m = research_manifest(
                config={"alpha": 1, "holdout_end": "secret", "final_test_seed": 2},
                input_files=[p],
                code_version="abc",
                holdout_revealed=False,
            )
            self.assertEqual(m["config"], {"alpha": 1})
            self.assertIn("input.csv", m["inputs"])
            self.assertEqual(len(m["manifest_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()

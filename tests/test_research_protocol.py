from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from orderflow_edge_lab.research_protocol import (
    ResearchProtocolError,
    build_research_freeze,
    classify_timestamp,
    verify_freeze,
)

UTC = timezone.utc


class ResearchProtocolTests(unittest.TestCase):
    def audit(self, sha: str = "a" * 64):
        return {
            "file": {"name": "sample.csv", "sha256": sha},
            "csv": {"row_count": 100},
            "timestamps": {
                "minimum": "2026-09-01T00:00:00+00:00",
                "maximum": "2026-09-10T00:00:00+00:00",
            },
        }

    def test_freeze_binds_source_hash_and_boundaries(self):
        manifest = build_research_freeze(
            [(Path("audit.json"), self.audit())],
            discovery_end=datetime(2026, 9, 4, tzinfo=UTC),
            validation_end=datetime(2026, 9, 7, tzinfo=UTC),
            holdout_end=datetime(2026, 9, 10, tzinfo=UTC),
            embargo_seconds=3600,
            protocol_name="ena-btc-v1",
        )
        self.assertTrue(verify_freeze(manifest))
        self.assertFalse(manifest["verified_out_of_sample_evidence"])
        self.assertEqual(manifest["sources"][0]["source_sha256"], "a" * 64)
        self.assertEqual(manifest["partition_policy"]["embargo_seconds"], 3600)

    def test_manifest_tamper_is_detected(self):
        manifest = build_research_freeze(
            [(Path("audit.json"), self.audit())],
            discovery_end=datetime(2026, 9, 4, tzinfo=UTC),
            validation_end=datetime(2026, 9, 7, tzinfo=UTC),
            holdout_end=datetime(2026, 9, 10, tzinfo=UTC),
        )
        manifest["partition_policy"]["holdout_end"] = "2026-09-11T00:00:00+00:00"
        self.assertFalse(verify_freeze(manifest))

    def test_duplicate_source_bytes_fail_closed(self):
        with self.assertRaisesRegex(ResearchProtocolError, "duplicate source bytes"):
            build_research_freeze(
                [(Path("a.json"), self.audit()), (Path("b.json"), self.audit())],
                discovery_end=datetime(2026, 9, 4, tzinfo=UTC),
                validation_end=datetime(2026, 9, 7, tzinfo=UTC),
                holdout_end=datetime(2026, 9, 10, tzinfo=UTC),
            )

    def test_embargo_classification(self):
        discovery_end = datetime(2026, 9, 4, tzinfo=UTC)
        validation_end = datetime(2026, 9, 7, tzinfo=UTC)
        holdout_end = datetime(2026, 9, 10, tzinfo=UTC)
        embargo = timedelta(hours=1)
        self.assertEqual(
            classify_timestamp(
                discovery_end + timedelta(minutes=30),
                discovery_end=discovery_end,
                validation_end=validation_end,
                holdout_end=holdout_end,
                embargo=embargo,
            ),
            "embargo_discovery_validation",
        )
        self.assertEqual(
            classify_timestamp(
                validation_end + timedelta(hours=2),
                discovery_end=discovery_end,
                validation_end=validation_end,
                holdout_end=holdout_end,
                embargo=embargo,
            ),
            "holdout",
        )

    def test_embargo_cannot_consume_partition(self):
        with self.assertRaisesRegex(ResearchProtocolError, "consumes validation"):
            build_research_freeze(
                [(Path("audit.json"), self.audit())],
                discovery_end=datetime(2026, 9, 4, tzinfo=UTC),
                validation_end=datetime(2026, 9, 4, 0, 30, tzinfo=UTC),
                holdout_end=datetime(2026, 9, 10, tzinfo=UTC),
                embargo_seconds=3600,
            )


if __name__ == "__main__":
    unittest.main()

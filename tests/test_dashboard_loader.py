import json
import tempfile
import unittest
from pathlib import Path

from dashboard.research_dashboard.loader import discover_artifacts, discover_git_ref_artifacts


class DashboardLoaderTests(unittest.TestCase):
    def test_discovers_explicit_research_state_without_inventing_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "research" / "trial" / "result.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "research_id": "trial_v1",
                        "status": "FALSIFIED_D0",
                        "pooled_net_mean_bps_2": -1.25,
                        "research_state": {
                            "persistent_edge_established": False,
                            "candidate_created": False,
                            "live_execution_supported": False,
                            "leverage_supported": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            rows = discover_artifacts(root)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row.project_id, "trial_v1")
            self.assertEqual(row.stage, "D0/DISCOVERY")
            self.assertEqual(row.source_ref, "WORKTREE")
            self.assertFalse(row.persistent_edge)
            self.assertFalse(row.candidate)
            self.assertFalse(row.live_supported)
            self.assertFalse(row.leverage_supported)
            self.assertEqual(row.metrics["pooled_net_mean_bps_2"], -1.25)

    def test_shadow_is_classified_but_not_promoted_by_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "config" / "example_shadow_v1.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "shadow_id": "example_shadow_v1",
                        "status": "FROZEN",
                        "claims": {"live_execution_supported": False},
                    }
                ),
                encoding="utf-8",
            )

            row = discover_artifacts(root)[0]
            self.assertTrue(row.is_shadow)
            self.assertEqual(row.stage, "SHADOW")
            self.assertIsNone(row.candidate)
            self.assertFalse(row.live_supported)

    def test_candidate_filename_does_not_mean_candidate_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "config" / "candidate_spec.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps({"candidate_id": "c1", "status": "FROZEN"}),
                encoding="utf-8",
            )

            row = discover_artifacts(root)[0]
            self.assertTrue(row.is_candidate_artifact)
            self.assertIsNone(row.candidate)

    def test_parse_errors_are_visible_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "research" / "broken.json"
            target.parent.mkdir(parents=True)
            target.write_text("{not-json", encoding="utf-8")

            row = discover_artifacts(root)[0]
            self.assertEqual(row.status, "PARSE_ERROR")
            self.assertIsNotNone(row.parse_error)
            self.assertIsNone(row.live_supported)

    def test_conflicting_explicit_flags_resolve_to_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "research" / "conflict.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "status": "REVIEW",
                        "a": {"live_execution_supported": True},
                        "b": {"live_execution_supported": False},
                    }
                ),
                encoding="utf-8",
            )
            row = discover_artifacts(root)[0]
            self.assertIsNone(row.live_supported)

    def test_empty_repository_has_no_synthetic_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover_artifacts(tmp), [])

    def test_git_ref_discovery_fails_closed_outside_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                discover_git_ref_artifacts(tmp, ["research/cross-market-etf-v1"]),
                [],
            )


if __name__ == "__main__":
    unittest.main()

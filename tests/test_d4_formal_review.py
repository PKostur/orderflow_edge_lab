from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics
import unittest


class D4FormalReviewTests(unittest.TestCase):
    def test_review_is_bound_to_its_snapshot(self):
        rec = json.loads(Path("research/volatility_state_d4/FORMAL_REVIEW_1.json").read_text(encoding="utf-8"))
        snap = Path(rec["bound_snapshot"]["aggregate_file"])
        self.assertEqual(hashlib.sha256(snap.read_bytes()).hexdigest(), rec["bound_snapshot"]["aggregate_sha256"])
        agg = json.loads(snap.read_text(encoding="utf-8"))
        self.assertEqual([c["cluster_id"] for c in agg["clusters"]], rec["bound_snapshot"]["cluster_ids"])
        self.assertTrue(agg["review_progress"]["ready_for_review"])
        self.assertEqual(len(rec["bound_snapshot"]["collector_ref"]), 40)
        self.assertEqual(rec["bound_snapshot"]["source_artifact_id"], 10937803160)
        self.assertEqual(rec["bound_snapshot"]["source_artifact_name"], "volatility-state-forward-ledger-v1")
        self.assertEqual(
            rec["bound_snapshot"]["source_artifact_digest"],
            "sha256:ad0bb3698587ef90c29a4356046b5c6126e60aa59b9cca01f099e81ea0e8297b",
        )

    def test_conclusion_matches_snapshot(self):
        rec = json.loads(Path("research/volatility_state_d4/FORMAL_REVIEW_1.json").read_text(encoding="utf-8"))
        vals = rec["observed"]["cluster_median_spearman"]
        self.assertEqual(len(vals), 11)
        self.assertTrue(all(v < 0 for v in vals))
        self.assertAlmostEqual(statistics.median(vals), rec["observed"]["median_of_cluster_medians"], places=5)
        self.assertEqual(rec["formal_conclusion"], "NOT_REPLICATED_DIRECTIONALLY")
        self.assertFalse(any(rec["claims"].values()))
        self.assertTrue(rec["lock"]["first_eligible_formal_review_snapshot"])
        self.assertTrue(rec["lock"]["conclusion_immutable_under_later_accumulation"])
        self.assertTrue(rec["lock"]["later_clusters_may_be_reported_but_cannot_rewrite_review_1"])


if __name__ == "__main__":
    unittest.main()

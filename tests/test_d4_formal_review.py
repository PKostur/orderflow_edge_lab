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
        cfg = Path("config/volatility_state_transfer_forward_v1.json")
        self.assertEqual(
            hashlib.sha256(cfg.read_bytes()).hexdigest(),
            rec["bound_snapshot"]["frozen_config_sha256"],
        )
        self.assertEqual(len(rec["bound_snapshot"]["collector_ref"]), 40)
        self.assertEqual(rec["bound_snapshot"]["source_artifact_id"], 10937803160)
        self.assertEqual(rec["bound_snapshot"]["source_artifact_name"], "volatility-state-forward-ledger-v1")
        self.assertEqual(
            rec["bound_snapshot"]["source_artifact_digest"],
            "sha256:ad0bb3698587ef90c29a4356046b5c6126e60aa59b9cca01f099e81ea0e8297b",
        )

    def test_conclusion_matches_snapshot(self):
        rec = json.loads(Path("research/volatility_state_d4/FORMAL_REVIEW_1.json").read_text(encoding="utf-8"))
        snap = Path(rec["bound_snapshot"]["aggregate_file"])
        agg = json.loads(snap.read_text(encoding="utf-8"))
        exact_vals = [c["cluster_median_primary_spearman"] for c in agg["clusters"]]
        vals = rec["observed"]["cluster_median_spearman"]
        self.assertEqual(len(vals), 11)
        self.assertEqual(vals, [round(v, 6) for v in exact_vals])
        self.assertTrue(all(v < 0 for v in exact_vals))
        self.assertEqual(rec["observed"]["negative_clusters"], len(exact_vals))
        self.assertEqual(rec["observed"]["distinct_utc_dates"], agg["distinct_utc_dates"])
        self.assertEqual(rec["observed"]["eligible_clusters"], agg["eligible_cluster_count"])
        self.assertAlmostEqual(
            rec["observed"]["median_of_cluster_medians"],
            agg["cluster_median_spearman_median"],
            places=12,
        )
        self.assertAlmostEqual(
            rec["observed"]["median_pooled_within_symbol_rank_correlation"],
            agg["median_pooled_within_symbol_rank_correlation"],
            places=12,
        )
        self.assertEqual(rec["observed"]["positive_cluster_fraction"], agg["positive_cluster_fraction"])
        self.assertEqual(rec["formal_conclusion"], "NOT_REPLICATED_DIRECTIONALLY")
        self.assertFalse(any(rec["claims"].values()))
        self.assertTrue(rec["lock"]["first_eligible_formal_review_snapshot"])
        self.assertTrue(rec["lock"]["conclusion_immutable_under_later_accumulation"])
        self.assertTrue(rec["lock"]["later_clusters_may_be_reported_but_cannot_rewrite_review_1"])


if __name__ == "__main__":
    unittest.main()

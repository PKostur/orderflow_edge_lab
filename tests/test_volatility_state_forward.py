from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.volatility_state_forward import (
    VolatilityStateForwardError,
    aggregate_forward_clusters,
    evaluate_forward_cluster,
    restore_forward_cluster_history,
)


class VolatilityStateForwardTests(unittest.TestCase):
    def _config(self):
        return {
            "watch_id": "vol-state-forward-v1",
            "prospective_start_utc": "2026-09-24T21:00:00Z",
            "source": {"transfer_symbols": ["A_USDT", "B_USDT"]},
            "frozen_relationship": {
                "feature": "local_range_to_spread_15s",
                "primary_target": "volatility_expansion_ratio_60s",
                "secondary_targets": ["volatility_expansion_ratio_30s"],
            },
            "review_rule": {
                "minimum_observations_per_symbol_per_cluster": 8,
                "minimum_eligible_symbols_per_cluster": 2,
                "minimum_independent_clusters": 3,
                "minimum_distinct_utc_dates": 2,
            },
        }

    def _report(self, symbol: str, positive=True):
        base = 1790283600 * 1_000_000_000
        obs=[]
        for i in range(12):
            x=float(i+1)
            y=x if positive else float(12-i)
            obs.append({
                "observed_at_ns": base + i*5_000_000_000,
                "features":{"local_range_to_spread_15s":x},
                "targets":{
                    "volatility_expansion_ratio_60s":y,
                    "volatility_expansion_ratio_30s":y*0.5,
                },
            })
        return {
            "experiment":"regime_research_v1_market_state_scan",
            "symbol":symbol,
            "observations":obs,
        }

    def test_cluster_counts_simultaneous_symbols_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[]
            for symbol in ("A_USDT","B_USDT"):
                p=Path(tmp)/f"{symbol}.json"
                p.write_text(json.dumps(self._report(symbol)),encoding="utf-8")
                paths.append(p)
            result=evaluate_forward_cluster(paths,self._config(),cluster_id="c1")
        self.assertEqual(result["eligible_symbol_count"],2)
        self.assertAlmostEqual(result["cluster_median_primary_spearman"],1.0)
        self.assertEqual(result["cluster_positive_symbol_fraction"],1.0)
        self.assertTrue(result["claims"]["simultaneous_symbols_count_as_one_dependence_cluster"])

    def test_aggregate_review_gate_uses_clusters_and_dates(self):
        cfg=self._config()
        clusters=[]
        for i,date in enumerate(("2026-09-25","2026-09-25","2026-09-26"),start=1):
            clusters.append({
                "schema_version":1,
                "analysis":"volatility_state_forward_cluster_v1",
                "watch_id":cfg["watch_id"],
                "cluster_id":f"c{i}",
                "prospective_start_utc":cfg["prospective_start_utc"],
                "capture_first_observation_utc":f"{date}T01:00:00+00:00",
                "eligible_symbol_count":2,
                "cluster_median_primary_spearman":0.2+i*0.01,
                "pooled_within_symbol_rank_correlation":0.25,
            })
        with tempfile.TemporaryDirectory() as tmp:
            paths=[]
            for i,row in enumerate(clusters):
                p=Path(tmp)/f"c{i}.json"
                p.write_text(json.dumps(row),encoding="utf-8")
                paths.append(p)
            result=aggregate_forward_clusters(paths,cfg)
        self.assertEqual(result["eligible_cluster_count"],3)
        self.assertEqual(len(result["distinct_utc_dates"]),2)
        self.assertTrue(result["review_progress"]["ready_for_review"])
        self.assertEqual(result["formal_verdict"],"WITHHELD")


    def test_restore_deduplicates_identical_artifact_copies(self):
        cfg=self._config()
        rows=[]
        for i,date in enumerate(("2026-09-25","2026-09-26"),start=1):
            rows.append({
                "schema_version":1,
                "analysis":"volatility_state_forward_cluster_v1",
                "watch_id":cfg["watch_id"],
                "cluster_id":f"c{i}",
                "prospective_start_utc":cfg["prospective_start_utc"],
                "capture_first_observation_utc":f"{date}T01:00:00+00:00",
                "eligible_symbol_count":2,
                "cluster_median_primary_spearman":0.1*i,
                "pooled_within_symbol_rank_correlation":0.2*i,
            })
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[]
            for copy_index in range(2):
                for row in rows:
                    p=root/f"artifact{copy_index}"/row["cluster_id"]/"cluster.json"
                    p.parent.mkdir(parents=True,exist_ok=True)
                    p.write_text(json.dumps(row),encoding="utf-8")
                    paths.append(p)
            history=root/"history"
            result=restore_forward_cluster_history(paths,cfg,history)
            restored=sorted(history.glob("*/cluster.json"))
        self.assertEqual(result["restored_cluster_count"],2)
        self.assertEqual(result["cluster_ids"],["c1","c2"])
        self.assertEqual(len(restored),2)
        self.assertFalse(result["claims"]["new_evidence_collected"])
        self.assertFalse(result["claims"]["historical_cluster_values_changed"])

    def test_restore_rejects_conflicting_duplicate_cluster_id(self):
        cfg=self._config()
        base={
            "schema_version":1,
            "analysis":"volatility_state_forward_cluster_v1",
            "watch_id":cfg["watch_id"],
            "cluster_id":"c1",
            "prospective_start_utc":cfg["prospective_start_utc"],
            "capture_first_observation_utc":"2026-09-25T01:00:00+00:00",
            "eligible_symbol_count":2,
            "cluster_median_primary_spearman":0.2,
            "pooled_within_symbol_rank_correlation":0.25,
        }
        changed=dict(base)
        changed["cluster_median_primary_spearman"]=-0.2
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[]
            for name,row in (("a",base),("b",changed)):
                p=root/name/"cluster.json"
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(json.dumps(row),encoding="utf-8")
                paths.append(p)
            with self.assertRaises(VolatilityStateForwardError):
                restore_forward_cluster_history(paths,cfg,root/"history")



if __name__ == "__main__":
    unittest.main()

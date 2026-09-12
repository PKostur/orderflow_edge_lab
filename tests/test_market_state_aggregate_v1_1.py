from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.market_state_aggregate_v1_1 import build_v1_1_state_screen


class MarketStateAggregateV11Tests(unittest.TestCase):
    def _write_protocol(self, root: Path) -> Path:
        payload = {
            "protocol_name": "regime-research-v1.1",
            "frozen_at_utc": "2026-09-12T20:55:00Z",
            "evidence_start_batch_id": "20260912T210000Z",
            "state_screen": {
                "minimum_independent_batches": 5,
                "minimum_dominant_sign_fraction": 0.8,
                "minimum_association_observations_per_batch": 20,
                "minimum_median_abs_spearman": 0.10,
                "minimum_median_abs_partial_spearman": 0.10,
                "redundancy_abs_spearman_threshold": 0.80,
            },
            "claims": {
                "verified_out_of_sample_evidence": False,
                "profitable_edge_established": False,
                "live_order_transmission_supported": False,
            },
        }
        path = root / "protocol.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _write_report(self, root: Path, batch_id: str, rho: float) -> Path:
        payload = {
            "experiment": "regime_research_v1_market_state_scan",
            "batch_id": batch_id,
            "associations": [
                {
                    "research_family": "liquidity_microstructure",
                    "feature": "spread_bps",
                    "target": "future_spread_bps_5s",
                    "observations": 30,
                    "spearman": rho,
                }
            ],
            "feature_redundancy": {"pairs": []},
            "observations": [],
        }
        path = root / f"{batch_id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_pre_freeze_batches_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write_protocol(root)
            old = self._write_report(root, "20260912T205900Z_old", 0.9)
            report = build_v1_1_state_screen([old], protocol)
            self.assertEqual(report["status"], "waiting_for_forward_batches")
            self.assertEqual(report["independent_batch_count"], 0)

    def test_sign_stability_alone_does_not_pass_effect_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write_protocol(root)
            reports = [
                self._write_report(root, f"20260912T21{i:02d}00Z_batch", 0.08)
                for i in range(5)
            ]
            report = build_v1_1_state_screen(reports, protocol)
            row = report["association_summary"][0]
            self.assertTrue(row["stable_sign_across_batches"])
            self.assertFalse(row["v1_1_effect_size_floor_passed"])
            self.assertFalse(row["v1_1_eligible_state_association"])
            self.assertEqual(report["eligible_state_association_count"], 0)

    def test_forward_stable_nontrivial_association_can_enter_separate_conditioning_research(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write_protocol(root)
            reports = [
                self._write_report(root, f"20260912T22{i:02d}00Z_batch", value)
                for i, value in enumerate([0.18, 0.21, 0.16, 0.19, 0.20])
            ]
            report = build_v1_1_state_screen(reports, protocol)
            row = report["association_summary"][0]
            self.assertTrue(row["v1_1_eligible_state_association"])
            self.assertEqual(report["eligible_state_association_count"], 1)
            self.assertTrue(
                report["v1_1_readiness"]["state_hypothesis_available_for_separate_conditioning_test"]
            )
            self.assertFalse(report["v1_1_readiness"]["automatic_strategy_conditioning_permitted"])
            self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])


if __name__ == "__main__":
    unittest.main()

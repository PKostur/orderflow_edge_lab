from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.strategy_conditioning_freeze import (
    StrategyConditioningFreezeError,
    build_strategy_conditioning_freeze,
    verify_strategy_conditioning_freeze,
)


class StrategyConditioningFreezeTests(unittest.TestCase):
    def _write_protocol(self, root: Path) -> Path:
        payload = {
            "protocol_name": "strategy-conditioning-v1",
            "frozen_at_utc": "2026-09-12T21:15:00Z",
            "upstream_state_protocol": "regime-research-v1.1",
            "baseline_strategy_protocol": "discovery-v1",
            "eligibility": {
                "required_state_screen_status": "screen_ready",
                "minimum_independent_batches": 5,
                "minimum_dominant_sign_fraction": 0.8,
                "minimum_median_abs_spearman": 0.1,
                "require_pnl_independent_redundancy_representative": True,
            },
            "trial_design": {"maximum_features": 1},
            "evaluation": {"required_outputs": ["conditioned_net_profit_factor"]},
            "claims": {
                "verified_out_of_sample_evidence": False,
                "profitable_edge_established": False,
                "live_order_transmission_supported": False,
                "automatic_strategy_conditioning_supported": False,
            },
        }
        path = root / "protocol.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _write_screen(self, root: Path, *, feature: str = "spread_bps", eligible: bool = True) -> Path:
        payload = {
            "experiment": "regime_research_v1_1_market_state_screen",
            "protocol_name": "regime-research-v1.1",
            "status": "screen_ready",
            "v1_1_readiness": {"enough_forward_batches": True},
            "claims": {"strategy_pnl_used": False},
            "association_summary": [
                {
                    "research_family": "liquidity_microstructure",
                    "feature": feature,
                    "target": "future_spread_bps_5s",
                    "independent_batches": 5,
                    "total_observations": 150,
                    "dominant_sign": "positive",
                    "dominant_sign_fraction": 1.0,
                    "median_spearman": 0.35,
                    "v1_1_eligible_state_association": eligible,
                }
            ],
            "feature_redundancy": {
                "clusters": [["spread_bps", "microprice_displacement"]],
                "representatives": {"cluster_1": "spread_bps"},
            },
        }
        path = root / "screen.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_freezes_only_state_qualified_representative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write_protocol(root)
            screen = self._write_screen(root)
            report = build_strategy_conditioning_freeze(
                screen,
                protocol,
                research_family="liquidity_microstructure",
                feature="spread_bps",
                target="future_spread_bps_5s",
            )
            self.assertTrue(verify_strategy_conditioning_freeze(report))
            self.assertEqual(report["state_hypothesis"]["feature"], "spread_bps")
            self.assertTrue(report["claims"]["state_screen_passed_before_strategy_pnl_test"])
            self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_rejects_nonrepresentative_redundant_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write_protocol(root)
            screen = self._write_screen(root, feature="microprice_displacement")
            with self.assertRaises(StrategyConditioningFreezeError):
                build_strategy_conditioning_freeze(
                    screen,
                    protocol,
                    research_family="liquidity_microstructure",
                    feature="microprice_displacement",
                    target="future_spread_bps_5s",
                )

    def test_rejects_unqualified_state_association(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write_protocol(root)
            screen = self._write_screen(root, eligible=False)
            with self.assertRaises(StrategyConditioningFreezeError):
                build_strategy_conditioning_freeze(
                    screen,
                    protocol,
                    research_family="liquidity_microstructure",
                    feature="spread_bps",
                    target="future_spread_bps_5s",
                )


if __name__ == "__main__":
    unittest.main()

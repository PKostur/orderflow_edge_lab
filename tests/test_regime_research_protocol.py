from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RegimeResearchProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((ROOT / "config" / "regime_research_v1.json").read_text(encoding="utf-8"))

    def test_protocol_is_discovery_only_and_makes_no_edge_claim(self):
        self.assertEqual(self.protocol["status"], "discovery_only")
        claims = self.protocol["claims"]
        self.assertFalse(claims["verified_out_of_sample_evidence"])
        self.assertFalse(claims["profitable_edge_established"])
        self.assertFalse(claims["live_order_transmission_supported"])

    def test_market_state_targets_are_separate_from_strategy_pnl(self):
        targets = self.protocol["market_state_targets"]
        self.assertEqual(set(targets), {"directionality", "volatility", "liquidity", "continuation_reversion"})
        self.assertIn("future market state", self.protocol["purpose"].lower())

    def test_specialist_families_cover_distinct_research_domains(self):
        families = self.protocol["specialist_families"]
        expected = {
            "trend_structure",
            "volatility_regime",
            "liquidity_microstructure",
            "aggressive_flow",
            "mean_reversion",
            "cross_asset_context",
            "derivatives_positioning",
            "time_session",
            "execution_economics",
        }
        self.assertEqual(set(families), expected)
        for family in families.values():
            self.assertTrue(family["indicators"])
            self.assertTrue(family["questions"])

    def test_synthesis_requires_redundancy_and_cost_controls(self):
        synthesis = self.protocol["synthesis_rules"]
        self.assertTrue(synthesis["redundancy_control"])
        self.assertTrue(synthesis["require_positive_net_expectancy_after_costs"])
        self.assertTrue(synthesis["require_pf_above_one_after_costs_for_trade_condition"])
        self.assertTrue(synthesis["compare_original_vs_reversed"])
        anti = "\n".join(self.protocol["anti_overfit_rules"]).lower()
        self.assertIn("do not select the best of many indicators solely by maximum pf", anti)
        self.assertIn("do not weaken transaction-cost assumptions", anti)

    def test_multi_agent_release_config_requires_specialized_roles(self):
        config = json.loads((ROOT / "config" / "multi_agents.json").read_text(encoding="utf-8"))
        required = set(config["release_manager"]["require_agents"])
        for agent_id in (
            "trend_structure",
            "volatility_regime",
            "liquidity_microstructure",
            "aggressive_flow",
            "mean_reversion",
            "cross_asset_context",
            "indicator_orthogonality",
            "research_validity",
            "transfer_generalization",
            "execution_economics",
        ):
            self.assertIn(agent_id, required)

    def test_ruflo_bootstrap_exposes_specialized_swarm_capacity(self):
        for relative in ("integrations/ruflo/bootstrap.ps1", "integrations/ruflo/bootstrap.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertIn("max-agents 15", text)
            self.assertIn("trend-structure", text)
            self.assertIn("volatility-regime", text)
            self.assertIn("liquidity-microstructure", text)
            self.assertIn("indicator-orthogonality", text)
            self.assertIn("transfer-generalization", text)


if __name__ == "__main__":
    unittest.main()

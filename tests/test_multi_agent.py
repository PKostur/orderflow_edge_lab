import unittest
from pathlib import Path

from orderflow_edge_lab.multi_agent import run_multi_agent, verify_report


ROOT = Path(__file__).resolve().parents[1]


class MultiAgentTests(unittest.TestCase):
    def test_all_specialists_run_and_report_is_hashed(self):
        report = run_multi_agent(ROOT, run_commands=False)
        self.assertTrue(verify_report(report))
        ids = {item["agent_id"] for item in report["agents"]}
        self.assertEqual(
            ids,
            {
                "data_integrity",
                "trend_structure",
                "volatility_regime",
                "liquidity_microstructure",
                "aggressive_flow",
                "mean_reversion",
                "cross_asset_context",
                "news_event_context",
                "derivatives_positioning",
                "execution_economics",
                "risk_path",
                "indicator_orthogonality",
                "research_validity",
                "transfer_generalization",
                "execution_safety",
                "reliability_observability",
                "adversarial_reviewer",
            },
        )
        manager = report["release_manager"]
        self.assertFalse(manager["live_order_transmission_supported"])
        self.assertFalse(manager["profitable_edge_established"])
        self.assertFalse(manager["verified_out_of_sample_evidence"])

    def test_report_tampering_is_detected(self):
        report = run_multi_agent(ROOT, run_commands=False)
        report["release_manager"]["profitable_edge_established"] = True
        self.assertFalse(verify_report(report))

    def test_research_agent_surfaces_trial_accounting_gap_until_bound(self):
        report = run_multi_agent(ROOT, run_commands=False)
        research = next(item for item in report["agents"] if item["agent_id"] == "research_validity")
        codes = {finding["code"] for finding in research["findings"]}
        promotion_text = (
            (ROOT / "src/orderflow_edge_lab/promotion.py").read_text(encoding="utf-8")
            + (ROOT / "src/orderflow_edge_lab/cli/promote.py").read_text(encoding="utf-8")
        ).lower()
        if "trial_ledger" not in promotion_text and "trial-ledger" not in promotion_text:
            self.assertIn("trial_ledger_not_bound_to_promotion", codes)


if __name__ == "__main__":
    unittest.main()

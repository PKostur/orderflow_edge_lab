import unittest

from orderflow_edge_lab.economics import EconomicsPolicy
from orderflow_edge_lab.promotion import assess_candidate_promotion


class PromotionTests(unittest.TestCase):
    def report(self):
        return {
            "schema_version": 7,
            "deployment_eligible": False,
            "verified_out_of_sample_evidence": False,
            "source_verification": {"verified_against_local_files": True, "files": []},
            "candidates": [{
                "candidate_id": "P1",
                "windows": [{"complete": True}],
                "summary": {"n": 25, "mean_r": 0.1},
            }],
        }

    def test_current_validation_artifact_cannot_be_promoted(self):
        result = assess_candidate_promotion(self.report(), "P1", EconomicsPolicy(account_equity=10000))
        self.assertFalse(result.promotable)
        self.assertTrue(result.research_only)
        self.assertIn("validation_report_not_deployment_eligible", result.reasons)
        self.assertIn("out_of_sample_edge_not_verified", result.reasons)

    def test_positive_fixed_cost_is_separate_hard_gate(self):
        report = self.report()
        report["deployment_eligible"] = True
        report["verified_out_of_sample_evidence"] = True
        economics = EconomicsPolicy(account_equity=10000, monthly_data_cost=199)
        result = assess_candidate_promotion(report, "P1", economics)
        self.assertFalse(result.promotable)
        self.assertIn("fixed_operating_cost_not_mapped_to_validated_currency_pnl", result.reasons)
        self.assertAlmostEqual(result.monthly_cost_hurdle_fraction, 0.0199)

    def test_zero_cost_candidate_requires_complete_window_and_outcomes(self):
        report = self.report()
        report["deployment_eligible"] = True
        report["verified_out_of_sample_evidence"] = True
        candidate = report["candidates"][0]
        candidate["windows"] = [{"complete": False}]
        candidate["summary"] = {"n": 0}
        result = assess_candidate_promotion(report, "P1", EconomicsPolicy(account_equity=10000))
        self.assertFalse(result.promotable)
        self.assertIn("no_complete_causal_validation_window", result.reasons)
        self.assertIn("no_matured_candidate_outcomes", result.reasons)

    def test_fully_certified_zero_cost_fixture_can_pass_gate(self):
        report = self.report()
        report["deployment_eligible"] = True
        report["verified_out_of_sample_evidence"] = True
        result = assess_candidate_promotion(report, "P1", EconomicsPolicy(account_equity=10000))
        self.assertTrue(result.promotable)
        self.assertFalse(result.research_only)
        self.assertEqual(result.reasons, ())
        self.assertEqual(len(result.validation_report_sha256), 64)
        self.assertEqual(len(result.economics_sha256), 64)

    def test_unverified_source_bytes_block_promotion(self):
        report = self.report()
        report["deployment_eligible"] = True
        report["verified_out_of_sample_evidence"] = True
        report["source_verification"]["verified_against_local_files"] = False
        result = assess_candidate_promotion(report, "P1", EconomicsPolicy(account_equity=10000))
        self.assertFalse(result.promotable)
        self.assertIn("source_bytes_not_locally_verified", result.reasons)

    def test_unknown_candidate_and_malformed_candidate_list_fail_closed(self):
        with self.assertRaises(ValueError):
            assess_candidate_promotion(self.report(), "missing", EconomicsPolicy(account_equity=10000))
        report = self.report()
        report["candidates"] = {}
        with self.assertRaises(ValueError):
            assess_candidate_promotion(report, "P1", EconomicsPolicy(account_equity=10000))


if __name__ == "__main__":
    unittest.main()

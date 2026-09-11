import unittest

from orderflow_edge_lab.economics import EconomicsPolicy, load_economics_policy


class EconomicsPolicyTests(unittest.TestCase):
    def test_zero_incremental_stack_has_zero_fixed_hurdle(self):
        report = EconomicsPolicy(account_equity=10_000).report()
        self.assertEqual(report["monthly_fixed_cost"], 0.0)
        self.assertEqual(report["monthly_cost_hurdle_fraction"], 0.0)

    def test_paid_stack_cost_is_expressed_against_equity(self):
        policy = EconomicsPolicy(
            account_equity=10_000,
            monthly_data_cost=199,
            monthly_platform_cost=50,
            monthly_compute_cost=25,
            monthly_model_cost=10,
            monthly_other_cost=16,
        )
        self.assertEqual(policy.monthly_fixed_cost, 300)
        self.assertAlmostEqual(policy.monthly_cost_hurdle_fraction, 0.03)
        self.assertAlmostEqual(policy.annualized_simple_cost_hurdle_fraction, 0.36)

    def test_negative_or_nonfinite_costs_are_rejected(self):
        with self.assertRaises(ValueError):
            EconomicsPolicy(account_equity=10_000, monthly_data_cost=-1)
        with self.assertRaises(ValueError):
            EconomicsPolicy(account_equity=float("nan"))

    def test_unknown_policy_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown economics fields"):
            load_economics_policy({"account_equity": 10_000, "magic_alpha_fee": 1})


if __name__ == "__main__":
    unittest.main()

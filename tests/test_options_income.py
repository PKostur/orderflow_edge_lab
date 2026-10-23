import math
import random
import unittest

from orderflow_edge_lab.options_income import DAY, depth_vwap, describe, expiry_pnl, request, select_spread, size_amount, trading_fee


class OptionsIncomeTests(unittest.TestCase):
    def test_real_depth_prices_and_refused_shortfalls(self):
        self.assertAlmostEqual(depth_vwap([[10, 1], [12, 2]], 2, 'buy'), 11)
        self.assertAlmostEqual(depth_vwap([[12, 1], [10, 2]], 2, 'sell'), 11)
        with self.assertRaises(ValueError):
            depth_vwap([[10, 1]], 2, 'buy')
        with self.assertRaises(ValueError):
            depth_vwap([[12, 1], [10, 1]], 2, 'buy')
        with self.assertRaises(ValueError):
            depth_vwap([[10, 1], [10, 1]], 2, 'buy')

    def test_fees_capped_on_premium_not_premium_rate(self):
        self.assertAlmostEqual(trading_fee(100000, 1000, .01), .30)
        self.assertAlmostEqual(trading_fee(100000, 10, .01), .0125)

    def test_piecewise_payoff_and_delivery(self):
        self.assertEqual(expiry_pnl(110, 90, 80, 1, 2, .1), 1.9)
        self.assertAlmostEqual(expiry_pnl(85, 90, 80, 1, 2, .1), 1.9 - 5 - .00015 * 85)
        self.assertAlmostEqual(expiry_pnl(50, 90, 80, 1, 2, .1), 1.9 - 10 - 2 * .00015 * 50)
        self.assertAlmostEqual(expiry_pnl(0, 90, 80, 1, 2, .1), -8.1)
        with self.assertRaises(ValueError):
            expiry_pnl(-1, 90, 80, 1, 2, .1)

    def test_rigorous_put_loss_bound_random_and_extreme_prices(self):
        rng = random.Random(43)
        for _ in range(1000):
            ks = rng.uniform(1, 100000)
            kl = ks * rng.uniform(.01, .99)
            qty = rng.uniform(.01, 3)
            credit = rng.uniform(0, ks - kl) * qty
            fee = .0006 * ks * qty
            bound = (ks - kl + .0003 * (ks + kl)) * qty + fee - credit
            for settlement in (0, kl, ks, ks * 1e6, rng.uniform(0, 2 * ks)):
                self.assertGreaterEqual(expiry_pnl(settlement, ks, kl, qty, credit, fee, 2), -bound - 1e-8)

    @staticmethod
    def instruments():
        return [dict(instrument_name=str(strike), base_currency='BTC', kind='option', option_type='put',
                     instrument_type='linear', quote_currency='USDC', settlement_currency='USDC',
                     state='open', is_active=True, expiration_timestamp=8*DAY, strike=strike,
                     contract_size=1, min_trade_amount=.01) for strike in (70, 80, 85, 90, 95, 100)]

    def test_selection_freeze_no_quote_cherry_pick(self):
        data = self.instruments()
        data.append({**data[0], 'strike': 89, 'state': 'halted'})
        data.append({**data[0], 'strike': 89, 'instrument_type': 'reversed'})
        short, long = select_spread(data, 'BTC', 100, 0)
        self.assertEqual((short['strike'], long['strike']), (90, 80))
        with self.assertRaises(ValueError):
            select_spread(data, 'BTC', 100, 2*DAY)

    def test_budget_floor_and_no_credit_dependent_sizing(self):
        short, long = select_spread(self.instruments(), 'BTC', 100, 0)
        q, evidence = size_amount(short, long, 100)
        self.assertLessEqual(evidence['sizing_loss_bound_ignoring_credit'], 100)
        self.assertLessEqual(evidence['sizing_cash_reserve_upper_bound'], 2500)
        self.assertAlmostEqual(q / .01, round(q / .01))
        short['min_trade_amount'] = long['min_trade_amount'] = 100000
        with self.assertRaises(ValueError):
            size_amount(short, long, 100)

    def test_cash_and_tail_summary_not_probability_from_delta(self):
        result = describe([2.] * 40)
        self.assertEqual(result['bootstrap_5pct_mean_pnl_usdc'], 2)
        self.assertEqual(result['loss_fraction'], 0)
        bad = describe([-100.] * 10 + [1.] * 30)
        self.assertLess(bad['mean_pnl_usdc'], 0)
        self.assertEqual(bad['worst_5pct_mean_pnl_usdc'], -100)

    def test_no_authenticated_or_order_endpoint(self):
        for method in ('buy', 'sell', '../private/buy', 'get_account_summary'):
            with self.assertRaises(ValueError):
                request(method, {}, 'should-not-be-created')
        self.assertTrue(math.isfinite(trading_fee(100, 1, 1)))


if __name__ == '__main__':
    unittest.main()

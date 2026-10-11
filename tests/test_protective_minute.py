import unittest

from orderflow_edge_lab.protective_minute import (
    Bracket, ExitBounds, Minute, benchmark_bounds, excess_bounds, excursion_bounds,
    fixed_risk_quantity, liquidation_cash, replace_bracket, resolve_minute, settle_buy,
)


class ProtectiveMinuteTests(unittest.TestCase):
    def setUp(self):
        self.bracket = Bracket(95, 110, 60, 60)

    def test_inactive_bracket_does_not_use_prior_extrema(self):
        self.assertIsNone(resolve_minute(Minute(0, 100, 120, 90, 100), self.bracket))

    def test_adverse_gap_is_not_filled_at_stop(self):
        result = resolve_minute(Minute(60, 80, 100, 75, 90), self.bracket)
        self.assertEqual((result.lower_price, result.upper_price, result.reason), (80, 80, "stop_gap"))
        self.assertEqual(result.time_interval, (60, 60))

    def test_target_gap_preserves_conservative_limit_and_improvement_sensitivity(self):
        result = resolve_minute(Minute(60, 120, 125, 90, 100), self.bracket)
        self.assertEqual((result.lower_price, result.upper_price, result.reason), (110, 120, "target_gap"))
        self.assertTrue(result.at_open)

    def test_both_touches_have_unknown_order_and_time(self):
        result = resolve_minute(Minute(60, 100, 112, 94, 108), self.bracket)
        self.assertEqual((result.lower_price, result.upper_price), (95, 110))
        self.assertEqual(result.reason, "both_touched_order_unknown")
        self.assertEqual(result.time_interval, (60, 120))

    def test_single_touches_and_no_touch(self):
        stop = resolve_minute(Minute(60, 100, 108, 95, 100), self.bracket)
        target = resolve_minute(Minute(60, 100, 110, 96, 105), self.bracket)
        self.assertEqual((stop.lower_price, stop.reason), (95, "stop_touch"))
        self.assertEqual((target.lower_price, target.reason), (110, "target_touch"))
        self.assertIsNone(resolve_minute(Minute(60, 100, 109, 96, 105), self.bracket))

    def test_scheduled_close_uses_open_not_later_barriers(self):
        result = resolve_minute(Minute(60, 100, 112, 90, 108), self.bracket, market_exit_decided_at=60)
        self.assertEqual((result.lower_price, result.reason), (100, "scheduled_market"))
        with self.assertRaises(ValueError):
            resolve_minute(Minute(60, 100, 112, 90, 108), self.bracket, market_exit_decided_at=120)

    def test_old_bracket_applies_before_close_replacement(self):
        last = Minute(60, 100, 108, 94, 100)
        replacement = Bracket(90, 120, 120, 120)
        self.assertEqual(resolve_minute(last, self.bracket).lower_price, 95)
        new = replace_bracket(self.bracket, replacement, last_processed_minute=60)
        self.assertEqual(new.stop, 90)  # No invented monotonic trailing-stop rule.
        self.assertIsNone(resolve_minute(Minute(120, 100, 108, 94, 100), new))
        with self.assertRaises(ValueError):
            replace_bracket(self.bracket, Bracket(90, 120, 60, 60), last_processed_minute=60)

    def test_signal_quantity_is_capped_and_frozen_across_price_gap(self):
        quantity = fixed_risk_quantity(1000, 100, 99)
        self.assertAlmostEqual(quantity, 1000 / 100.2, places=8)
        normal = settle_buy(1000, quantity, 100)
        self.assertTrue(normal.accepted)
        self.assertGreaterEqual(normal.remaining_cash, 0)
        gap = settle_buy(1000, quantity, 102)
        self.assertFalse(gap.accepted)
        self.assertEqual((gap.remaining_cash, gap.quantity, gap.reason), (1000, 0, "insufficient_cash"))

    def test_risk_sizing_is_not_full_cash_when_stop_is_wide(self):
        self.assertEqual(fixed_risk_quantity(1000, 100, 90), 3)

    def test_costs_charged_on_actual_notionals_and_cash_reconciles(self):
        buy = settle_buy(1000, 3, 100, side_bps=20)
        self.assertAlmostEqual(buy.charged_cost, .6)
        self.assertAlmostEqual(buy.remaining_cash, 699.4)
        self.assertAlmostEqual(liquidation_cash(buy.remaining_cash, 3, 110, side_bps=20), 1028.74)
        # Immediate post-entry protective gap: both costs still charged.
        self.assertAlmostEqual(liquidation_cash(buy.remaining_cash, 3, 100), 998.8)

    def test_fee_induced_rejection_does_not_debit_cash(self):
        self.assertFalse(settle_buy(1000, 10, 100).accepted)
        self.assertTrue(settle_buy(1000, 10, 100, side_bps=0).accepted)
        self.assertEqual(settle_buy(1000, 0, 100).reason, "zero_quantity")

    def test_btc_exit_minute_bounds_not_candle_close(self):
        exit_bounds = ExitBounds(60, 95, 110, "both", False)
        btc = Minute(60, 200, 220, 180, 210)
        lower, upper = benchmark_bounds(200, btc, exit_bounds)
        self.assertAlmostEqual(lower, -1040)
        self.assertAlmostEqual(upper, 960)
        lower, upper = excess_bounds(100, exit_bounds, 200, btc)
        self.assertAlmostEqual(lower, -1500)
        self.assertAlmostEqual(upper, 2000)
        with self.assertRaises(ValueError):
            benchmark_bounds(200, Minute(120, 200, 220, 180, 210), exit_bounds)

    def test_known_open_btc_reference_ignores_later_minute_high_low(self):
        exit_bounds = ExitBounds(60, 80, 80, "gap", True)
        lower, upper = benchmark_bounds(200, Minute(60, 210, 500, 50, 400), exit_bounds)
        self.assertAlmostEqual(lower, 460)
        self.assertEqual(lower, upper)

    def test_exit_minute_extrema_are_uncertain(self):
        completed = [Minute(0, 100, 103, 99, 101)]
        exit_bar = Minute(60, 101, 120, 90, 115)
        result = excursion_bounds(100, completed, exit_bar, ExitBounds(60, 95, 110, "both", False), entry_at=0)
        for observed, expected in zip(result["mfe_bps"], (300, 2000)):
            self.assertAlmostEqual(observed, expected)
        for observed, expected in zip(result["mae_bps"], (-1000, -100)):
            self.assertAlmostEqual(observed, expected)

    def test_open_exit_does_not_take_after_exit_range(self):
        result = excursion_bounds(100, [Minute(0, 100, 101, 100, 100)],
                                  Minute(60, 80, 500, 1, 400), ExitBounds(60, 80, 80, "gap", True), entry_at=0)
        self.assertAlmostEqual(result["mfe_bps"][0], 100)
        self.assertEqual(result["mfe_bps"][0], result["mfe_bps"][1])
        self.assertAlmostEqual(result["mae_bps"][0], -2000)
        self.assertEqual(result["mae_bps"][0], result["mae_bps"][1])

    def test_post_exit_extrema_and_gaps_refused(self):
        bar = Minute(180, 100, 105, 90, 100)
        exit_bounds = ExitBounds(180, 95, 95, "stop", False)
        for completed in ([bar], [Minute(0, 100, 101, 99, 100)],
                          [Minute(0, 100, 101, 99, 100), Minute(120, 100, 101, 99, 100)]):
            with self.assertRaises(ValueError):
                excursion_bounds(100, completed, bar, exit_bounds, entry_at=0)
        with self.assertRaises(ValueError):
            excursion_bounds(100, [Minute(120, 100, 101, 99, 100)], bar, exit_bounds, entry_at=0)

    def test_invalid_numeric_and_clock_inputs_fail_closed(self):
        for clock in (True, 1, 60.0, -60):
            with self.assertRaises(ValueError):
                Minute(clock, 100, 101, 99, 100)
        for value in (float("nan"), float("inf"), 0, -1):
            with self.assertRaises(ValueError):
                Minute(0, value, 101, 99, 100)
        with self.assertRaises(ValueError):
            Minute(0, 100, 99, 98, 100)
        with self.assertRaises(ValueError):
            Bracket(110, 95, 0, 0)
        with self.assertRaises(ValueError):
            Bracket(95, 110, 120, 60)
        for cost in (-1, 10000, float("nan")):
            with self.assertRaises(ValueError):
                settle_buy(1000, 1, 100, side_bps=cost)

    def test_derived_overflow_fails_closed(self):
        with self.assertRaises(ValueError):
            liquidation_cash(1, 1e308, 1e308)
        with self.assertRaises(ValueError):
            settle_buy(1000, 1e308, 1e308)
        with self.assertRaises(ValueError):
            benchmark_bounds(1e-308, Minute(60, 1e308, 1e308, 1e308, 1e308),
                             ExitBounds(60, 100, 100, "open", True))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from collections import deque
import unittest

from orderflow_edge_lab.lsk_regime_router import _classify, _directional_price_response_efficiency


def _state(**overrides):
    row = {
        "spread_bps": 1.0,
        "local_range_15s_bps": 10.0,
        "local_quote_updates_per_second_15s": 10.0,
        "rolling_trade_count_10s": 10,
        "signal_strength_multiple": 1.5,
        "abs_return_to_spread_15s": 3.0,
        "directional_price_response_efficiency": 10.0,
        "btc_flow_alignment": "aligned",
    }
    row.update(overrides)
    return row


def _history():
    return deque(
        [
            _state(abs_return_to_spread_15s=1.0, directional_price_response_efficiency=8.0),
            _state(abs_return_to_spread_15s=2.0, directional_price_response_efficiency=9.0),
            _state(abs_return_to_spread_15s=3.0, directional_price_response_efficiency=10.0),
            _state(abs_return_to_spread_15s=4.0, directional_price_response_efficiency=11.0),
            _state(abs_return_to_spread_15s=5.0, directional_price_response_efficiency=12.0),
        ],
        maxlen=20,
    )


class LskRegimeRouterTests(unittest.TestCase):
    def test_directional_efficiency_respects_signal_side(self):
        self.assertEqual(_directional_price_response_efficiency(6.0, 1, 2.0), 3.0)
        self.assertEqual(_directional_price_response_efficiency(-6.0, 1, 2.0), -3.0)
        self.assertEqual(_directional_price_response_efficiency(-6.0, -1, 2.0), 3.0)
        self.assertEqual(_directional_price_response_efficiency(6.0, -1, 2.0), -3.0)

    def test_routes_original_when_participation_and_directional_response_expand(self):
        route, diagnostic = _classify(
            _state(
                rolling_trade_count_10s=20,
                local_quote_updates_per_second_15s=20.0,
                local_range_15s_bps=20.0,
                directional_price_response_efficiency=20.0,
                abs_return_to_spread_15s=3.0,
            ),
            _history(),
            min_prior=5,
        )
        self.assertEqual(route, "original")
        self.assertEqual(diagnostic["reason"], "continuation")

    def test_routes_reversed_when_displacement_is_mature_and_directional_response_collapses(self):
        route, diagnostic = _classify(
            _state(
                rolling_trade_count_10s=5,
                local_quote_updates_per_second_15s=8.0,
                local_range_15s_bps=12.0,
                directional_price_response_efficiency=5.0,
                abs_return_to_spread_15s=6.0,
            ),
            _history(),
            min_prior=5,
        )
        self.assertEqual(route, "reversed")
        self.assertEqual(diagnostic["reason"], "exhaustion")

    def test_routes_no_trade_when_state_is_ambiguous(self):
        route, diagnostic = _classify(
            _state(
                rolling_trade_count_10s=8,
                local_quote_updates_per_second_15s=9.0,
                directional_price_response_efficiency=10.0,
                abs_return_to_spread_15s=3.0,
            ),
            _history(),
            min_prior=5,
        )
        self.assertEqual(route, "no_trade")
        self.assertEqual(diagnostic["reason"], "ambiguous")

    def test_routes_no_trade_before_causal_baseline_exists(self):
        route, diagnostic = _classify(_state(), deque(list(_history())[:4], maxlen=20), min_prior=5)
        self.assertEqual(route, "no_trade")
        self.assertEqual(diagnostic["reason"], "insufficient_causal_baseline")

    def test_original_rejects_against_signal_price_response_even_with_high_activity(self):
        route, _ = _classify(
            _state(
                rolling_trade_count_10s=20,
                local_quote_updates_per_second_15s=20.0,
                local_range_15s_bps=20.0,
                directional_price_response_efficiency=-2.0,
                abs_return_to_spread_15s=3.0,
            ),
            _history(),
            min_prior=5,
        )
        self.assertNotEqual(route, "original")


if __name__ == "__main__":
    unittest.main()

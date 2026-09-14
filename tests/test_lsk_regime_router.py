from collections import deque

from orderflow_edge_lab.lsk_regime_router import _classify


def _state(**overrides):
    row = {
        "spread_bps": 1.0,
        "local_range_15s_bps": 10.0,
        "local_quote_updates_per_second_15s": 10.0,
        "rolling_trade_count_10s": 10,
        "signal_strength_multiple": 1.5,
        "abs_return_to_spread_15s": 3.0,
        "price_response_efficiency": 10.0,
        "btc_flow_alignment": "aligned",
    }
    row.update(overrides)
    return row


def _history():
    return deque(
        [
            _state(abs_return_to_spread_15s=1.0),
            _state(abs_return_to_spread_15s=2.0),
            _state(abs_return_to_spread_15s=3.0),
            _state(abs_return_to_spread_15s=4.0),
            _state(abs_return_to_spread_15s=5.0),
        ],
        maxlen=20,
    )


def test_routes_original_when_participation_and_response_expand():
    route, diagnostic = _classify(
        _state(
            rolling_trade_count_10s=20,
            local_quote_updates_per_second_15s=20.0,
            local_range_15s_bps=20.0,
            price_response_efficiency=20.0,
            abs_return_to_spread_15s=3.0,
        ),
        _history(),
        min_prior=5,
    )
    assert route == "original"
    assert diagnostic["reason"] == "continuation"


def test_routes_reversed_when_displacement_is_mature_and_response_collapses():
    route, diagnostic = _classify(
        _state(
            rolling_trade_count_10s=5,
            local_quote_updates_per_second_15s=8.0,
            local_range_15s_bps=12.0,
            price_response_efficiency=5.0,
            abs_return_to_spread_15s=6.0,
        ),
        _history(),
        min_prior=5,
    )
    assert route == "reversed"
    assert diagnostic["reason"] == "exhaustion"


def test_routes_no_trade_when_state_is_ambiguous():
    route, diagnostic = _classify(
        _state(
            rolling_trade_count_10s=8,
            local_quote_updates_per_second_15s=9.0,
            price_response_efficiency=10.0,
            abs_return_to_spread_15s=3.0,
        ),
        _history(),
        min_prior=5,
    )
    assert route == "no_trade"
    assert diagnostic["reason"] == "ambiguous"


def test_routes_no_trade_before_causal_baseline_exists():
    route, diagnostic = _classify(_state(), deque(list(_history())[:4], maxlen=20), min_prior=5)
    assert route == "no_trade"
    assert diagnostic["reason"] == "insufficient_causal_baseline"

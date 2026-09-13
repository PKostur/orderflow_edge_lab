from copy import deepcopy
import unittest

from orderflow_edge_lab.gamma_exposure import (
    append_comparison_history,
    black_scholes_gamma,
    build_gamma_snapshot,
    verify_gamma_snapshot,
)


PROTOCOL = {
    "protocol_name": "gamma-exposure-trial-v1",
    "snapshot_definition": {
        "minimum_open_interest_btc": 0.0,
        "top_strikes_each_side": 5,
        "balance_flip_proxy": {"enabled": True, "spot_ratio_min": 0.6, "spot_ratio_max": 1.4, "grid_points": 41}
    },
    "comparison_definition": {
        "minimum_forward_snapshots_before_descriptive_state_comparison": 12,
        "minimum_completed_strategy_outcomes_before_any_pnl_by_gamma_state_table": 5
    }
}


def fixtures():
    expiry = 1_800_000_000_000
    instruments = [
        {"instrument_name": "BTC-X-90000-C", "strike": 90000, "option_type": "call", "expiration_timestamp": expiry, "contract_size": 1, "is_active": True},
        {"instrument_name": "BTC-X-90000-P", "strike": 90000, "option_type": "put", "expiration_timestamp": expiry, "contract_size": 1, "is_active": True},
        {"instrument_name": "BTC-X-110000-C", "strike": 110000, "option_type": "call", "expiration_timestamp": expiry, "contract_size": 1, "is_active": True},
        {"instrument_name": "BTC-X-110000-P", "strike": 110000, "option_type": "put", "expiration_timestamp": expiry, "contract_size": 1, "is_active": True}
    ]
    summaries = [
        {"instrument_name": "BTC-X-90000-C", "open_interest": 12, "mark_iv": 55, "underlying_price": 100000, "interest_rate": 0.01},
        {"instrument_name": "BTC-X-90000-P", "open_interest": 3, "mark_iv": 55, "underlying_price": 100000, "interest_rate": 0.01},
        {"instrument_name": "BTC-X-110000-C", "open_interest": 2, "mark_iv": 60, "underlying_price": 100000, "interest_rate": 0.01},
        {"instrument_name": "BTC-X-110000-P", "open_interest": 9, "mark_iv": 60, "underlying_price": 100000, "interest_rate": 0.01}
    ]
    return instruments, summaries


def reports(trades=0, pnl=0.0):
    ena = {"status": "collecting", "metrics": {"trades": trades, "compounded_return": pnl / 1000.0}, "claims": {}}
    trend = {"status": "collecting", "metrics": {"completed_symbol_trades": trades, "open_symbol_positions": 0, "net_pnl_per_1000_usdt": pnl}, "claims": {}}
    xs = {"status": "collecting", "metrics": {"completed_holding_periods": trades, "open_symbol_positions": 0, "net_pnl_per_1000_usdt": pnl}, "claims": {}}
    return ena, trend, xs


class GammaExposureTests(unittest.TestCase):
    def test_black_scholes_gamma_positive(self):
        self.assertGreater(black_scholes_gamma(100.0, 100.0, 0.5, 0.5, 0.01), 0)

    def test_snapshot_is_signed_proxy_and_manifest_verifies(self):
        instruments, summaries = fixtures()
        snapshot = build_gamma_snapshot(instruments, summaries, PROTOCOL, observed_at_ms=1_790_000_000_000)
        self.assertGreater(snapshot["metrics"]["gross_gamma_exposure_usd_per_1pct"], 0)
        self.assertGreater(snapshot["metrics"]["call_gamma_exposure_usd_per_1pct"], 0)
        self.assertGreater(snapshot["metrics"]["put_gamma_exposure_usd_per_1pct"], 0)
        self.assertFalse(snapshot["limitations"]["dealer_positioning_observed"])
        self.assertFalse(snapshot["claims"]["live_order_transmission_supported"])
        self.assertTrue(verify_gamma_snapshot(snapshot))
        tampered = deepcopy(snapshot)
        tampered["metrics"]["reference_spot_usd"] += 1
        self.assertFalse(verify_gamma_snapshot(tampered))

    def test_history_waits_for_predeclared_sample_guards(self):
        instruments, summaries = fixtures()
        snapshot = build_gamma_snapshot(instruments, summaries, PROTOCOL, observed_at_ms=1_790_000_000_000)
        ena, trend, xs = reports()
        history = append_comparison_history(snapshot, ena, trend, xs, PROTOCOL)
        self.assertEqual(history["status"], "collecting_gamma_history")
        self.assertEqual(history["guards"]["observed_forward_snapshots"], 1)
        self.assertFalse(history["claims"]["strategy_parameters_changed"])

    def test_history_can_reach_descriptive_ready_without_parameter_selection(self):
        instruments, summaries = fixtures()
        first = build_gamma_snapshot(instruments, summaries, PROTOCOL, observed_at_ms=1_790_000_000_000)
        records = []
        for i in range(11):
            trades = min(i, 5)
            records.append({
                "observed_at_utc": f"2026-09-13T{i:02d}:00:00Z",
                "gamma": dict(first["metrics"]),
                "strategy": {
                    "ena_1h": {"status": "collecting", "completed_outcomes": trades, "open_positions": 0, "pnl_per_1000_usdt": float(i)},
                    "trend_8h": {"status": "collecting", "completed_outcomes": 0, "open_positions": 0, "pnl_per_1000_usdt": 0.0},
                    "cross_sectional_30d_7d": {"status": "collecting", "completed_outcomes": 0, "open_positions": 0, "pnl_per_1000_usdt": 0.0}
                }
            })
        later = build_gamma_snapshot(instruments, summaries, PROTOCOL, observed_at_ms=1_790_100_000_000)
        ena, trend, xs = reports(trades=5, pnl=12.0)
        history = append_comparison_history(later, ena, trend, xs, PROTOCOL, {"records": records})
        self.assertEqual(history["guards"]["observed_forward_snapshots"], 12)
        self.assertGreaterEqual(history["guards"]["observed_completed_outcome_increments"], 5)
        self.assertEqual(history["status"], "descriptive_comparison_ready")
        self.assertFalse(history["claims"]["gamma_threshold_selected_from_strategy_pnl"])


if __name__ == "__main__":
    unittest.main()

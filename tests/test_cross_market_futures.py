from __future__ import annotations

import json
from pathlib import Path
import unittest

from orderflow_edge_lab.cross_market_futures import (
    FUTURES_SPECS,
    audit_native_futures_events,
    extra_round_trip_friction_bps,
    futures_spec,
)
from orderflow_edge_lab.data import MarketEvent


class CrossMarketFuturesTests(unittest.TestCase):
    def test_frozen_protocol_invariants(self) -> None:
        cfg = json.loads(Path("config/cross_market_futures_v1.json").read_text())
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_NON_CRYPTO_RESULTS")
        self.assertEqual([x["root"] for x in cfg["universe"]], ["ES", "NQ", "GC", "CL"])
        transfer = cfg["signal_transfer"]
        self.assertEqual(transfer["absolute_aggressive_flow_ratio_threshold"], 0.25)
        self.assertEqual(transfer["absolute_book_imbalance_threshold"], 0.25)
        self.assertEqual(transfer["absolute_microprice_normalized_edge_threshold"], 0.20)
        self.assertEqual(transfer["minimum_trade_prints"], 5)
        self.assertEqual(transfer["same_family_same_direction_cooldown_seconds"], 2)
        self.assertEqual(transfer["forward_horizons_seconds"], [1, 5, 15, 30])
        self.assertFalse(transfer["market_specific_threshold_tuning"])
        self.assertEqual(cfg["economics"]["additional_round_trip_friction_ticks"], [0.0, 1.0, 2.0])
        self.assertEqual(cfg["economics"]["leverage"], 1.0)
        self.assertTrue(cfg["d0_transfer_survival"]["no_v1_direct_promotion"])
        self.assertFalse(cfg["claims"]["candidate_promoted"])
        self.assertFalse(cfg["claims"]["live_execution_supported"])
        self.assertFalse(cfg["claims"]["leverage_supported"])

    def test_contract_specs_and_tick_values(self) -> None:
        self.assertEqual(set(FUTURES_SPECS), {"ES", "NQ", "GC", "CL"})
        self.assertAlmostEqual(futures_spec("es").tick_value_usd, 12.5)
        self.assertAlmostEqual(futures_spec("NQ").tick_value_usd, 5.0)
        self.assertAlmostEqual(futures_spec("GC").tick_value_usd, 10.0)
        self.assertAlmostEqual(futures_spec("CL").tick_value_usd, 10.0)

    def test_market_native_tick_stress_converts_to_bps(self) -> None:
        self.assertAlmostEqual(
            extra_round_trip_friction_bps(root="ES", price=5000.0, total_ticks=1.0),
            0.5,
        )
        self.assertAlmostEqual(
            extra_round_trip_friction_bps(root="ES", price=5000.0, total_ticks=2.0),
            1.0,
        )

    def test_native_event_audit_accepts_tick_aligned_single_contract(self) -> None:
        events = [
            MarketEvent(1_700_000_000_000_000_000, "ESZ26", "QUOTE", bid=5000.00, ask=5000.25),
            MarketEvent(1_700_000_000_100_000_000, "ESZ26", "TRADE", price=5000.25, size=2.0, bid=5000.00, ask=5000.25),
        ]
        report = audit_native_futures_events(events, root="ES")
        self.assertTrue(report["passed"])
        self.assertEqual(report["off_tick_prices"], 0)
        self.assertEqual(report["symbols"], ["ESZ26"])

    def test_native_event_audit_rejects_roll_mix_and_off_tick_price(self) -> None:
        events = [
            MarketEvent(1_700_000_000_000_000_000, "ESZ26", "TRADE", price=5000.25, size=1.0),
            MarketEvent(1_700_000_000_100_000_000, "ESH27", "TRADE", price=5000.10, size=1.0),
        ]
        report = audit_native_futures_events(events, root="ES")
        self.assertFalse(report["passed"])
        self.assertIn("multiple_native_contract_symbols", report["failures"])
        self.assertIn("off_tick_prices", report["failures"])


if __name__ == "__main__":
    unittest.main()

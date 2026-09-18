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
from orderflow_edge_lab.cross_market_futures_transfer import evaluate_feature_rows
from orderflow_edge_lab.data import MarketEvent
from orderflow_edge_lab.dxfeed_futures_features import build_dxfeed_level1_feature_rows


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
        clarification = Path("research/cross_market_futures_v1/FREEZE_CLARIFICATION.md").read_text()
        self.assertIn("top-10 displayed depth imbalance", clarification)
        self.assertIn("ineligible for CMF-H2", clarification)
        quote_age = Path("research/cross_market_futures_v1/FREEZE_CLARIFICATION_QUOTE_AGE.md").read_text()
        self.assertIn("1.0 second", quote_age)

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

    @staticmethod
    def _synthetic_dxfeed_rows() -> list[dict[str, object]]:
        base = 1_700_000_000_000_000_000
        rows: list[dict[str, object]] = []
        # Engineering fixture only: monotonic ES quote/trade events with a drifting
        # price and persistent bid-heavy BBO. It is not research evidence.
        for second in range(0, 41):
            bid = 5000.00 + 0.25 * second
            quote_ts = base + second * 1_000_000_000
            rows.append(
                {
                    "timestamp": quote_ts,
                    "symbol": "ESZ26",
                    "kind": "QUOTE",
                    "bid": bid,
                    "ask": bid + 0.25,
                    "bid_size": 9.0,
                    "ask_size": 1.0,
                    "sequence": second * 2 + 1,
                }
            )
            if second <= 5:
                rows.append(
                    {
                        "timestamp": quote_ts + 100_000_000,
                        "symbol": "ESZ26",
                        "kind": "TRADE",
                        "price": bid + 0.25,
                        "size": 1.0,
                        "side": "BUY",
                        "sequence": second * 2 + 2,
                    }
                )
        return rows

    def test_level1_builder_and_transfer_replay_fail_closed_for_h2(self) -> None:
        built = build_dxfeed_level1_feature_rows(self._synthetic_dxfeed_rows())
        self.assertTrue(built.h1_eligible)
        self.assertTrue(built.h3_eligible)
        self.assertEqual(built.ambiguous_same_timestamp_bbo_uses_blocked, 0)
        self.assertEqual(built.stale_bbo_uses_blocked, 0)
        report = evaluate_feature_rows(built.rows, root="ES")
        counts = report["signal_counts_by_family"]
        self.assertGreater(counts.get("aggressive_flow_ratio", 0), 0)
        self.assertGreater(counts.get("microprice_normalized_edge", 0), 0)
        self.assertEqual(counts.get("book_imbalance_10", 0), 0)
        eligibility = report["hypothesis_observation_eligibility"]
        self.assertFalse(eligibility["CMF-H2_book_imbalance_10_observed"])
        self.assertTrue(eligibility["H2_requires_true_top10_depth"])
        self.assertFalse(report["claims"]["candidate_promoted"])
        self.assertFalse(report["claims"]["live_execution_supported"])

    def test_transfer_reversed_control_and_tick_friction_are_explicit(self) -> None:
        built = build_dxfeed_level1_feature_rows(self._synthetic_dxfeed_rows())
        report = evaluate_feature_rows(built.rows, root="ES")
        rows = report["observations"]
        self.assertTrue(any(r["control"] == "original" for r in rows))
        self.assertTrue(any(r["control"] == "reversed_same_decision" for r in rows))
        one_tick = [r for r in rows if r["extra_round_trip_ticks"] == 1.0]
        self.assertTrue(one_tick)
        self.assertTrue(all(r["extra_friction_bps"] > 0 for r in one_tick))
        self.assertTrue(all(r["commission_exchange_fees_resolved"] is False for r in rows))

    def test_default_futures_quote_age_is_one_second(self) -> None:
        base = 1_700_000_000_000_000_000
        rows = [
            {"timestamp": base, "symbol": "ESZ26", "kind": "QUOTE", "bid": 5000.0, "ask": 5000.25, "bid_size": 9, "ask_size": 1},
            {"timestamp": base + 1_500_000_000, "symbol": "ESZ26", "kind": "TRADE", "price": 5000.25, "size": 1, "side": "BUY"},
        ]
        built = build_dxfeed_level1_feature_rows(rows)
        trade = [r for r in built.rows if r["event_type"] == "trade"][0]
        self.assertIsNone(trade["best_bid"])
        self.assertEqual(built.stale_bbo_uses_blocked, 1)

    def test_stale_and_ambiguous_bbo_state_is_not_used(self) -> None:
        base = 1_700_000_000_000_000_000
        stale_rows = [
            {"timestamp": base, "symbol": "ESZ26", "kind": "QUOTE", "bid": 5000.0, "ask": 5000.25, "bid_size": 9, "ask_size": 1},
            {"timestamp": base + 3_000_000_000, "symbol": "ESZ26", "kind": "TRADE", "price": 5000.25, "size": 1, "side": "BUY"},
        ]
        stale = build_dxfeed_level1_feature_rows(stale_rows, max_quote_age_seconds=2.0)
        trade = [r for r in stale.rows if r["event_type"] == "trade"][0]
        self.assertIsNone(trade["best_bid"])
        self.assertEqual(stale.stale_bbo_uses_blocked, 1)

        ambiguous_rows = [
            {"timestamp": base, "symbol": "ESZ26", "kind": "QUOTE", "bid": 5000.0, "ask": 5000.25, "bid_size": 9, "ask_size": 1},
            {"timestamp": base, "symbol": "ESZ26", "kind": "TRADE", "price": 5000.25, "size": 1, "side": "BUY"},
        ]
        ambiguous = build_dxfeed_level1_feature_rows(ambiguous_rows)
        trade2 = [r for r in ambiguous.rows if r["event_type"] == "trade"][0]
        self.assertIsNone(trade2["best_bid"])
        self.assertEqual(ambiguous.ambiguous_same_timestamp_bbo_uses_blocked, 1)


if __name__ == "__main__":
    unittest.main()

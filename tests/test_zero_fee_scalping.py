from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.zero_fee_scalping import (
    Contract, FeePolicy, ScalpConfig, ScalpingError, evaluate, load_events, screen_promotional_pairs, simulate,
)


BASE = int(datetime(2026, 10, 6, 10, tzinfo=timezone.utc).timestamp()) * 1_000_000_000
SYMBOL = "TEST_USDT"


def fees(**changes):
    return {"venue": "mexc_futures", "market": "linear_usdt_perpetual", "symbol": SYMBOL,
            "execution_channel": "api", "account_eligible": True, "region_eligible": True,
            "channel_eligible": True, "maker_bps": 0, "taker_bps": 0, "normal_taker_bps": 8,
            "terms_url": "https://example.test/terms", "terms_snapshot_sha256": "a" * 64,
            "observed_at_ns": BASE, "valid_from_ns": BASE, "valid_until_ns": BASE + 3600 * 1_000_000_000,
            "quota_kind": "unlimited", **changes}


def depth(ms, *, bid=100, ask=100.01, capacity=1000000, **extra):
    return {"symbol": SYMBOL, "feature_schema_version": 2, "event_type": "depth", "depth_applied": True,
            "received_at_ns": BASE + ms * 1_000_000, "exchange_ts_ms": BASE // 1_000_000 + ms,
            "best_bid": bid, "best_ask": ask, "best_bid_contract_volume": capacity,
            "best_ask_contract_volume": capacity, "true_depth_gaps_seen": 0, **extra}


def trade(ms, *, side=1):
    return {"symbol": SYMBOL, "feature_schema_version": 2, "event_type": "trade",
            "received_at_ns": BASE + ms * 1_000_000, "exchange_ts_ms": BASE // 1_000_000 + ms,
            "best_bid": 100, "best_ask": 100.01, "microprice": 100.009 if side == 1 else 100.001,
            "rolling_buy_volume": 80 if side == 1 else 20, "rolling_sell_volume": 20 if side == 1 else 80,
            "rolling_trade_count": 10, "book_imbalance_10": 0.8 * side, "true_depth_gaps_seen": 0}


def rows():
    return sorted([depth(ms) for ms in range(0, 20100, 100)] + [trade(10001), trade(10101)],
                  key=lambda r: r["received_at_ns"])


CONTRACT = Contract(SYMBOL, 0.1, 1, 1, 8, BASE + 6 * 3600 * 1_000_000_000, BASE - 60 * 1_000_000_000)


class ScalpingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "features.jsonl"

    def load(self, data):
        self.path.write_text("".join(json.dumps(r) + "\n" for r in data), encoding="utf-8")
        return load_events(self.path, SYMBOL)

    def run_sim(self, data=None, *, cfg=None, fee_record=None, reverse=False, horizon=5):
        ev, qs, ts = self.load(rows() if data is None else data)
        return simulate(ev, qs, ts, CONTRACT, fees() if fee_record is None else fee_record,
                        cfg or ScalpConfig(), channel="api", horizon=horizon, reverse=reverse)

    def test_flat_market_loses_spread_slippage_and_normal_fees(self):
        report = self.run_sim()
        self.assertEqual(len(report["trades"]), 1)  # second signal overlaps the position
        t = report["trades"][0]
        self.assertEqual(t["contracts"], 9)  # contract units; rounded down to step
        self.assertAlmostEqual(t["entry_price"], 100.01 * 1.0001)
        self.assertAlmostEqual(t["exit_price"], 100 * 0.9999)
        self.assertAlmostEqual(t["executable_gross_pnl_usdt"], 0.9 * (t["exit_price"] - t["entry_price"]))
        self.assertLess(t["hypothetical_zero_fee_pnl_usdt"], 0)
        self.assertAlmostEqual(t["normal_fee_pnl_usdt"], t["executable_gross_pnl_usdt"] -
                               (t["entry_notional_usdt"] + t["exit_notional_usdt"]) * 0.0008)
        self.assertEqual(t["holding_seconds"], 5)
        self.assertTrue(t["documented_zero_fee_round_trip"])

    def test_short_pnl_and_each_leg_fee_use_actual_notional(self):
        r = self.run_sim(reverse=True, fee_record=fees(channel_eligible=False))
        t = r["trades"][0]
        self.assertAlmostEqual(t["executable_gross_pnl_usdt"], -t["contracts"] * 0.1 * (t["exit_price"] - t["entry_price"]))
        self.assertEqual(t["entry_fee_bps"], 8)
        self.assertFalse(t["documented_zero_fee_round_trip"])

    def test_cached_trade_quotes_do_not_refresh_depth(self):
        data = [depth(ms) for ms in range(0, 10100, 100)] + [trade(ms) for ms in range(10001, 20000, 100)]
        r = self.run_sim(sorted(data, key=lambda row: row["received_at_ns"]))
        self.assertEqual(len(r["unresolved_positions"]), 1)
        self.assertEqual(r["unresolved_positions"][0]["reason"], "stale_book")
        self.assertFalse(r["pnl_complete"])
        self.assertEqual(r["trades"], [])

    def test_stale_exchange_timestamp_rejects_recently_received_depth(self):
        data = rows()
        for row in data:
            if row["event_type"] == "depth":
                row["exchange_ts_ms"] -= 2000
        r = self.run_sim(data)
        self.assertEqual(r["trades"], [])
        self.assertGreater(r["entry_rejections"]["stale_exchange_book_or_clock_skew"], 0)

    def test_late_trade_packets_cannot_trigger_fresh_signals(self):
        data = rows()
        for row in data:
            if row["event_type"] == "trade":
                row["exchange_ts_ms"] -= 2000
        r = self.run_sim(data)
        self.assertEqual(r["signal_attempts"], 0)
        self.assertEqual(r["trades"], [])

    def test_signal_cannot_see_later_depth_at_identical_timestamp(self):
        data = [depth(0), trade(10001), depth(10001)] + [depth(ms) for ms in range(10100, 20100, 100)]
        r = self.run_sim(data)
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["entry_rejections"], {"stale_book": 1})

    def test_entry_uses_quote_observed_before_delayed_arrival(self):
        data = rows()
        data.append(depth(10252, bid=100.05, ask=100.06))  # after arrival at 10251
        data.sort(key=lambda r: r["received_at_ns"])
        t = self.run_sim(data)["trades"][0]
        self.assertAlmostEqual(t["entry_price"], 100.01 * 1.0001)

    def test_insufficient_entry_depth_rejects_instead_of_inventing_fill(self):
        data = rows()
        for r in data:
            if r["event_type"] == "depth":
                r["best_ask_contract_volume"] = 1
        r = self.run_sim(data)
        self.assertFalse(r["trades"])
        self.assertGreater(r["entry_rejections"]["entry_capacity"], 0)

    def test_unfillable_exit_halts_and_retains_open_inventory(self):
        data = rows()
        for row in data:
            if row["event_type"] == "depth" and row["received_at_ns"] >= BASE + 15000 * 1_000_000:
                row["best_bid_contract_volume"] = 1
        r = self.run_sim(data)
        self.assertEqual(r["status"], "incomplete_execution")
        self.assertEqual(r["unresolved_positions"][0]["reason"], "exit_capacity")
        self.assertEqual(r["signal_attempts"], 1)

    def test_gap_recovery_cannot_hide_disruption_during_open_position(self):
        data = rows()
        data.append(depth(12050, recovered_after_gap=True))
        data.sort(key=lambda row: row["received_at_ns"])
        r = self.run_sim(data)
        self.assertFalse(r["pnl_complete"])
        self.assertEqual(r["unresolved_positions"][0]["reason"], "book_disruption")

    def test_flow_reversal_exits_with_latency(self):
        data = sorted(rows() + [trade(11001, side=-1)], key=lambda row: row["received_at_ns"])
        t = self.run_sim(data)["trades"][0]
        self.assertEqual(t["exit_reason"], "flow_reversal")
        self.assertEqual(t["exit_at_ns"], BASE + 11251 * 1_000_000)

    def test_price_stop_uses_delayed_executable_price(self):
        data = rows()
        for row in data:
            if row["event_type"] == "depth" and row["received_at_ns"] >= BASE + 11000 * 1_000_000:
                row["best_bid"], row["best_ask"] = 99.8, 99.81
        t = self.run_sim(data)["trades"][0]
        self.assertEqual(t["exit_reason"], "stop_loss")
        self.assertEqual(t["exit_at_ns"], BASE + 11250 * 1_000_000)
        self.assertAlmostEqual(t["exit_price"], 99.8 * 0.9999)

    def test_funding_guard_excludes_entire_possible_holding_window(self):
        ev, qs, ts = self.load(rows())
        near = replace(CONTRACT, next_settlement_ns=BASE + 60 * 1_000_000_000)
        r = simulate(ev, qs, ts, near, fees(), ScalpConfig(), channel="api", horizon=5)
        self.assertEqual(r["trades"], [])
        self.assertGreater(r["entry_rejections"]["funding_window"], 0)

    def test_capture_tail_does_not_create_unobserved_exit(self):
        self.assertEqual(self.run_sim(horizon=120)["entry_rejections"], {"capture_tail": 2})

    def test_reconnects_and_observation_regression_are_rejected(self):
        with self.assertRaises(ScalpingError):
            self.load(rows() + [{"record_type": "session_summary", "reconnects": 1}])
        with self.assertRaises(ScalpingError):
            self.load([depth(100), depth(0)])

    def test_invalid_configuration_fails_closed(self):
        for cfg in (replace(ScalpConfig(), max_quote_age_ms=0), replace(ScalpConfig(), max_top_depth_fraction=0.5),
                    replace(ScalpConfig(), latency_ms=float("nan")), replace(ScalpConfig(), funding_guard_seconds=10)):
            with self.subTest(cfg=cfg), self.assertRaises(ScalpingError):
                cfg.validate()

    def test_evaluate_hashes_inputs_and_keeps_claims_false(self):
        self.load(rows() + [{"record_type": "session_summary", "reconnects": 0}])
        root = Path(self.temp.name)
        contract_path, funding_path, fee_path, protocol_path = [root / f"{name}.json" for name in ("contracts", "funding", "fees", "protocol")]
        contract_path.write_text(json.dumps({"success": True, "data": [{"symbol": SYMBOL, "quoteCoin": "USDT", "settleCoin": "USDT",
                                  "state": 0, "contractSize": 0.1, "minVol": 1, "volUnit": 1}]}))
        funding_path.write_text(json.dumps({"success": True, "data": {"symbol": SYMBOL, "collectCycle": 8,
                                              "nextSettleTime": CONTRACT.next_settlement_ns // 1_000_000,
                                              "timestamp": CONTRACT.funding_observed_ns // 1_000_000}}))
        fee_path.write_text(json.dumps(fees()))
        protocol_path.write_text(json.dumps({**ScalpConfig().__dict__, "status": "development_only", "venue": "mexc_futures",
                                             "execution_channel": "api", "horizons_seconds": [5],
                                             "stress_cases": [{"name": "base", "latency_ms": 250, "slippage_bps_per_leg": 1}]}))
        report = evaluate(self.path, contract_path, funding_path, fee_path, protocol_path, symbol=SYMBOL)
        self.assertEqual(report["trial_count"], 2)
        self.assertEqual(report["dependence_clusters"], 1)
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertTrue(all(len(v) == 64 for v in report["source_hashes"].values()))
        self.load(rows())
        with self.assertRaisesRegex(ScalpingError, "terminal clean session_summary"):
            evaluate(self.path, contract_path, funding_path, fee_path, protocol_path, symbol=SYMBOL)

    def test_pair_screen_uses_advertised_fees_and_liquidity_not_pnl(self):
        root = Path(self.temp.name)
        contract_path, ticker_path = root / "contracts.json", root / "tickers.json"
        specs = [("A", 0, 0, "crypto"), ("B", 0, 0.0001, "crypto"), ("C", 0, 0, "stock"), ("D", None, 0, "crypto")]
        contract_path.write_text(json.dumps({"success": True, "data": [
            {"symbol": base + "_USDT", "baseCoin": base, "quoteCoin": "USDT", "settleCoin": "USDT", "state": 0,
             "makerFeeRate": maker, "takerFeeRate": taker, "conceptPlate": concept} for base, maker, taker, concept in specs]}))
        ticker_path.write_text(json.dumps({"success": True, "data": [
            {"symbol": base + "_USDT", "bid1": 100, "ask1": 100.01, "amount24": 20000000} for base, *_ in specs]}))
        r = screen_promotional_pairs(contract_path, ticker_path)
        self.assertEqual([row["symbol"] for row in r["selected"]], ["A_USDT"])
        self.assertFalse(r["selected"][0]["api_promotion_verified"])
        self.assertFalse(r["selection_rule"]["strategy_pnl_used"])


class FeeEligibilityTests(unittest.TestCase):
    def test_api_exclusion_unknown_account_and_maker_only_cannot_be_zero_taker(self):
        for record in (fees(channel_eligible=False), fees(account_eligible=None), fees(quota_kind="unknown")):
            rate, reasons = FeePolicy(record, symbol=SYMBOL, channel="api").rate(BASE + 1, 100)
            self.assertEqual(rate, 8)
            self.assertTrue(reasons)
        rate, reasons = FeePolicy(fees(taker_bps=8), symbol=SYMBOL, channel="api").rate(BASE + 1, 100)
        self.assertEqual(rate, 8)
        self.assertEqual(reasons, [])

    def test_expiry_during_hold_charges_exit_standard_fee(self):
        r = fees(valid_until_ns=BASE + 12 * 1_000_000_000)
        policy = FeePolicy(r, symbol=SYMBOL, channel="api")
        self.assertEqual(policy.rate(BASE + 11 * 1_000_000_000, 100)[0], 0)
        self.assertEqual(policy.rate(BASE + 13 * 1_000_000_000, 100)[0], 8)

    def test_quota_counts_both_legs_and_falls_back_on_crossing(self):
        policy = FeePolicy(fees(quota_kind="limited", remaining_quota_usdt=150), symbol=SYMBOL, channel="api")
        self.assertEqual(policy.rate(BASE + 1, 100)[0], 0)
        self.assertEqual(policy.rate(BASE + 2, 100), (8, ["quota_exhausted"]))
        self.assertEqual(policy.rate(BASE + 3, 40), (8, ["quota_exhausted"]))

    def test_future_record_missing_hash_wrong_symbol_and_channel_do_not_apply(self):
        for record in (fees(observed_at_ns=BASE + 100), fees(terms_snapshot_sha256=None), fees(symbol="OTHER_USDT"),
                       fees(execution_channel="manual"), fees(valid_until_ns=None)):
            rate, reasons = FeePolicy(record, symbol=SYMBOL, channel="api").rate(BASE + 1, 100)
            self.assertEqual(rate, 8)
            self.assertTrue(reasons)

    def test_nan_fee_and_normal_zero_are_rejected(self):
        for record in (fees(taker_bps=float("nan")), fees(normal_taker_bps=0), fees(taker_bps=-1)):
            with self.assertRaises(ScalpingError):
                FeePolicy(record, symbol=SYMBOL, channel="api")


if __name__ == "__main__":
    unittest.main()

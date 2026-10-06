from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.contracts_v2 import build_canonical_source_set, build_source_record
from orderflow_edge_lab.execution import MarketSnapshot, PaperEngine, RejectedIntent, RiskPolicy, TradeIntent
from orderflow_edge_lab.paper_execution_v2 import (
    METADATA_SCHEMA,
    TERMS_POLICY_SCHEMA,
    ApprovalBoundPaperEngineV2,
    PaperExecutionV2Error,
    audit_paper_execution_v2,
    build_reconciliation_anchor_v2,
    verify_reconciliation_anchor_v2,
    write_reconciliation_anchor_v2,
)
from orderflow_edge_lab.paper_replay_v2 import (
    PaperReplayV2Error,
    build_replay_bundle_v2,
    validate_approval_terms_v2,
    validate_paper_market_coverage_v2,
    validate_replay_bundle_v2,
    verify_replay_bundle_file_v2,
    write_replay_bundle_v2,
)

UTC = timezone.utc
POLICY_HASH = "a" * 64


def source_set():
    return build_canonical_source_set([
        build_source_record("normalized_prices", {"schema": "orderflow_edge_lab.file_identity.v2", "size_bytes": 7, "sha256": "1" * 64}),
        build_source_record("normalized_funding", {"schema": "orderflow_edge_lab.file_identity.v2", "size_bytes": 7, "sha256": "2" * 64}),
        build_source_record("replay_config", {"schema": "orderflow_edge_lab.file_identity.v2", "size_bytes": 7, "sha256": "3" * 64}),
    ])


def replay_inputs(*, funding_rate=0.0, collection_failures=None):
    t0 = "2026-10-01T08:00:00Z"
    t1 = "2026-10-02T08:00:00Z"
    t2 = "2026-10-03T08:00:00Z"
    return {
        "config": {
            "initial_equity": 10000.0,
            "start_utc": "2026-10-01T00:00:00Z",
            "as_of_utc": t2,
            "slippage": 0.0,
            "min_fee": 0.0,
            "collection_failures": collection_failures or [],
        },
        "targets": [
            {"timestamp": t0, "symbol": "A", "weight": 0.5},
            {"timestamp": t1, "symbol": "A", "weight": 0.5},
            {"timestamp": t2, "symbol": "A", "weight": 0.5},
        ],
        "marks": [
            {"timestamp": t0, "symbol": "A", "price": 100.0},
            {"timestamp": t1, "symbol": "A", "price": 110.0},
            {"timestamp": t2, "symbol": "A", "price": 120.0},
        ],
        "funding": [
            {"timestamp": "2026-10-01T16:00:00Z", "symbol": "A", "rate": funding_rate},
            {"timestamp": "2026-10-02T16:00:00Z", "symbol": "A", "rate": funding_rate},
        ],
        "funding_expectations": [
            {"timestamp": "2026-10-01T16:00:00Z", "symbol": "A"},
            {"timestamp": "2026-10-02T16:00:00Z", "symbol": "A"},
        ],
        "specs": {"A": {"contract_size": 1.0, "min_contracts": 1, "taker_fee_rate": 0.0}},
        "coverage_policy_sha256": POLICY_HASH,
    }


def metadata(symbols=("MNQ",)):
    all_metadata = {
        "MNQ": {
            "schema": METADATA_SCHEMA, "symbol": "MNQ", "tick_size": "0.25", "tick_value": "0.50",
            "max_contracts": 20, "contract_increment": 2, "min_contracts": 2,
        },
        "NQ": {
            "schema": METADATA_SCHEMA, "symbol": "NQ", "tick_size": "0.25", "tick_value": "5.00",
            "max_contracts": 4, "contract_increment": 1, "min_contracts": 1,
        },
    }
    return {symbol: all_metadata[symbol] for symbol in symbols}


def terms_policy():
    return {
        "schema": TERMS_POLICY_SCHEMA,
        "max_bid_move_ticks": 0,
        "max_ask_move_ticks": 0,
        "max_fill_move_ticks": 0,
    }


class PaperReplayV2Tests(unittest.TestCase):
    def test_missing_funding_is_data_gap_and_never_publishes_summary(self):
        inputs = replay_inputs()
        inputs["funding"] = []
        coverage = validate_paper_market_coverage_v2(inputs)
        bundle = build_replay_bundle_v2(inputs, source_set())
        self.assertEqual(coverage["status"], "DATA_GAP")
        self.assertEqual(bundle["status"], "DATA_GAP")
        self.assertIsNone(bundle["summary"])
        self.assertEqual(bundle["manifest"]["outcome"], "INCOMPLETE")
        self.assertTrue(any("funding:A" in item for item in coverage["coverage"]["missing_observation_ids"]))

    def test_observed_zero_is_complete_not_missing_and_lifecycle_reconciles(self):
        bundle = build_replay_bundle_v2(replay_inputs(funding_rate=0.0), source_set())
        self.assertEqual(bundle["status"], "COMPLETE")
        self.assertEqual(bundle["coverage"]["status"], "COMPLETE")
        funding = [row for row in bundle["coverage"]["observations"] if row["observation_id"].startswith("funding:")]
        self.assertTrue(funding)
        self.assertTrue(all(row["observation"]["availability"] == "OBSERVED" for row in funding))
        self.assertTrue(all(row["observation"]["value"] == 0.0 for row in funding))
        self.assertGreater(len([row for row in bundle["lifecycle"] if row["event_type"] == "rebalance_fill"]), 1)
        self.assertAlmostEqual(bundle["summary"]["ending_equity"], bundle["summary"]["curve"][-1]["equity"])
        self.assertEqual(validate_replay_bundle_v2(bundle)["bundle_sha256"], bundle["bundle_sha256"])

    def test_duplicate_nonfinite_and_missing_mark_fail_closed_deterministically(self):
        duplicate = replay_inputs()
        duplicate["funding"].append(deepcopy(duplicate["funding"][0]))
        nonfinite = replay_inputs()
        nonfinite["marks"][1]["price"] = float("nan")
        missing = replay_inputs()
        missing["marks"] = missing["marks"][:1]
        for inputs in (duplicate, nonfinite, missing):
            with self.subTest(inputs=inputs):
                bundle = build_replay_bundle_v2(inputs, source_set())
                self.assertEqual(bundle["status"], "DATA_GAP")
                self.assertIsNone(bundle["summary"])

    def test_bundles_are_byte_reproducible_and_mutations_fail_verification(self):
        left = build_replay_bundle_v2(replay_inputs(), source_set())
        right = build_replay_bundle_v2(replay_inputs(), source_set())
        self.assertEqual(json.dumps(left, sort_keys=True, separators=(",", ":")), json.dumps(right, sort_keys=True, separators=(",", ":")))
        for field, mutation in (
            ("input_snapshot", lambda value: value["marks"][0].__setitem__("price", 101.0)),
            ("input_snapshot", lambda value: value["config"].__setitem__("min_fee", 0.01)),
            ("lifecycle", lambda value: value[0].__setitem__("fees", 1.0) if "fees" in value[0] else value[0].__setitem__("timestamp", "2020-01-01T00:00:00Z")),
        ):
            corrupted = deepcopy(left)
            mutation(corrupted[field])
            with self.subTest(field=field), self.assertRaises(PaperReplayV2Error):
                validate_replay_bundle_v2(corrupted)

    def test_exclusive_saved_bundle_and_collection_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bundle.json"
            complete = build_replay_bundle_v2(replay_inputs(), source_set())
            write_replay_bundle_v2(path, complete)
            self.assertEqual(verify_replay_bundle_file_v2(path)["status"], "VERIFIED_LOCAL_REPLAY")
            with self.assertRaises(FileExistsError):
                write_replay_bundle_v2(path, complete)
            path.write_bytes(path.read_bytes() + b"X")
            self.assertEqual(verify_replay_bundle_file_v2(path)["status"], "INVALID")
        incomplete = build_replay_bundle_v2(replay_inputs(collection_failures=["funding_source_failed:A"]), source_set())
        self.assertEqual(incomplete["status"], "INCOMPLETE_INPUT")
        self.assertIsNone(incomplete["summary"])


class PaperExecutionV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = root / "state.json"
        self.journal = root / "journal.jsonl"
        self.now = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
        self.market = MarketSnapshot("MNQ", 20000.00, 20000.25, self.now)

    def engine(self, *, symbols=("MNQ",), policy=None, equity=10000.0, migrate=False):
        return ApprovalBoundPaperEngineV2(
            self.state, self.journal, instrument_metadata=metadata(symbols), terms_policy=terms_policy(),
            policy=policy, starting_equity=equity, migrate_reconciled_flat=migrate,
        )

    def intent(self, symbol="MNQ", side="LONG", strategy="v2"):
        if side == "LONG":
            return TradeIntent(strategy, symbol, side, 20000.25, 19995.25, 20010.25, self.now)
        return TradeIntent(strategy, symbol, side, 20000.00, 20005.00, 19990.00, self.now)

    def open_position(self, engine, *, symbol="MNQ", strategy="v2"):
        market = self.market if symbol == "MNQ" else MarketSnapshot("NQ", 20000.00, 20000.25, self.now)
        ident = engine.submit(self.intent(symbol, strategy=strategy), market, now=self.now, evidence={"fixture": strategy})
        position = engine.approve(ident, market, approval_token=engine.approval_token_for(ident), now=self.now)
        self.assertNotIn("status", position)
        return ident

    def test_off_tick_rejects_before_state_or_journal_mutation_and_valid_lots_are_even(self):
        with self.engine() as engine:
            revision = engine.state["revision"]
            head = engine.state["journal_head"]
            off_tick = TradeIntent("offtick", "MNQ", "LONG", 20000.26, 19995.25, 20010.25, self.now)
            with self.assertRaisesRegex(RejectedIntent, "off_tick"):
                engine.submit(off_tick, self.market, now=self.now, evidence={"fixture": 1})
            self.assertEqual(engine.state["revision"], revision)
            self.assertEqual(engine.state["journal_head"], head)
            ident = engine.submit(self.intent(), self.market, now=self.now, evidence={"fixture": 2})
            position = engine.approve(ident, self.market, approval_token=engine.approval_token_for(ident), now=self.now)
            self.assertEqual(position["contracts"] % 2, 0)
            self.assertEqual(position["entry_fill"], 20000.5)
            exit_market = MarketSnapshot("MNQ", 20001.00, 20001.25, self.now)
            closed = engine.close_position(ident, exit_market, reason="fixture", now=self.now)
            expected = (20000.75 - 20000.5) / 0.25 * 0.5 * position["contracts"]
            self.assertAlmostEqual(closed["gross_pnl"], expected)

    def test_terms_move_refreshes_token_even_when_count_stays_the_same(self):
        with self.engine() as engine:
            ident = engine.submit(self.intent(), self.market, now=self.now, evidence={"fixture": "terms"})
            original = engine.approval_token_for(ident)
            terms = engine.state["pending"][ident]["approval_binding"]["terms"]
            self.assertEqual(validate_approval_terms_v2(terms), terms)
            invalid_terms = deepcopy(terms)
            invalid_terms["contracts"] = 0
            with self.assertRaises(PaperExecutionV2Error):
                validate_approval_terms_v2(invalid_terms)
            moved = MarketSnapshot("MNQ", 20000.25, 20000.50, self.now)
            refreshed = engine.approve(ident, moved, approval_token=original, now=self.now)
            self.assertEqual(refreshed["status"], "APPROVAL_MARKET_TERMS_CHANGED")
            self.assertNotEqual(refreshed["refreshed_approval_token"], original)
            self.assertFalse(engine.state["positions"])
            with self.assertRaisesRegex(RejectedIntent, "approval_token_mismatch"):
                engine.approve(ident, moved, approval_token=original, now=self.now)
            opened = engine.approve(ident, moved, approval_token=refreshed["refreshed_approval_token"], now=self.now)
            self.assertEqual(opened["symbol"], "MNQ")
        events = [json.loads(line)["event_type"] for line in self.journal.read_text().splitlines()]
        self.assertIn("approval_market_terms_changed", events)

    def test_existing_manual_state_requires_explicit_reconciled_flat_migration_without_rewrite(self):
        with PaperEngine(self.state, self.journal):
            pass
        before_state = self.state.read_bytes()
        before_journal = self.journal.read_bytes()
        with self.assertRaises(PaperExecutionV2Error):
            self.engine()
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.journal.read_bytes(), before_journal)
        # Existing default state binds both NQ and MNQ; migration must declare
        # complete successor metadata matching that frozen legacy registry.
        with self.engine(symbols=("MNQ", "NQ"), migrate=True) as migrated:
            self.assertEqual(migrated.state["positions"], {})
        self.assertTrue(Path(str(self.state) + ".paper_execution_v2.json").exists())

    def test_flatten_preflight_keeps_all_positions_and_success_records_completion(self):
        policy = RiskPolicy(max_open_positions=2)
        with self.engine(symbols=("MNQ", "NQ"), policy=policy, equity=100000.0) as engine:
            mnq = self.open_position(engine, symbol="MNQ", strategy="mnq")
            nq = self.open_position(engine, symbol="NQ", strategy="nq")
            result = engine.engage_kill_switch({"MNQ": self.market}, flatten=True, now=self.now)
            self.assertEqual(result["status"], "PREFLIGHT_FAILED")
            self.assertEqual(set(engine.state["positions"]), {mnq, nq})
            self.assertTrue(engine.state["kill_switch"])
        first_events = [json.loads(line)["event_type"] for line in self.journal.read_text().splitlines()]
        self.assertIn("kill_switch_flatten_preflight_failed", first_events)

        # A separate fresh successor verifies the all-good path without releasing/reusing the failed run.
        state2 = self.state.with_name("state2.json")
        journal2 = self.journal.with_name("journal2.jsonl")
        with ApprovalBoundPaperEngineV2(state2, journal2, instrument_metadata=metadata(("MNQ", "NQ")), terms_policy=terms_policy(),
                                        policy=policy, starting_equity=100000.0) as engine:
            self.state, self.journal = state2, journal2
            mnq = self.open_position(engine, symbol="MNQ", strategy="mnq2")
            nq = self.open_position(engine, symbol="NQ", strategy="nq2")
            good = engine.engage_kill_switch({"MNQ": self.market, "NQ": MarketSnapshot("NQ", 20000, 20000.25, self.now)},
                                              flatten=True, now=self.now)
            self.assertEqual(good["status"], "COMPLETED")
            self.assertEqual(good["closed_position_ids"], sorted([mnq, nq]))
            self.assertFalse(engine.state["positions"])
        events = [json.loads(line)["event_type"] for line in journal2.read_text().splitlines()]
        self.assertEqual(events.count("paper_position_closed"), 2)
        self.assertIn("kill_switch_flatten_completed", events)

    def test_second_flatten_persistence_failure_is_audited_incomplete_with_exact_remaining_ids(self):
        policy = RiskPolicy(max_open_positions=2)
        with self.engine(symbols=("MNQ", "NQ"), policy=policy, equity=100000.0) as engine:
            mnq = self.open_position(engine, symbol="MNQ", strategy="mnq")
            nq = self.open_position(engine, symbol="NQ", strategy="nq")
            original = engine._write_state
            calls = {"count": 0}

            def fail_second_close(state):
                calls["count"] += 1
                if calls["count"] == 3:  # requested, first close, second close
                    raise OSError("injected second close checkpoint failure")
                return original(state)

            with patch.object(engine, "_write_state", side_effect=fail_second_close):
                with self.assertRaises(OSError):
                    engine.engage_kill_switch({"MNQ": self.market, "NQ": MarketSnapshot("NQ", 20000, 20000.25, self.now)},
                                              flatten=True, now=self.now)
        audit = audit_paper_execution_v2(self.state, self.journal)
        self.assertIn("flatten_incomplete", audit["blockers"])
        self.assertIn("recovery_required", audit["blockers"])
        self.assertEqual(audit["flatten"]["expected_position_ids"], sorted([mnq, nq]))
        self.assertEqual(audit["flatten"]["remaining_position_ids"], [])

    def test_kill_without_flatten_preserves_positions(self):
        with self.engine() as engine:
            ident = self.open_position(engine)
            engine.engage_kill_switch(now=self.now)
            self.assertIn(ident, engine.state["positions"])
            self.assertTrue(engine.state["kill_switch"])

    def test_later_independent_anchor_detects_rollback_and_mutation_never_writes_history(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        with self.engine() as engine:
            old_state = self.state.read_bytes()
            old_journal = self.journal.read_bytes()
            engine.engage_kill_switch(now=self.now)
        anchor = build_reconciliation_anchor_v2(self.state, self.journal, runtime_identity={"fixture": "anchor"},
                                                generated_at="2026-10-05T20:00:00Z")
        anchor_path = external / "anchor.json"
        write_reconciliation_anchor_v2(anchor_path, anchor)
        self.state.write_bytes(old_state)
        self.journal.write_bytes(old_journal)
        result = verify_reconciliation_anchor_v2(self.state, self.journal, trusted_anchor_path=anchor_path)
        self.assertEqual(result["status"], "ROLLBACK_DETECTED")
        before = anchor_path.read_bytes()
        anchor_path.write_text(anchor_path.read_text().replace("paper_reconciliation", "paper_reconciliati0n", 1))
        mutated = verify_reconciliation_anchor_v2(self.state, self.journal, trusted_anchor_path=anchor_path)
        self.assertEqual(mutated["status"], "ANCHOR_INVALID_OR_LOCAL_INVALID")
        self.assertNotEqual(anchor_path.read_bytes(), before)  # verifier did not repair/rewrite it

    def test_anchor_strict_missing_blocks_and_journal_ahead_is_recovery_not_rollback(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        with self.engine() as engine:
            anchor = build_reconciliation_anchor_v2(self.state, self.journal, runtime_identity={"fixture": "recovery"},
                                                    generated_at="2026-10-05T20:00:00Z")
            anchor_path = external / "anchor.json"
            write_reconciliation_anchor_v2(anchor_path, anchor)
            with patch.object(engine, "_write_state", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    engine.submit(self.intent(), self.market, now=self.now, evidence={"fixture": "journal-ahead"})
        recovery = verify_reconciliation_anchor_v2(self.state, self.journal, trusted_anchor_path=anchor_path)
        self.assertEqual(recovery["status"], "RECOVERY_REQUIRED")
        strict = verify_reconciliation_anchor_v2(self.state, self.journal, strict_unattended=True)
        self.assertEqual(strict["status"], "TRUSTED_ANCHOR_UNKNOWN")
        self.assertFalse(strict["ready_for_unattended"])


if __name__ == "__main__":
    unittest.main()

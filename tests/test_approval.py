from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.approval import ApprovalBoundPaperEngine
from orderflow_edge_lab.execution import MarketSnapshot, RejectedIntent, RiskPolicy, TradeIntent
from orderflow_edge_lab.reliability import audit_journal_semantics


UTC = timezone.utc


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "state.json"
        self.journal = root / "journal.jsonl"
        self.now = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
        self.intent = TradeIntent(
            strategy_id="approval-binding",
            symbol="MNQ",
            side="LONG",
            entry_reference=20000.25,
            stop=19995.25,
            target=20010.25,
            signal_time=self.now,
        )
        self.submission_market = MarketSnapshot("MNQ", 20000.00, 20000.25, self.now)

    def _submit(self, engine, *, evidence=None):
        ident = engine.submit(self.intent, self.submission_market, now=self.now, evidence=evidence)
        return ident, engine.approval_token_for(ident)

    def test_unchanged_size_can_be_approved_with_exact_token(self):
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident, token = self._submit(engine, evidence={"dataset_sha256": "a" * 64})
            proposed = engine.state["pending"][ident]["contracts"]
            position = engine.approve(ident, self.submission_market, approval_token=token, now=self.now)
            self.assertEqual(position["contracts"], proposed)

    def test_missing_or_wrong_token_fails_closed_and_leaves_intent_pending(self):
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident, token = self._submit(engine)
            with self.assertRaisesRegex(RejectedIntent, "approval_token_mismatch"):
                engine.approve(ident, self.submission_market, now=self.now)
            self.assertIn(ident, engine.state["pending"])
            self.assertFalse(engine.state["positions"])
            with self.assertRaisesRegex(RejectedIntent, "approval_token_mismatch"):
                engine.approve(ident, self.submission_market, approval_token="0" * len(token), now=self.now)
            self.assertIn(ident, engine.state["pending"])
            self.assertFalse(engine.state["positions"])

        events = [json.loads(line)["event_type"] for line in self.journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events.count("approval_token_rejected"), 2)

    def test_binding_covers_evidence_market_and_engine_configuration(self):
        evidence = {"export_sha256": "b" * 64, "quality": {"passed": True}}
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident, token = self._submit(engine, evidence=evidence)
            binding = engine.state["pending"][ident]["approval_binding"]
            self.assertEqual(binding["submitted_market"]["bid"], self.submission_market.bid)
            self.assertEqual(binding["submitted_market"]["ask"], self.submission_market.ask)
            self.assertEqual(len(binding["evidence_sha256"]), 64)
            self.assertEqual(len(binding["engine_config_sha256"]), 64)
            self.assertEqual(token, engine.state["pending"][ident]["approval_token"])

    def test_token_survives_restart_with_journal_reconciliation(self):
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident, token = self._submit(engine, evidence={"record": 1})
        with ApprovalBoundPaperEngine(self.state, self.journal) as restarted:
            self.assertEqual(restarted.approval_token_for(ident), token)
            restarted.approve(ident, self.submission_market, approval_token=token, now=self.now)
            self.assertIn(ident, restarted.state["positions"])

    def test_more_favorable_market_cannot_silently_increase_approved_size(self):
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident, token = self._submit(engine)
            proposed = engine.state["pending"][ident]["contracts"]
            moved = MarketSnapshot("MNQ", 19999.00, 19999.25, self.now)
            with self.assertRaisesRegex(RejectedIntent, "approval_terms_changed"):
                engine.approve(ident, moved, approval_token=token, now=self.now)
            self.assertEqual(engine.state["pending"][ident]["contracts"], proposed)
            self.assertFalse(engine.state["positions"])

        last = json.loads(self.journal.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["event_type"], "approval_terms_changed")
        self.assertEqual(last["payload"]["intent_id"], ident)
        self.assertEqual(last["payload"]["submitted_contracts"], proposed)
        self.assertGreater(last["payload"]["currently_allowed"], proposed)
        self.assertEqual(last["payload"]["approval_token"], token)
        self.assertEqual(last["payload"]["market"]["bid"], moved.bid)
        self.assertEqual(last["payload"]["market"]["ask"], moved.ask)
        self.assertEqual(last["payload"]["market"]["timestamp"], moved.timestamp.isoformat())
        self.assertGreaterEqual(audit_journal_semantics(self.journal)["checkpoints"], 4)

    def test_less_favorable_market_cannot_silently_downsize_approved_order(self):
        policy = RiskPolicy(min_reward_risk=1.0)
        with ApprovalBoundPaperEngine(self.state, self.journal, policy=policy) as engine:
            ident, token = self._submit(engine)
            proposed = engine.state["pending"][ident]["contracts"]
            moved = MarketSnapshot("MNQ", 20001.00, 20001.25, self.now)
            with self.assertRaisesRegex(RejectedIntent, "approval_terms_changed"):
                engine.approve(ident, moved, approval_token=token, now=self.now)
            self.assertEqual(engine.state["pending"][ident]["contracts"], proposed)
            self.assertFalse(engine.state["positions"])

        last = json.loads(self.journal.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["event_type"], "approval_terms_changed")
        self.assertEqual(last["payload"]["intent_id"], ident)
        self.assertEqual(last["payload"]["submitted_contracts"], proposed)
        self.assertLess(last["payload"]["currently_allowed"], proposed)
        self.assertEqual(last["payload"]["market"]["symbol"], "MNQ")
        self.assertGreaterEqual(audit_journal_semantics(self.journal)["checkpoints"], 4)


if __name__ == "__main__":
    unittest.main()

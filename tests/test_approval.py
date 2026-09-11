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

    def test_unchanged_size_can_be_approved(self):
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident = engine.submit(self.intent, self.submission_market, now=self.now)
            proposed = engine.state["pending"][ident]["contracts"]
            position = engine.approve(ident, self.submission_market, now=self.now)
            self.assertEqual(position["contracts"], proposed)

    def test_more_favorable_market_cannot_silently_increase_approved_size(self):
        with ApprovalBoundPaperEngine(self.state, self.journal) as engine:
            ident = engine.submit(self.intent, self.submission_market, now=self.now)
            proposed = engine.state["pending"][ident]["contracts"]
            moved = MarketSnapshot("MNQ", 19999.00, 19999.25, self.now)
            with self.assertRaisesRegex(RejectedIntent, "approval_terms_changed"):
                engine.approve(ident, moved, now=self.now)
            self.assertEqual(engine.state["pending"][ident]["contracts"], proposed)
            self.assertFalse(engine.state["positions"])

        last = json.loads(self.journal.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["event_type"], "approval_terms_changed")
        self.assertEqual(last["payload"]["intent_id"], ident)
        self.assertEqual(last["payload"]["submitted_contracts"], proposed)
        self.assertGreater(last["payload"]["currently_allowed"], proposed)
        self.assertEqual(last["payload"]["market"]["bid"], moved.bid)
        self.assertEqual(last["payload"]["market"]["ask"], moved.ask)
        self.assertEqual(last["payload"]["market"]["timestamp"], moved.timestamp.isoformat())
        self.assertGreaterEqual(audit_journal_semantics(self.journal)["checkpoints"], 3)

    def test_less_favorable_market_cannot_silently_downsize_approved_order(self):
        policy = RiskPolicy(min_reward_risk=1.0)
        with ApprovalBoundPaperEngine(self.state, self.journal, policy=policy) as engine:
            ident = engine.submit(self.intent, self.submission_market, now=self.now)
            proposed = engine.state["pending"][ident]["contracts"]
            moved = MarketSnapshot("MNQ", 20001.00, 20001.25, self.now)
            with self.assertRaisesRegex(RejectedIntent, "approval_terms_changed"):
                engine.approve(ident, moved, now=self.now)
            self.assertEqual(engine.state["pending"][ident]["contracts"], proposed)
            self.assertFalse(engine.state["positions"])

        last = json.loads(self.journal.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["event_type"], "approval_terms_changed")
        self.assertEqual(last["payload"]["intent_id"], ident)
        self.assertEqual(last["payload"]["submitted_contracts"], proposed)
        self.assertLess(last["payload"]["currently_allowed"], proposed)
        self.assertEqual(last["payload"]["market"]["symbol"], "MNQ")
        self.assertGreaterEqual(audit_journal_semantics(self.journal)["checkpoints"], 3)


if __name__ == "__main__":
    unittest.main()

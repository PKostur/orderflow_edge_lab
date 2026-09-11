from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.approval import ApprovalBoundPaperEngine
from orderflow_edge_lab.execution import MarketSnapshot, RejectedIntent, RiskPolicy, TradeIntent


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


if __name__ == "__main__":
    unittest.main()

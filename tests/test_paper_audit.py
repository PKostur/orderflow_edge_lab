from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.approval import ApprovalBoundPaperEngine
from orderflow_edge_lab.cli.paper_audit import audit_paper_runtime
from orderflow_edge_lab.execution import MarketSnapshot, RiskPolicy, TradeIntent


UTC = timezone.utc


class PaperAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.journal = Path(self.tmp.name) / "journal.jsonl"
        self.now = datetime(2026, 9, 11, 20, 0, tzinfo=UTC)
        self.market = MarketSnapshot("MNQ", 20000.00, 20000.25, self.now)
        self.intent = TradeIntent(
            strategy_id="audit-test",
            symbol="MNQ",
            side="LONG",
            entry_reference=20000.25,
            stop=19995.25,
            target=20010.25,
            signal_time=self.now,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_pending_proposal_is_operationally_ready(self):
        policy = RiskPolicy(approval_ttl_seconds=120)
        with ApprovalBoundPaperEngine(self.state, self.journal, policy=policy) as engine:
            engine.submit(self.intent, self.market, now=self.now, evidence={"source": "test"})
        report = audit_paper_runtime(self.state, self.journal, now=self.now + timedelta(seconds=30))
        self.assertTrue(report["operational_ready"])
        self.assertEqual(report["pending_count"], 1)
        self.assertEqual(report["expired_pending_ids"], [])
        self.assertFalse(report["ready_for_live"])
        self.assertFalse(report["live_order_transmission_supported"])

    def test_expired_pending_proposal_blocks_operational_readiness(self):
        policy = RiskPolicy(approval_ttl_seconds=10)
        with ApprovalBoundPaperEngine(self.state, self.journal, policy=policy) as engine:
            ident = engine.submit(self.intent, self.market, now=self.now, evidence={"source": "test"})
        report = audit_paper_runtime(self.state, self.journal, now=self.now + timedelta(seconds=11))
        self.assertFalse(report["operational_ready"])
        self.assertIn("expired_pending_intents", report["blockers"])
        self.assertEqual(report["expired_pending_ids"], [ident])

    def test_missing_state_fails_closed(self):
        report = audit_paper_runtime(self.state, self.journal, now=self.now)
        self.assertFalse(report["operational_ready"])
        self.assertIn("state_file_missing", report["blockers"])


if __name__ == "__main__":
    unittest.main()

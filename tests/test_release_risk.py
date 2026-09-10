from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.execution import (
    PaperEngine, RiskPolicy, MarketSnapshot, TradeIntent, StateCorruptionError, RejectedIntent,
)


class ReleaseRiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state, self.journal = Path(self.tmp.name) / "state.json", Path(self.tmp.name) / "journal.jsonl"
        self.now = datetime.now(timezone.utc)
        self.market = MarketSnapshot("MNQ", 20000, 20000.25, self.now)

    def intent(self, name="test", now=None):
        return TradeIntent(name, "MNQ", "LONG", 20000.25, 19995.25, 20010.25, now or self.now)

    def test_restarting_with_changed_cost_or_risk_policy_fails_closed(self):
        with PaperEngine(self.state, self.journal):
            pass
        before = self.state.read_bytes(), self.journal.read_bytes()
        for policy in (RiskPolicy(risk_fraction=0.01), RiskPolicy(commission_per_contract_per_side=1)):
            with self.assertRaisesRegex(StateCorruptionError, "configuration changed"):
                PaperEngine(self.state, self.journal, policy=policy)
            self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_in_process_configuration_change_is_rejected(self):
        with PaperEngine(self.state, self.journal) as engine:
            engine.policy = RiskPolicy(risk_fraction=0.01)
            with self.assertRaisesRegex(StateCorruptionError, "configuration changed"):
                engine.submit(self.intent(), self.market, now=self.now)

    def test_time_cannot_move_backwards_across_restart(self):
        with PaperEngine(self.state, self.journal) as engine:
            engine.submit(self.intent(), self.market, now=self.now)
        before = self.state.read_bytes(), self.journal.read_bytes()
        with PaperEngine(self.state, self.journal) as engine:
            past = self.now - timedelta(days=1)
            with self.assertRaisesRegex(RejectedIntent, "time_regression"):
                engine.submit(self.intent("past", past), MarketSnapshot("MNQ", 20000, 20000.25, past), now=past)
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_open_positions_reserve_remaining_daily_loss_budget(self):
        policy = RiskPolicy(risk_fraction=0.02, max_open_positions=2)
        with PaperEngine(self.state, self.journal, policy=policy) as engine:
            first = engine.submit(self.intent(), self.market, now=self.now)
            second = engine.submit(self.intent("second"), self.market, now=self.now)
            engine.approve(first, self.market, now=self.now)
            with self.assertRaisesRegex(RejectedIntent, "risk_budget_too_small"):
                engine.approve(second, self.market, now=self.now)
            self.assertEqual(len(engine.state["positions"]), 1)

    def test_expiry_is_audited_once_and_kill_does_not_revive_queue(self):
        with PaperEngine(self.state, self.journal, policy=RiskPolicy(approval_ttl_seconds=1)) as engine:
            first = engine.submit(self.intent(), self.market, now=self.now)
            later = self.now + timedelta(seconds=1)
            self.assertEqual(engine.expire_pending(now=later), [first])
            revision = engine.state["revision"]
            self.assertEqual(engine.expire_pending(now=later), [])
            self.assertEqual(engine.state["revision"], revision)
            market = MarketSnapshot("MNQ", 20000, 20000.25, later)
            second = engine.submit(self.intent("second", later), market, now=later)
            engine.engage_kill_switch(now=later)
            engine.release_kill_switch(now=later)
            with self.assertRaisesRegex(RejectedIntent, "unknown_pending"):
                engine.approve(second, market, now=later)

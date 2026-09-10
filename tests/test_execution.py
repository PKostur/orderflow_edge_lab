from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.execution import (
    EngineLockError, HashChainJournal, MarketSnapshot, PaperEngine, RejectedIntent,
    RiskPolicy, StateCorruptionError, TradeIntent,
)


UTC = timezone.utc


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.journal = Path(self.tmp.name) / "journal.jsonl"
        self.now = datetime(2026, 9, 10, 20, 0, tzinfo=UTC)
        self.market = MarketSnapshot("MNQ", 20000.00, 20000.25, self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def intent(self, **changes):
        values = dict(
            strategy_id="test",
            symbol="MNQ",
            side="LONG",
            entry_reference=20000.25,
            stop=19995.25,
            target=20010.25,
            signal_time=self.now,
        )
        values.update(changes)
        return TradeIntent(**values)

    def test_intent_id_deterministic(self):
        self.assertEqual(self.intent().intent_id, self.intent().intent_id)

    def test_duplicate_rejected(self):
        with PaperEngine(self.state, self.journal) as engine:
            engine.submit(self.intent(), self.market, now=self.now)
            with self.assertRaisesRegex(RejectedIntent, "duplicate_intent"):
                engine.submit(self.intent(), self.market, now=self.now)

    def test_stale_signal_and_market_rejected(self):
        with PaperEngine(self.state, self.journal) as engine:
            stale_intent = self.intent(signal_time=self.now - timedelta(minutes=1))
            with self.assertRaisesRegex(RejectedIntent, "stale_signal"):
                engine.submit(stale_intent, self.market, now=self.now)
            stale_market = MarketSnapshot("MNQ", 20000, 20000.25, self.now - timedelta(seconds=10))
            with self.assertRaisesRegex(RejectedIntent, "stale_market"):
                engine.submit(self.intent(strategy_id="fresh"), stale_market, now=self.now)

    def test_spread_and_rr_rejected(self):
        with PaperEngine(self.state, self.journal) as engine:
            wide = MarketSnapshot("MNQ", 20000, 20002, self.now)
            with self.assertRaisesRegex(RejectedIntent, "spread"):
                engine.submit(self.intent(strategy_id="wide"), wide, now=self.now)
            bad_rr = self.intent(strategy_id="rr", target=20005.25)
            with self.assertRaisesRegex(RejectedIntent, "reward_risk"):
                engine.submit(bad_rr, self.market, now=self.now)

    def test_approval_expiry(self):
        policy = RiskPolicy(approval_ttl_seconds=1)
        with PaperEngine(self.state, self.journal, policy=policy) as engine:
            intent_id = engine.submit(self.intent(), self.market, now=self.now)
            with self.assertRaisesRegex(RejectedIntent, "approval_expired"):
                engine.approve(
                    intent_id,
                    MarketSnapshot("MNQ", 20000, 20000.25, self.now + timedelta(seconds=2)),
                    now=self.now + timedelta(seconds=2),
                )

    def test_pnl_uses_tick_value_and_costs(self):
        policy = RiskPolicy(slippage_ticks=0, commission_per_contract_per_side=1.0)
        with PaperEngine(self.state, self.journal, starting_equity=10_000, policy=policy) as engine:
            intent_id = engine.submit(self.intent(), self.market, now=self.now)
            pos = engine.approve(intent_id, self.market, now=self.now)
            exit_market = MarketSnapshot("MNQ", 20001.00, 20001.25, self.now)
            result = engine.close_position(intent_id, exit_market, reason="test", now=self.now)
            contracts = pos["contracts"]
            expected_gross = (20001.00 - 20000.25) / 0.25 * 0.50 * contracts
            expected_net = expected_gross - 2 * contracts
            self.assertAlmostEqual(result["gross_pnl"], expected_gross)
            self.assertAlmostEqual(result["net_pnl"], expected_net)

    def test_kill_switch_blocks_new_entry(self):
        with PaperEngine(self.state, self.journal) as engine:
            engine.engage_kill_switch(now=self.now)
            with self.assertRaisesRegex(RejectedIntent, "kill_switch"):
                engine.submit(self.intent(), self.market, now=self.now)

    def test_single_owner_lock(self):
        engine = PaperEngine(self.state, self.journal)
        try:
            with self.assertRaises(EngineLockError):
                PaperEngine(self.state, self.journal)
        finally:
            engine.close()

    def test_corrupt_state_fails_closed(self):
        self.state.write_text("{not json", encoding="utf-8")
        with self.assertRaises(StateCorruptionError):
            PaperEngine(self.state, self.journal)
        self.assertEqual(self.state.read_text(encoding="utf-8"), "{not json")

    def test_journal_tamper_detected(self):
        with PaperEngine(self.state, self.journal) as engine:
            engine.submit(self.intent(), self.market, now=self.now)
        lines = self.journal.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["payload"]["contracts"] = 999
        self.journal.write_text(json.dumps(row) + "\n", encoding="utf-8")
        with self.assertRaises(StateCorruptionError):
            HashChainJournal.verify(self.journal)


if __name__ == "__main__":
    unittest.main()

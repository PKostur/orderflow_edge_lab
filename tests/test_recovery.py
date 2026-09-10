from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.execution import (
    PaperEngine, MarketSnapshot, TradeIntent, StateCorruptionError, EngineLockError,
)
from orderflow_edge_lab.reliability import deployment_readiness


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state.json"
        self.journal = Path(self.tmp.name) / "journal.jsonl"
        self.now = datetime.now(timezone.utc)
        self.market = MarketSnapshot("MNQ", 20000, 20000.25, self.now)
        self.intent = TradeIntent("test", "MNQ", "LONG", 20000.25, 19995.25, 20010.25, self.now)

    def engine(self, **kwargs):
        return PaperEngine(self.state, self.journal, **kwargs)

    def test_journal_ahead_recovers_open_without_duplicate_fill(self):
        with self.engine() as engine:
            ident = engine.submit(self.intent, self.market, now=self.now)
            with patch.object(engine, "_write_state", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    engine.approve(ident, self.market, now=self.now)
            with self.assertRaisesRegex(StateCorruptionError, "persistence failure"):
                engine.engage_kill_switch(now=self.now)
        self.assertFalse(deployment_readiness(self.state, self.journal).ready_for_paper)
        with self.engine() as engine:
            self.assertIn(ident, engine.state["positions"])
            self.assertNotIn(ident, engine.state["pending"])
            self.assertEqual(engine.state["trades_today"], 1)
            revision = engine.state["revision"]
        with self.engine() as engine:
            self.assertEqual(engine.state["revision"], revision)
        self.assertTrue(deployment_readiness(self.state, self.journal).ready_for_paper)

    def test_failed_journal_append_does_not_commit_memory(self):
        with self.engine() as engine:
            before = deepcopy(engine.state)
            with patch.object(engine.journal, "append", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    engine.engage_kill_switch(now=self.now)
        with self.engine() as engine:
            self.assertEqual(engine.state, before)

    def test_partial_tail_and_deleted_tail_fail_closed(self):
        with self.engine() as engine:
            engine.engage_kill_switch(now=self.now)
        journal = self.journal.read_bytes()
        for damaged in (journal + b'{"partial":', journal[:journal.rfind(b"\n", 0, -1) + 1], b""):
            with self.subTest(damaged=len(damaged)):
                self.journal.write_bytes(damaged)
                with self.assertRaises(StateCorruptionError):
                    self.engine()
                self.assertFalse(deployment_readiness(self.state, self.journal).ready_for_paper)

    def test_valid_json_state_tampering_is_detected(self):
        with self.engine() as engine:
            state = deepcopy(engine.state)
        state["equity"] += 1
        self.state.write_text(json.dumps(state))
        with self.assertRaises(StateCorruptionError):
            self.engine()

    def test_missing_state_recovers_from_complete_journal(self):
        with self.engine() as engine:
            original = deepcopy(engine.state)
        self.state.unlink()
        with self.engine() as engine:
            self.assertEqual(engine.state, original)

    def test_shared_journal_has_one_owner(self):
        with self.engine():
            with self.assertRaises(EngineLockError):
                PaperEngine(self.state.with_name("other.json"), self.journal)

    def test_os_releases_lock_after_process_crash(self):
        code = "from orderflow_edge_lab.execution import PaperEngine; import os,sys; e=PaperEngine(sys.argv[1],sys.argv[2]); os._exit(7)"
        child = subprocess.run([sys.executable, "-c", code, str(self.state), str(self.journal)],
                               capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 7, child.stderr.decode())
        with self.engine() as engine:
            self.assertEqual(engine.state["revision"], 1)

    def test_legacy_migration_is_explicit_and_preserves_backup(self):
        with self.engine() as engine:
            legacy = {k: v for k, v in engine.state.items() if k not in {"revision", "journal_head"}}
        legacy["version"] = 1
        self.state.write_text(json.dumps(legacy))
        self.journal.unlink()
        before = self.state.read_bytes()
        with self.assertRaisesRegex(StateCorruptionError, "migration"):
            self.engine()
        with self.engine(migrate_legacy=True) as engine:
            self.assertEqual(engine.state["version"], 2)
        self.assertEqual(self.state.with_suffix(".json.v1.bak").read_bytes(), before)

    def test_short_trade_survives_close_checkpoint_failure(self):
        intent = TradeIntent("short", "MNQ", "SHORT", 20000, 20005, 19990, self.now)
        with self.engine() as engine:
            ident = engine.submit(intent, self.market, now=self.now)
            engine.approve(ident, self.market, now=self.now)
            with patch.object(engine, "_write_state", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    engine.close_position(ident, self.market, reason="test", now=self.now)
        with self.engine() as engine:
            self.assertFalse(engine.state["positions"])
            equity = engine.state["equity"]
        with self.engine() as engine:
            self.assertEqual(engine.state["equity"], equity)

    def test_interrupted_legacy_migration_recovers_without_second_checkpoint(self):
        with self.engine() as engine:
            legacy = {k: v for k, v in engine.state.items() if k not in {"revision", "journal_head"}}
        legacy["version"] = 1
        self.state.write_text(json.dumps(legacy))
        self.journal.unlink()
        with patch.object(PaperEngine, "_write_state", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.engine(migrate_legacy=True)
        with self.engine() as engine:
            self.assertEqual(engine.state["revision"], 1)

    def test_null_state_is_corruption_not_missing_state(self):
        with self.engine():
            pass
        self.state.write_text("null")
        with self.assertRaises(StateCorruptionError):
            self.engine()

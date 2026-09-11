import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.execution import (
    HashChainJournal,
    MarketSnapshot,
    PaperEngine,
    StateCorruptionError,
    TradeIntent,
)
from orderflow_edge_lab.reliability import audit_journal_semantics, deployment_readiness

UTC = timezone.utc


class ReliabilityTests(unittest.TestCase):
    def test_missing_state_fails_paper_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = deployment_readiness(root / "missing.json", root / "journal.jsonl")
            self.assertFalse(report.ready_for_paper)
            self.assertFalse(report.ready_for_live)

    def test_valid_operational_files_allow_paper_but_never_live(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({
                "version": 1,
                "day_start_equity": 10000.0, "realized_pnl_today": 0.0,
                "trades_today": 0, "seen_intents": [],
                "equity": 10000.0,
                "trading_day": "2026-09-10",
                "pending": {},
                "positions": {},
                "kill_switch": False,
            }), encoding="utf-8")
            journal = root / "journal.jsonl"
            HashChainJournal(journal)
            with PaperEngine(state, journal, migrate_legacy=True):
                pass
            report = deployment_readiness(state, journal)
            self.assertTrue(report.ready_for_paper)
            self.assertFalse(report.ready_for_live)
            evidence = next(c for c in report.checks if c.name == "out_of_sample_evidence")
            self.assertFalse(evidence.passed)
            semantics = next(c for c in report.checks if c.name == "journal_semantics")
            self.assertTrue(semantics.passed)
            bindings = next(c for c in report.checks if c.name == "approval_bindings")
            self.assertTrue(bindings.passed)

    def test_unbound_pending_proposal_fails_paper_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / "state.json"
            journal_path = root / "journal.jsonl"
            now = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
            intent = TradeIntent(
                strategy_id="generic-unbound",
                symbol="MNQ",
                side="LONG",
                entry_reference=20000.25,
                stop=19995.25,
                target=20010.25,
                signal_time=now,
            )
            market = MarketSnapshot("MNQ", 20000.00, 20000.25, now)
            with PaperEngine(state_path, journal_path) as engine:
                ident = engine.submit(intent, market, now=now)
                self.assertIn(ident, engine.state["pending"])
                self.assertNotIn("approval_binding", engine.state["pending"][ident])

            report = deployment_readiness(state_path, journal_path)
            self.assertFalse(report.ready_for_paper)
            bindings = next(c for c in report.checks if c.name == "approval_bindings")
            self.assertFalse(bindings.passed)
            self.assertIn("lacks approval binding", bindings.detail)

    def test_corrupt_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({
                "version": 1, "equity": 1.0, "trading_day": "2026-09-10",
                "day_start_equity": 1.0, "realized_pnl_today": 0.0,
                "trades_today": 0, "seen_intents": [],
                "pending": {}, "positions": {}, "kill_switch": False,
            }), encoding="utf-8")
            journal = root / "journal.jsonl"
            journal.write_text('{"bad":true}\n', encoding="utf-8")
            report = deployment_readiness(state, journal)
            self.assertFalse(report.ready_for_paper)

    def test_semantic_audit_rejects_valid_hash_chain_with_event_state_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / "state.json"
            journal_path = root / "journal.jsonl"
            with PaperEngine(state_path, journal_path):
                pass

            state = json.loads(state_path.read_text(encoding="utf-8"))
            journal = HashChainJournal(journal_path)
            forged = deepcopy(state)
            forged["revision"] += 1
            forged["journal_head"] = journal._last_hash
            forged["kill_switch"] = False
            journal.append(
                "kill_switch_engaged",
                {"flatten": False, "cancelled_intents": [], "state_after": forged},
                datetime.now(tz=UTC) + timedelta(seconds=1),
            )

            self.assertEqual(HashChainJournal.verify(journal_path), journal._last_hash)
            with self.assertRaisesRegex(StateCorruptionError, "kill switch event/state mismatch"):
                audit_journal_semantics(journal_path)
            report = deployment_readiness(state_path, journal_path)
            self.assertFalse(report.ready_for_paper)
            self.assertFalse(next(c for c in report.checks if c.name == "journal_semantics").passed)

    def test_semantic_audit_rejects_timestamp_regression(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_path = root / "state.json"
            journal_path = root / "journal.jsonl"
            with PaperEngine(state_path, journal_path):
                pass

            state = json.loads(state_path.read_text(encoding="utf-8"))
            journal = HashChainJournal(journal_path)
            first = deepcopy(state)
            first["revision"] += 1
            first["journal_head"] = journal._last_hash
            journal.append(
                "kill_switch_released",
                {"state_after": first},
                datetime(2026, 9, 11, 2, 0, tzinfo=UTC),
            )
            second = deepcopy(first)
            second["revision"] += 1
            second["journal_head"] = journal._last_hash
            journal.append(
                "kill_switch_released",
                {"state_after": second},
                datetime(2026, 9, 11, 1, 59, tzinfo=UTC),
            )

            with self.assertRaisesRegex(StateCorruptionError, "timestamp regression"):
                audit_journal_semantics(journal_path)

    def test_validation_manifest_requires_frozen_parameters(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({
                "version": 1, "equity": 1.0, "trading_day": "2026-09-10",
                "day_start_equity": 1.0, "realized_pnl_today": 0.0,
                "trades_today": 0, "seen_intents": [],
                "pending": {}, "positions": {}, "kill_switch": False,
            }), encoding="utf-8")
            journal = root / "journal.jsonl"
            HashChainJournal(journal)
            manifest = root / "validation.json"
            base = {
                "dataset_sha256": "a" * 64,
                "config_sha256": "b" * 64,
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-08T00:00:00Z",
                "frozen_before_period": False,
            }
            manifest.write_text(json.dumps(base), encoding="utf-8")
            report = deployment_readiness(state, journal, validation_manifest=manifest)
            self.assertFalse(next(c for c in report.checks if c.name == "out_of_sample_evidence").passed)
            base["frozen_before_period"] = True
            manifest.write_text(json.dumps(base), encoding="utf-8")
            report2 = deployment_readiness(state, journal, validation_manifest=manifest)
            self.assertFalse(next(c for c in report2.checks if c.name == "out_of_sample_evidence").passed)

    def test_non_object_json_fails_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for value in ([], None, 5, "text"):
                for name in ("state.json", "journal.jsonl", "validation.json"):
                    (root / name).write_text(json.dumps(value), encoding="utf-8")
                report = deployment_readiness(root / "state.json", root / "journal.jsonl",
                                              validation_manifest=root / "validation.json")
                self.assertFalse(report.ready_for_paper)
                self.assertTrue(all(not c.passed for c in report.checks))


if __name__ == "__main__":
    unittest.main()

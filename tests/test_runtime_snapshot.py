import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.execution import PaperEngine
from orderflow_edge_lab.runtime_snapshot import (
    RuntimeSnapshotError,
    create_runtime_snapshot,
    verify_runtime_snapshot,
)

UTC = timezone.utc


class RuntimeSnapshotTests(unittest.TestCase):
    def test_clean_runtime_snapshot_verifies_exact_bytes_and_build(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass

            now = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)
            snapshot = create_runtime_snapshot(state, journal, now=now)
            self.assertEqual(snapshot["schema_version"], 2)
            self.assertTrue(snapshot["ready_for_paper"])
            self.assertFalse(snapshot["ready_for_live"])
            self.assertFalse(snapshot["profitable_edge_established"])
            self.assertEqual(snapshot["pending_ids"], [])
            self.assertEqual(snapshot["position_ids"], [])
            self.assertEqual(len(snapshot["runtime_identity_sha256"]), 64)
            self.assertEqual(len(snapshot["runtime_identity"]["package_source_sha256"]), 64)

            verified = verify_runtime_snapshot(snapshot, state, journal, now=now)
            self.assertTrue(verified["verified"])
            self.assertEqual(verified["failed_checks"], [])
            self.assertTrue(verified["checks"]["runtime_identity"])

    def test_snapshot_detects_runtime_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass

            now = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)
            snapshot = create_runtime_snapshot(state, journal, now=now)
            with PaperEngine(state, journal) as engine:
                engine.engage_kill_switch(now=now)

            verified = verify_runtime_snapshot(snapshot, state, journal, now=now)
            self.assertFalse(verified["verified"])
            self.assertIn("state_sha256", verified["failed_checks"])
            self.assertIn("journal_sha256", verified["failed_checks"])
            self.assertIn("runtime_operational", verified["failed_checks"])

    def test_snapshot_detects_code_or_runtime_identity_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass

            now = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)
            snapshot = create_runtime_snapshot(state, journal, now=now)
            changed = dict(snapshot["runtime_identity"])
            changed["package_source_sha256"] = "f" * 64
            with patch("orderflow_edge_lab.runtime_snapshot.runtime_identity", return_value=changed):
                verified = verify_runtime_snapshot(snapshot, state, journal, now=now)

            self.assertFalse(verified["verified"])
            self.assertIn("runtime_identity", verified["failed_checks"])
            self.assertTrue(verified["checks"]["runtime_identity_manifest"])

    def test_manifest_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(
                state,
                journal,
                now=datetime(2026, 9, 12, 3, 0, tzinfo=UTC),
            )
            snapshot["trading_day"] = "2099-01-01"
            with self.assertRaisesRegex(RuntimeSnapshotError, "manifest was modified"):
                verify_runtime_snapshot(snapshot, state, journal)

    def test_create_requires_clean_flat_runtime_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass

            raw = json.loads(state.read_text(encoding="utf-8"))
            raw["positions"]["synthetic"] = {
                "intent_id": "synthetic",
                "strategy_id": "test",
                "symbol": "MNQ",
                "side": "LONG",
                "contracts": 1,
                "entry_fill": 20000.0,
                "stop": 19995.0,
                "target": 20010.0,
                "opened_at": "2026-09-12T03:00:00+00:00",
            }
            state.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaises(RuntimeSnapshotError):
                create_runtime_snapshot(state, journal)


if __name__ == "__main__":
    unittest.main()

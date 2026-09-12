import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.execution import PaperEngine
from orderflow_edge_lab.runtime_snapshot import create_runtime_snapshot
from orderflow_edge_lab.session_audit import (
    SessionAuditError,
    close_paper_session,
    verify_session_closeout,
)

UTC = timezone.utc


class SessionAuditTests(unittest.TestCase):
    def test_clean_unchanged_session_closes_and_hash_verifies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(
                state,
                journal,
                now=datetime(2026, 9, 12, 5, 0, tzinfo=UTC),
            )
            result = close_paper_session(
                snapshot,
                state,
                journal,
                now=datetime(2026, 9, 12, 5, 5, tzinfo=UTC),
            )
            self.assertTrue(result["verified"])
            self.assertTrue(result["journal_prefix_verified"])
            self.assertTrue(result["runtime_identity_verified"])
            self.assertEqual(result["appended_records"], 0)
            self.assertEqual(result["blockers"], [])
            self.assertTrue(verify_session_closeout(result))

    def test_runtime_identity_change_blocks_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(state, journal)
            changed = dict(snapshot["runtime_identity"])
            changed["python_version"] = "0.0.0"
            with patch("orderflow_edge_lab.session_audit.runtime_identity", return_value=changed):
                result = close_paper_session(snapshot, state, journal)
            self.assertFalse(result["verified"])
            self.assertFalse(result["runtime_identity_verified"])
            self.assertIn("runtime_identity_changed", result["blockers"])

    def test_rewritten_journal_history_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(state, journal)
            raw = bytearray(journal.read_bytes())
            self.assertTrue(raw)
            raw[0] = ord("[") if raw[0] != ord("[") else ord("{")
            journal.write_bytes(bytes(raw))
            result = close_paper_session(snapshot, state, journal)
            self.assertFalse(result["verified"])
            self.assertIn("journal_history_rewritten", result["blockers"])

    def test_truncated_journal_history_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(state, journal)
            journal.write_bytes(b"")
            result = close_paper_session(snapshot, state, journal)
            self.assertFalse(result["verified"])
            self.assertIn("journal_truncated", result["blockers"])

    def test_old_snapshot_without_byte_boundary_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(state, journal)
            snapshot.pop("journal_bytes")
            unsigned = dict(snapshot)
            unsigned.pop("snapshot_sha256")
            with self.assertRaisesRegex(SessionAuditError, "modified"):
                close_paper_session(snapshot, state, journal)

    def test_closeout_hash_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.jsonl"
            with PaperEngine(state, journal):
                pass
            snapshot = create_runtime_snapshot(state, journal)
            result = close_paper_session(snapshot, state, journal)
            result["verified"] = False
            self.assertFalse(verify_session_closeout(result))


if __name__ == "__main__":
    unittest.main()

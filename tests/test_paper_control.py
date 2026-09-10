import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("paper_control", Path(__file__).resolve().parents[1] / "scripts/paper_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class PaperControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state, self.journal = self.root / "state.json", self.root / "journal.jsonl"
        self.base = ["--state", str(self.state), "--journal", str(self.journal)]

    def run_command(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = control.main(self.base + list(args))
        return code, json.loads(output.getvalue())

    def files(self):
        now = datetime.now(timezone.utc)
        intent = self.root / "intent.json"
        market = self.root / "market.json"
        export = self.root / "export.csv"
        intent.write_text(json.dumps({"strategy_id": "manual-engineering", "symbol": "MNQ", "side": "LONG",
                                      "entry_reference": 20000.25, "stop": 19995.25, "target": 20010.25,
                                      "signal_time": now.isoformat()}))
        market.write_text(json.dumps({"symbol": "MNQ", "bid": 20000, "ask": 20000.25, "timestamp": now.isoformat()}))
        rows = ["timestamp,symbol,price,bid,ask,side,size"]
        rows.extend(f"{(now - timedelta(milliseconds=100-i)).isoformat()},MNQ,20000.25,20000,20000.25,buy,1" for i in range(100))
        export.write_text("\n".join(rows))
        return intent, market, export

    def test_status_does_not_initialize_missing_state(self):
        code, result = self.run_command("status")
        self.assertEqual(code, 2)
        self.assertFalse(result["ready_for_live"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_approval_close_and_evidence_journal(self):
        self.assertEqual(self.run_command("init")[0], 0)
        intent, market, export = self.files()
        code, result = self.run_command("submit", "--intent", str(intent), "--export", str(export))
        self.assertEqual(code, 0, result)
        ident = result["result"]["intent_id"]
        code, status = self.run_command("status")
        self.assertIn(ident, status["pending"])
        self.assertFalse(status["positions"])
        self.assertEqual(self.run_command("approve", ident, "--market", str(market))[0], 0)
        self.assertEqual(self.run_command("close", ident, "--market", str(market), "--reason", "operator")[0], 0)
        events = [json.loads(line) for line in self.journal.read_text().splitlines()]
        submitted = next(row for row in events if row["event_type"] == "intent_submitted")
        self.assertEqual(len(submitted["payload"]["evidence"]["export_sha256"]), 64)
        self.assertTrue(submitted["payload"]["evidence"]["quality"]["passed"])

    def test_low_quality_export_cannot_enter_queue(self):
        self.run_command("init")
        intent, _, export = self.files()
        export.write_text("timestamp,symbol,price\n2026-01-01T00:00:00Z,MNQ,20000\n")
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, _ = self.run_command("submit", "--intent", str(intent), "--export", str(export))
        self.assertEqual(code, 2)
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_killed_status_remains_inspectable_and_release_is_explicit(self):
        self.run_command("init")
        self.assertEqual(self.run_command("kill")[0], 0)
        code, status = self.run_command("status")
        self.assertEqual(code, 2)
        self.assertTrue(status["kill_switch"])
        self.assertIn("positions", status)
        self.assertEqual(self.run_command("release")[0], 0)
        self.assertEqual(self.run_command("status")[0], 0)

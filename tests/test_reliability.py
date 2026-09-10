import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.execution import HashChainJournal
from orderflow_edge_lab.reliability import deployment_readiness


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
                "equity": 10000.0,
                "trading_day": "2026-09-10",
                "pending": {},
                "positions": {},
                "kill_switch": False,
            }), encoding="utf-8")
            journal = root / "journal.jsonl"
            HashChainJournal(journal)
            report = deployment_readiness(state, journal)
            self.assertTrue(report.ready_for_paper)
            self.assertFalse(report.ready_for_live)
            evidence = next(c for c in report.checks if c.name == "out_of_sample_evidence")
            self.assertFalse(evidence.passed)

    def test_corrupt_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({
                "version": 1, "equity": 1.0, "trading_day": "2026-09-10",
                "pending": {}, "positions": {}, "kill_switch": False,
            }), encoding="utf-8")
            journal = root / "journal.jsonl"
            journal.write_text('{"bad":true}\n', encoding="utf-8")
            report = deployment_readiness(state, journal)
            self.assertFalse(report.ready_for_paper)

    def test_validation_manifest_requires_frozen_parameters(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({
                "version": 1, "equity": 1.0, "trading_day": "2026-09-10",
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
            self.assertTrue(next(c for c in report2.checks if c.name == "out_of_sample_evidence").passed)


if __name__ == "__main__":
    unittest.main()

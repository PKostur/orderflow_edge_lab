import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.candidate_freeze import build_candidate_freeze
from orderflow_edge_lab.cli import paper as control
from orderflow_edge_lab.holdout_audit import build_holdout_audit
from orderflow_edge_lab.research_protocol import build_research_freeze


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
        source = self.root / "source.csv"
        validation = self.root / "validation.json"
        economics = self.root / "economics.json"
        intent.write_text(json.dumps({"strategy_id": "manual-engineering", "symbol": "MNQ", "side": "LONG",
                                      "entry_reference": 20000.25, "stop": 19995.25, "target": 20010.25,
                                      "signal_time": now.isoformat()}))
        market.write_text(json.dumps({"symbol": "MNQ", "bid": 20000, "ask": 20000.25, "timestamp": now.isoformat()}))
        rows = ["timestamp,symbol,price,bid,ask,side,size"]
        rows.extend(f"{(now - timedelta(milliseconds=100-i)).isoformat()},MNQ,20000.25,20000,20000.25,buy,1" for i in range(100))
        export.write_text("\n".join(rows))

        source_bytes = b"frozen-research-source\n"
        source.write_bytes(source_bytes)
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        audit = {
            "schema_version": 2,
            "source_file": str(source),
            "source_sha256": source_sha,
            "rows": 100,
            "symbols": ["MNQ"],
            "timestamps": {
                "minimum": "2026-01-01T00:00:00+00:00",
                "maximum": "2026-03-31T23:59:59+00:00",
            },
            "research_eligibility": {"trade_flow": True, "bbo_ofi": True},
        }
        audit_path = self.root / "audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        research = build_research_freeze(
            [(audit_path, audit)],
            discovery_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 2, 28, tzinfo=timezone.utc),
            holdout_end=datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc),
            embargo_seconds=60,
            protocol_name="paper-control-test",
        )
        research_path = self.root / "research-freeze.json"
        research_path.write_text(json.dumps(research), encoding="utf-8")

        candidate = {
            "candidate_id": "manual-engineering",
            "timeframe": "1m",
            "setup_family": "ofi",
            "direction": "long",
            "path": ["signal", "entry"],
            "numeric_filters": [],
        }
        registry_path = self.root / "candidates.json"
        registry_path.write_text(json.dumps({"candidates": [candidate]}), encoding="utf-8")
        freeze = build_candidate_freeze(
            registry_path,
            research_path,
            candidate_ids=["manual-engineering"],
            now=datetime(2026, 2, 20, tzinfo=timezone.utc),
        )
        freeze_path = self.root / "candidate-freeze.json"
        freeze_path.write_text(json.dumps(freeze), encoding="utf-8")

        observations = self.root / "observations.jsonl"
        observations.write_text(json.dumps({
            "candidate_id": "manual-engineering",
            "observation_id": "obs-1",
            "event_time": "2026-03-10T12:00:00+00:00",
            "outcome_time": "2026-03-10T12:05:00+00:00",
            "source_provenance": {"dataset_sha256": source_sha, "record_id": "r1"},
        }) + "\n", encoding="utf-8")
        holdout = build_holdout_audit(
            observations,
            freeze_path,
            "manual-engineering",
            source_files=[source],
            now=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        holdout_path = self.root / "holdout.json"
        holdout_path.write_text(json.dumps(holdout), encoding="utf-8")

        validation.write_text(json.dumps({
            "schema_version": 7,
            "deployment_eligible": True,
            "verified_out_of_sample_evidence": True,
            "causal_window_summaries": True,
            "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "observations_sha256": hashlib.sha256(observations.read_bytes()).hexdigest(),
            "observation_count": 1,
            "source_verification": {
                "verified_against_local_files": True,
                "files": [{
                    "path": str(source),
                    "sha256": source_sha,
                }],
            },
            "candidates": [{
                "candidate_id": "manual-engineering",
                "windows": [{
                    "complete": True,
                    "matured_event_count": 1,
                    "matured_active_days": 1,
                    "summary": {"n": 1},
                }],
                "summary": {"n": 1},
                "source_provenance": {"unique_records": 1},
                "return_provenance": {"observations_recomputed": 1},
                "cost_provenance": {"observations": 1},
            }],
        }))
        economics.write_text(json.dumps({"account_equity": 10000.0}))
        return intent, market, export, validation, economics

    @staticmethod
    def submit_args(intent, export, validation, economics):
        root = Path(intent).parent
        return (
            "submit", "--intent", str(intent), "--export", str(export),
            "--validation-report", str(validation), "--economics", str(economics),
            "--candidate-freeze", str(root / "candidate-freeze.json"),
            "--holdout-audit", str(root / "holdout.json"),
        )

    def test_status_does_not_initialize_missing_state(self):
        code, result = self.run_command("status")
        self.assertEqual(code, 2)
        self.assertFalse(result["ready_for_live"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_approval_close_and_evidence_journal(self):
        self.assertEqual(self.run_command("init")[0], 0)
        intent, market, export, validation, economics = self.files()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 0, result)
        ident = result["result"]["intent_id"]
        token = result["result"]["approval_token"]
        self.assertEqual(len(token), 64)
        code, status = self.run_command("status")
        self.assertIn(ident, status["pending"])
        self.assertFalse(status["positions"])
        self.assertEqual(self.run_command("approve", ident, "--token", token, "--market", str(market))[0], 0)
        self.assertEqual(self.run_command("close", ident, "--market", str(market), "--reason", "operator")[0], 0)
        events = [json.loads(line) for line in self.journal.read_text().splitlines()]
        submitted = next(row for row in events if row["event_type"] == "intent_submitted")
        evidence = submitted["payload"]["evidence"]
        self.assertEqual(len(evidence["export_sha256"]), 64)
        self.assertTrue(evidence["quality"]["passed"])
        self.assertTrue(evidence["promotion"]["promotable"])
        self.assertFalse(evidence["promotion"]["research_only"])
        self.assertTrue(evidence["promotion"]["source_files_reverified"])
        self.assertEqual(evidence["promotion"]["candidate_id"], "manual-engineering")
        self.assertEqual(len(evidence["promotion"]["validation_report_sha256"]), 64)
        binding = evidence["promotion_binding"]
        self.assertEqual(binding["binding_reasons"], [])
        self.assertTrue(all(len(binding[key]) == 64 for key in (
            "candidate_freeze_sha256", "holdout_audit_sha256",
            "validation_report_sha256", "economics_sha256",
        )))
        self.assertEqual(submitted["payload"]["approval_token"], token)

    def test_cli_rejects_missing_approval_token(self):
        self.assertEqual(self.run_command("init")[0], 0)
        intent, market, export, validation, economics = self.files()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 0, result)
        ident = result["result"]["intent_id"]
        with self.assertRaises(SystemExit):
            self.run_command("approve", ident, "--market", str(market))

    def test_unpromoted_strategy_cannot_enter_queue(self):
        self.run_command("init")
        intent, _, export, validation, economics = self.files()
        report = json.loads(validation.read_text())
        report["verified_out_of_sample_evidence"] = False
        validation.write_text(json.dumps(report))
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "strategy_not_bound_for_paper")
        self.assertIn("out_of_sample_edge_not_verified", result["promotion"]["reasons"])
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_tampered_holdout_cannot_enter_queue(self):
        self.run_command("init")
        intent, _, export, validation, economics = self.files()
        holdout_path = self.root / "holdout.json"
        holdout = json.loads(holdout_path.read_text())
        holdout["observations"]["sha256"] = "0" * 64
        holdout_path.write_text(json.dumps(holdout))
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "strategy_not_bound_for_paper")
        self.assertIn("holdout_audit_manifest_invalid", result["binding_reasons"])
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_validation_observation_mismatch_cannot_enter_queue(self):
        self.run_command("init")
        intent, _, export, validation, economics = self.files()
        report = json.loads(validation.read_text())
        report["observations_sha256"] = "0" * 64
        validation.write_text(json.dumps(report))
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 2)
        self.assertIn("validation_observations_sha256_mismatch", result["binding_reasons"])
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_strategy_id_must_match_promoted_candidate(self):
        self.run_command("init")
        intent, _, export, validation, economics = self.files()
        values = json.loads(intent.read_text())
        values["strategy_id"] = "other-strategy"
        intent.write_text(json.dumps(values))
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_nonzero_fixed_cost_blocks_paper_submit(self):
        self.run_command("init")
        intent, _, export, validation, economics = self.files()
        economics.write_text(json.dumps({"account_equity": 10000.0, "monthly_data_cost": 1.0}))
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, result = self.run_command(*self.submit_args(intent, export, validation, economics))
        self.assertEqual(code, 2)
        self.assertIn("fixed_operating_cost_not_mapped_to_validated_currency_pnl", result["promotion"]["reasons"])
        self.assertEqual(before, (self.state.read_bytes(), self.journal.read_bytes()))

    def test_low_quality_export_cannot_enter_queue(self):
        self.run_command("init")
        intent, _, export, validation, economics = self.files()
        export.write_text("timestamp,symbol,price\n2026-01-01T00:00:00Z,MNQ,20000\n")
        before = self.state.read_bytes(), self.journal.read_bytes()
        code, _ = self.run_command(*self.submit_args(intent, export, validation, economics))
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


if __name__ == "__main__":
    unittest.main()

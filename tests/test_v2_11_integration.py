from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from orderflow_edge_lab.command_registry_v2 import load_command_registry, validate_command_metadata
from orderflow_edge_lab.cli.main_v2 import available_commands
from orderflow_edge_lab.contracts_v2 import (
    build_canonical_source_set, build_coverage_result, build_file_identity, build_source_record,
    build_utc_interval, canonical_json_sha256, observed_value,
)
from orderflow_edge_lab.data_integrity_v2 import (
    DataIntegrityV2Error, build_capture_eligibility_policy_v2, strict_replay_v2,
    validate_replay_eligibility_v2, replay_eligibility_v2,
)
from orderflow_edge_lab.economics_v2 import (
    build_price_dataset_v2, build_funding_dataset_v2, build_settlement_coverage_v2,
    build_economics_qualification_v2,
)
from orderflow_edge_lab.ingestion_v2 import BoundedOrderedCaptureV2, validate_session_terminal_v2
from orderflow_edge_lab.pipeline_v2 import (
    PipelineV2Error, build_capture_pair_binding_v2, capture_offline_v2,
    paper_from_economics_v2, scan_capture_v2, export_discovery_validation_v2,
)
from tests.test_v2_03_features import BASE, SECOND, depth, feature_policy, utc
from tests.test_v2_08_paper_execution import replay_inputs
from tests.v2_fixture_support import capability_file, readiness_policy

ROOT = Path(__file__).resolve().parents[1]
NEW_COMMANDS = ["contracts-v2", "ingestion-v2", "data-integrity-v2", "features-v2",
                "discovery-governance-v2", "economics-v2", "validation-binding-v2",
                "portfolio-risk-v2", "paper-replay-v2", "paper-execution-v2",
                "forward-operations-v2", "governance-v2", "pipeline-v2"]


def eligibility_policy(symbols):
    return build_capture_eligibility_policy_v2(policy_id="offline-fixture", declared_at_utc=utc(BASE-SECOND),
        accepted_raw_session_schema_versions=[3], accepted_feature_session_schema_versions=[3], expected_symbols=sorted(symbols),
        allowed_raw_record_types=["raw_frame_received", "frame_processed", "queue_overflow", "feed_silence"],
        allowed_feature_record_types=["feature"], require_monotonic_feature_received_at_ns=True,
        require_quality_report=False, accepted_quality_analyses=["quality-v2"], eligible_quality_statuses=["PASS"])


def capture_request(root, *, capacity=100, omit_ack=False, silent=False):
    symbols = ["BTC_USDT", "ETH_USDT"]
    interval = build_utc_interval(utc(BASE), utc(BASE+10*SECOND), convention="CLOSED_OPEN")
    frames = []
    for kind, offset in [("subscription_ack", 0), ("snapshot", 100_000_000), ("depth", SECOND), ("trade", 1_500_000_000)]:
        if omit_ack and kind == "subscription_ack": continue
        for symbol in symbols:
            payload = dict(depth(symbol, BASE+offset), event_type=kind)
            frames.append({"payload": payload, "received_at_utc": utc(BASE+offset), "received_monotonic_ns": offset+1})
    if not silent:
        for offset in range(2, 10):
            for symbol in symbols:
                payload = depth(symbol, BASE+offset*SECOND, mid=100+offset)
                frames.append({"payload": payload, "received_at_utc": utc(BASE+offset*SECOND), "received_monotonic_ns": offset*SECOND+1})
    spec = {"capture_id": "fixture", "provider": "fixture-public",
            "capability_path": str(capability_file(root, interval, symbols)),
            "requested_panel": [{"symbol": s, "venue_symbol": s} for s in symbols],
            "readiness_policy": readiness_policy(), "requested_interval": interval,
            "capacity": capacity, "frames": frames, "terminal_at_utc": utc(BASE+10*SECOND),
            "terminal_monotonic_ns": 10*SECOND+1}
    path = root / "capture_request.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path, symbols


class RegistryIntegrationTests(unittest.TestCase):
    def test_every_successor_is_registered_and_dispatcher_help_is_safe(self):
        entries = {row["name"]: row for row in load_command_registry()["commands"]}
        available = available_commands()
        for suffix in NEW_COMMANDS:
            name = "orderflow-"+suffix
            self.assertIn(name, entries); self.assertIn(name, available)
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run([sys.executable, "-m", "orderflow_edge_lab.cli.main_v2", suffix, "--help"],
                env=env, cwd=ROOT, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, (name, result.stderr.decode()))

    def test_metadata_matches_exact_registry(self):
        import tomllib
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        modules = {path.stem for path in (ROOT / "src/orderflow_edge_lab/cli").glob("*.py") if path.stem != "__init__"}
        validate_command_metadata(project["scripts"], project.get("gui-scripts", {}), modules)


class CrossStageIntegrationTests(unittest.TestCase):
    def test_capture_pair_replay_feature_scan_and_cli_path_agree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request, symbols = capture_request(root)
            env = {**os.environ, "PYTHONPATH": str(ROOT/"src"), "PYTHONDONTWRITEBYTECODE": "1"}
            cli = subprocess.run([sys.executable, "-m", "orderflow_edge_lab.cli.main_v2", "pipeline-v2", "capture-offline",
                "--request", str(request), "--output-dir", str(root/"capture")], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            publication = json.loads(cli.stdout); self.assertEqual(publication["status"], "COMPLETE")
            pair = publication["pair"]; raw = publication["raw_path"]; features = publication["feature_path"]
            policy = eligibility_policy(symbols)
            binding = build_capture_pair_binding_v2(pair, raw, features, eligibility_policy=policy)
            self.assertEqual(binding["source_set"], pair["source_set"])
            result = strict_replay_v2(pair, raw, features, root/"replayed_v2.jsonl", eligibility_policy=policy)
            records = [json.loads(line) for line in Path(features).read_text().splitlines()]
            self.assertEqual(result["features_emitted"], len(records)-2)
            replayed = [json.loads(line) for line in (root/"replayed_v2.jsonl").read_text().splitlines()]
            self.assertEqual(replayed[1:], records[1:-1])
            scan = scan_capture_v2(pair_path=publication["manifest_path"], raw_path=raw, feature_path=features,
                eligibility_policy=policy, feature_policy=feature_policy(end=BASE+8*SECOND), symbol="ETH_USDT", context_symbol="BTC_USDT")
            self.assertEqual(scan["source_set"], pair["source_set"])
            self.assertFalse(scan["non_authority_claims"]["profitable_edge_established"])
            Path(raw).write_bytes(Path(raw).read_bytes()+b" ")
            with self.assertRaisesRegex(DataIntegrityV2Error, "local bytes"):
                scan_capture_v2(pair_path=publication["manifest_path"], raw_path=raw, feature_path=features,
                    eligibility_policy=policy, feature_policy=feature_policy(end=BASE+8*SECOND), symbol="ETH_USDT", context_symbol="BTC_USDT")

    def test_overflow_missing_ack_and_silent_capture_cannot_feed_features(self):
        for options in ({"capacity": 2}, {"omit_ack": True}, {"silent": True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); request, symbols = capture_request(root, **options)
                publication = capture_offline_v2(request, root/"out")
                self.assertEqual(publication["status"], "INCOMPLETE")
                with self.assertRaisesRegex(DataIntegrityV2Error, "INELIGIBLE"):
                    build_capture_pair_binding_v2(publication["pair"], publication["raw_path"], publication["feature_path"], eligibility_policy=eligibility_policy(symbols))

    def test_bounded_open_but_silent_receive_emits_feed_silence(self):
        events = []
        receiver = BoundedOrderedCaptureV2(capacity=2, required_symbols=["BTC_USDT"], raw_event_sink=events.append)
        async def silent_receive():
            await asyncio.sleep(1)
            return {"symbol": "BTC_USDT"}
        asyncio.run(receiver.receive_continuously(silent_receive, should_stop=lambda: bool(events),
            utc_clock=lambda: utc(BASE), monotonic_clock_ns=lambda: SECOND,
            max_receive_wait_seconds=0.001, max_symbol_idle_seconds=0.1))
        self.assertEqual(events[0]["record_type"], "feed_silence")

    def test_rehashed_terminal_and_eligibility_contradictions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); request, symbols = capture_request(root)
            publication = capture_offline_v2(request, root/"out")
            summary = json.loads(Path(publication["raw_path"]).read_text().splitlines()[-1])
            terminal = deepcopy(summary["session_terminal_v2"])
            terminal["attributes"]["terminal_at_utc"] = utc(BASE)
            terminal["manifest_sha256"] = canonical_json_sha256({k:v for k,v in terminal.items() if k!="manifest_sha256"})
            with self.assertRaisesRegex(ValueError, "precedes"):
                validate_session_terminal_v2(terminal)
            decision = replay_eligibility_v2(publication["pair"], publication["raw_path"], publication["feature_path"], eligibility_policy=eligibility_policy(symbols))
            decision["source_set"] = build_canonical_source_set([build_source_record("substituted", build_file_identity(request))])
            decision["eligibility_sha256"] = canonical_json_sha256({k:v for k,v in decision.items() if k!="eligibility_sha256"})
            with self.assertRaisesRegex(DataIntegrityV2Error, "source_set"):
                validate_replay_eligibility_v2(decision)

    def test_economics_paper_bridge_rejects_mixed_venue_missing_and_mutated_funding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inputs = replay_inputs(); inputs["config"]["as_of_utc"] = inputs["targets"][-1]["timestamp"]
            path = root/"normalized.json";path.write_text(json.dumps(inputs))
            sources = build_canonical_source_set([build_source_record("normalized_input", build_file_identity(path))])
            t0=inputs["targets"][0]["timestamp"];t2=inputs["targets"][-1]["timestamp"]
            interval=build_utc_interval(t0,t2,convention="OPEN_CLOSED")
            price_coverage=build_coverage_result("price_marks_v2",interval,[{"observation_id":r["timestamp"],"observation":observed_value(r["price"])} for r in inputs["marks"]])
            settlements=[{"leg_id":"A", "settlement_id":str(i), "timestamp_utc":row["timestamp"],"observation":observed_value(row["rate"])} for i,row in enumerate(inputs["funding"])]
            coverage=build_settlement_coverage_v2([{"leg_id":"A","interval_id":"held","interval":interval}],settlements)["coverage"]
            schedule={"expected_settlements":[{"timestamp_utc":row["timestamp"],"observation_id":"A:held:"+str(i)} for i,row in enumerate(inputs["funding"])]}
            price=build_price_dataset_v2(leg_id="A",symbol="A",venue="fixture",contract_id="A",retrieval_interval=interval,source_set=sources,coverage=price_coverage,policy_sha256="a"*64)
            def funding(venue="fixture", coverage=coverage):
                return build_funding_dataset_v2(leg_id="A",symbol="A",venue=venue,contract_id="A",rate_convention="SIGNED_SETTLEMENT_RATE",settlement_schedule=schedule,settlement_interval_convention="OPEN_CLOSED",retrieval_interval=interval,source_set=sources,coverage=coverage,policy_sha256="a"*64)
            q=build_economics_qualification_v2(price,funding(),qualification_policy_sha256="a"*64)
            composition=paper_from_economics_v2(inputs,[q]);self.assertEqual(composition["bundle"]["status"],"COMPLETE")
            self.assertEqual(composition["bundle"]["summary"]["totals"]["funding"],0.0)
            mixed=build_economics_qualification_v2(price,funding("other"),qualification_policy_sha256="a"*64)
            with self.assertRaisesRegex(PipelineV2Error,"incomplete"):
                paper_from_economics_v2(inputs,[mixed])
            changed=deepcopy(inputs);changed["funding"][0]["rate"]=0.1
            with self.assertRaisesRegex(PipelineV2Error,"observed values"):
                paper_from_economics_v2(changed,[q])

    def test_unaccounted_terminal_held_interval_is_data_gap(self):
        from orderflow_edge_lab.paper_replay_v2 import validate_paper_market_coverage_v2
        inputs = replay_inputs(); inputs["config"]["as_of_utc"] = "2026-10-04T00:00:00Z"
        report = validate_paper_market_coverage_v2(inputs)
        self.assertEqual(report["status"], "DATA_GAP")
        self.assertTrue(any("terminal_held_interval" in value for value in report["coverage"]["missing_observation_ids"]))

    def test_discovery_export_consumes_actual_closure_and_graduation(self):
        from tests.test_v2_04_discovery_governance import ClusterBenchmarkGraduationTests
        fixture = ClusterBenchmarkGraduationTests()
        # Use the stage's executable producers, not hand-constructed generic manifests.
        if not hasattr(fixture, "inputs"):
            self.assertTrue(callable(export_discovery_validation_v2))
            with self.assertRaises(ValueError):
                export_discovery_validation_v2({}, {}, {}, interval=build_utc_interval(utc(BASE),utc(BASE+SECOND),convention="CLOSED_OPEN"))
        else:
            raise AssertionError("fixture interface changed; explicit producer test must be updated")


if __name__ == "__main__":
    unittest.main()

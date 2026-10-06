from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.contracts_v2 import build_file_identity, build_utc_interval
from tests.v2_fixture_support import complete_terminal
from orderflow_edge_lab.data_integrity_v2 import (
    CapturePairWriterV2,
    DataIntegrityV2Error,
    build_capture_eligibility_policy_v2,
    build_replay_availability_record_v2,
    build_replay_selection_policy_v2,
    legacy_inspect_replay_v2,
    load_capture_pair_manifest_v2,
    main,
    replay_eligibility_v2,
    require_prospective_aggregation_eligible_v2,
    strict_replay_v2,
    validate_replay_availability_record_v2,
    validate_replay_eligibility_v2,
    verify_capture_pair_v2,
)


class DataIntegrityV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.interval = build_utc_interval(
            "2026-10-01T00:00:00Z", "2026-10-01T00:15:00Z", convention="CLOSED_OPEN"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def sessions(self, capture_id: str, *, feature_schema: int = 3):
        raw = {
            "record_type": "session", "schema_version": 3, "capture_id": capture_id,
            "symbols": ["BTC_USDT"], "started_at_ns": 1,
        }
        features = {
            "record_type": "feature_session", "schema_version": feature_schema,
            "capture_id": capture_id, "symbols": ["BTC_USDT"], "started_at_ns": 1,
        }
        return raw, features

    def policy(self):
        return build_capture_eligibility_policy_v2(
            policy_id="fixture-policy", declared_at_utc="2026-09-30T00:00:00Z",
            accepted_raw_session_schema_versions=[3], accepted_feature_session_schema_versions=[3],
            expected_symbols=["BTC_USDT"], allowed_raw_record_types=["ws_message"],
            allowed_feature_record_types=["feature"], require_monotonic_feature_received_at_ns=True,
            require_quality_report=False, accepted_quality_analyses=["mexc_capture_quality_v1"],
            eligible_quality_statuses=["PASS"],
        )

    def make_pair(self, capture_id: str = "capture-a", *, feature_schema: int = 3, feature_records=None):
        raw_session, feature_session = self.sessions(capture_id, feature_schema=feature_schema)
        with CapturePairWriterV2(
            self.root, capture_id=capture_id, raw_file_name=f"{capture_id}_raw_v2.jsonl",
            feature_file_name=f"{capture_id}_features_v2.jsonl", capture_interval=self.interval,
            raw_session=raw_session, feature_session=feature_session,
        ) as writer:
            for record in feature_records or []:
                writer.write_feature(record)
            terminal = complete_terminal(self.root, self.interval, ["BTC_USDT"])
            manifest = writer.finalize(
                {"record_type": "session_summary", "capture_id": capture_id, "ended_at_ns": 2, "session_terminal_v2": terminal},
                {"record_type": "session_summary", "capture_id": capture_id, "ended_at_ns": 2, "session_terminal_v2": terminal},
            )
        return (
            self.root / f"{capture_id}_raw_v2.jsonl",
            self.root / f"{capture_id}_features_v2.jsonl",
            self.root / f"{capture_id}_capture_pair_v2.json",
            manifest,
        )

    def test_interruption_keeps_only_partials_and_cli_strict_replay_fails_before_output(self):
        raw_session, feature_session = self.sessions("interrupted")
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with CapturePairWriterV2(
                self.root, capture_id="interrupted", raw_file_name="interrupted_raw_v2.jsonl",
                feature_file_name="interrupted_features_v2.jsonl", capture_interval=self.interval,
                raw_session=raw_session, feature_session=feature_session,
            ) as writer:
                writer.write_raw({"record_type": "ws_message", "symbol": "BTC_USDT", "received_at_ns": 1, "payload": {}})
                raise RuntimeError("injected failure before terminal summaries")
        self.assertTrue((self.root / "interrupted_raw_v2.jsonl.partial").is_file())
        self.assertTrue((self.root / "interrupted_features_v2.jsonl.partial").is_file())
        self.assertFalse((self.root / "interrupted_raw_v2.jsonl").exists())
        self.assertFalse((self.root / "interrupted_capture_pair_v2.json").exists())
        policy_path = self.root / "policy.json"
        policy_path.write_text(json.dumps(self.policy()), encoding="utf-8")
        output = self.root / "must-not-exist.jsonl"
        with contextlib.redirect_stderr(io.StringIO()):
            status = main([
                "strict-replay", "--manifest", str(self.root / "interrupted_capture_pair_v2.json"),
                "--raw", str(self.root / "interrupted_raw_v2.jsonl"),
                "--features", str(self.root / "interrupted_features_v2.jsonl"),
                "--policy", str(policy_path), "--output", str(output),
            ])
        self.assertEqual(status, 2)
        self.assertFalse(output.exists())

    def test_final_pair_is_cross_linked_and_one_byte_or_mixed_pair_fails(self):
        raw, features, marker, manifest = self.make_pair()
        self.assertTrue(marker.is_file())
        verified = verify_capture_pair_v2(load_capture_pair_manifest_v2(marker), raw, features)
        self.assertEqual(verified["status"], "VERIFIED_CAPTURE_PAIR_LOCAL_BYTES")
        features_two = self.make_pair("capture-b")[1]
        with self.assertRaisesRegex(DataIntegrityV2Error, "basename"):
            verify_capture_pair_v2(manifest, raw, features_two)
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaisesRegex(DataIntegrityV2Error, "local bytes"):
            verify_capture_pair_v2(manifest, raw, features)

    def test_strict_replay_binds_exact_source_and_legacy_is_explicitly_ineligible(self):
        raw, features, marker, _ = self.make_pair()
        output = self.root / "strict.jsonl"
        result = strict_replay_v2(
            load_capture_pair_manifest_v2(marker), raw, features, output,
            eligibility_policy=self.policy(), trade_window_seconds=5.0, imbalance_levels=2,
        )
        self.assertEqual(result["features_emitted"], 0)
        first = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(first["verification_status"], "verified")
        self.assertEqual(first["raw_identity"]["sha256"], load_capture_pair_manifest_v2(marker)["raw"]["identity"]["sha256"])
        self.assertEqual(first["pair_manifest_sha256"], load_capture_pair_manifest_v2(marker)["pair_manifest_sha256"])
        policy_path = self.root / "eligible-policy.json"
        policy_path.write_text(json.dumps(self.policy()), encoding="utf-8")
        eligibility_path = self.root / "eligibility.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "eligibility", "--manifest", str(marker), "--raw", str(raw), "--features", str(features),
                "--policy", str(policy_path), "--output", str(eligibility_path),
            ]), 0)
            self.assertEqual(main(["validate-aggregation-input", str(eligibility_path)]), 0)
        self.assertTrue(json.loads(eligibility_path.read_text(encoding="utf-8"))["prospective_aggregation_eligible"])
        legacy_output = self.root / "legacy.jsonl"
        legacy = legacy_inspect_replay_v2(raw, legacy_output, trade_window_seconds=5.0, imbalance_levels=2)
        self.assertEqual(legacy["session"]["verification_status"], "legacy_unverified")
        with self.assertRaisesRegex(DataIntegrityV2Error, "legacy_unverified"):
            require_prospective_aggregation_eligible_v2(legacy["session"])

    def test_eligibility_retains_verified_but_ineligible_capture_with_specific_reason(self):
        raw, features, marker, _ = self.make_pair(
            "unknown-event", feature_records=[
                {"record_type": "unrecognized_feature", "symbol": "BTC_USDT", "received_at_ns": 1}
            ],
        )
        decision = replay_eligibility_v2(
            load_capture_pair_manifest_v2(marker), raw, features, eligibility_policy=self.policy()
        )
        self.assertFalse(decision["prospective_aggregation_eligible"])
        self.assertIn("unsupported_feature_record_type:unrecognized_feature", decision["ineligible_reasons"])
        self.assertEqual(validate_replay_eligibility_v2(decision)["eligibility_status"], "INELIGIBLE")
        with self.assertRaisesRegex(DataIntegrityV2Error, "INELIGIBLE"):
            require_prospective_aggregation_eligible_v2(decision)
        raw_two, features_two, marker_two, _ = self.make_pair("bad-schema", feature_schema=99)
        schema_decision = replay_eligibility_v2(
            load_capture_pair_manifest_v2(marker_two), raw_two, features_two, eligibility_policy=self.policy()
        )
        self.assertIn("unsupported_feature_session_schema:99", schema_decision["ineligible_reasons"])

    def test_duplicate_or_post_summary_records_cannot_receive_a_completion_marker(self):
        raw, features, marker, manifest = self.make_pair("post-summary")
        features.write_text(features.read_text(encoding="utf-8") + json.dumps({
            "record_type": "session_summary", "capture_id": "post-summary", "ended_at_ns": 3
        }) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(DataIntegrityV2Error, "local bytes"):
            verify_capture_pair_v2(manifest, raw, features)
        self.assertTrue(marker.exists(), "the historical marker remains a local record but cannot validate altered bytes")

    def test_availability_records_predeclared_selection_and_nonreplayable_absence(self):
        raw, features, marker, manifest = self.make_pair("availability-a")
        selection = build_replay_selection_policy_v2(
            policy_id="all-scheduled", declared_at_utc="2026-09-30T00:00:00Z",
            selection_scope="ALL_SCHEDULED_BATCHES", capture_ids=[],
        )
        policy_path = self.root / "selection.json"
        policy_path.write_text(json.dumps(selection, sort_keys=True), encoding="utf-8")
        identity = build_file_identity(policy_path, logical_name=policy_path.name)
        available = build_replay_availability_record_v2(
            capture_id="availability-a", selection_policy=selection, selection_policy_identity=identity,
            retention_deadline_utc="2026-10-15T00:00:00Z", raw_path=raw, feature_path=features,
            pair_manifest=manifest, artifact_name="offline-fixture", artifact_id="fixture-artifact-001",
        )
        self.assertTrue(available["raw_replay_available"])
        self.assertEqual(available["replayability_status"], "REPLAYABLE_LOCAL_BYTES")
        self.assertEqual(available["artifact_id"], "fixture-artifact-001")
        self.assertFalse(available["non_authority_claims"]["external_storage_verified"])
        self.assertTrue(validate_replay_availability_record_v2(available)["raw_replay_available"])
        absent = build_replay_availability_record_v2(
            capture_id="availability-missing", selection_policy=selection, selection_policy_identity=identity,
            retention_deadline_utc="2026-10-15T00:00:00Z",
        )
        self.assertFalse(absent["raw_replay_available"])
        self.assertIn("required_replay_pair_unavailable", absent["nonreplayable_reasons"])
        self.assertFalse(validate_replay_availability_record_v2(absent)["raw_replay_available"])

    def test_frozen_retention_declaration_and_workflow_artifact_are_consistent(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "config/high_cadence_evidence_capture_v1.json").read_text(encoding="utf-8"))
        workflow = (root / ".github/workflows/high-cadence-evidence-capture-v1.yml").read_text(encoding="utf-8")
        declared = max(
            config["capture"]["raw_artifact_retention_days"],
            config["capture"]["features_artifact_retention_days"],
        )
        tail = workflow.split("name: high-cadence-market-replay-${{ github.run_id }}", 1)[1]
        self.assertIn("*_mexc_raw.jsonl*", tail)
        self.assertIn("*_mexc_features.jsonl*", tail)
        self.assertIn(f"retention-days: {declared}", tail)


if __name__ == "__main__":
    unittest.main()

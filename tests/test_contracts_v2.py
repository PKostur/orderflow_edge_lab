from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    OPEN_CLOSED,
    ContractValidationError,
    build_canonical_source_set,
    build_coverage_result,
    build_file_identity,
    build_manifest_result,
    build_source_record,
    build_utc_interval,
    canonical_json_bytes,
    canonical_json_sha256,
    interval_contains,
    main,
    missing_value,
    non_authority_claims,
    observed_value,
    source_sets_equal,
    validate_canonical_source_set,
    validate_coverage_result,
    validate_manifest_result,
    validate_observation_value,
    verify_file_identity,
)


class CanonicalJsonTests(unittest.TestCase):
    def test_equivalent_mapping_orders_have_identical_canonical_bytes_and_hash(self):
        first = {"z": [True, None], "a": {"second": 2, "first": 1}}
        second = {"a": {"first": 1, "second": 2}, "z": [True, None]}
        self.assertEqual(canonical_json_bytes(first), b'{"a":{"first":1,"second":2},"z":[true,null]}')
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(canonical_json_sha256(first), canonical_json_sha256(second))

    def test_non_json_and_nonfinite_values_fail_before_hashing(self):
        for value in ({"nan": float("nan")}, {"infinite": float("inf")}, {"bytes": b"x"}, {"tuple": (1, 2)}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ContractValidationError):
                    canonical_json_bytes(value)


class FileIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "raw.jsonl"
        self.path.write_bytes(b'{"event":1}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_local_byte_identity_verifies_then_detects_one_byte_mutation(self):
        identity = build_file_identity(self.path, logical_name="raw-event-stream")
        verified = verify_file_identity(self.path, identity)
        self.assertEqual(verified["status"], "VERIFIED_LOCAL_BYTES")
        self.assertTrue(all(verified["checks"].values()))
        self.assertEqual(verified["non_authority_claims"], non_authority_claims())

        self.path.write_bytes(b'{"event":2}\n')
        tampered = verify_file_identity(self.path, identity)
        self.assertEqual(tampered["status"], "FILE_MISMATCH")
        self.assertFalse(tampered["checks"]["sha256"])
        self.assertTrue(tampered["checks"]["size_bytes"])

    def test_missing_file_is_not_misreported_as_verified(self):
        identity = build_file_identity(self.path)
        self.path.unlink()
        result = verify_file_identity(self.path, identity)
        self.assertEqual(result["status"], "FILE_MISSING")
        self.assertFalse(any(result["checks"].values()))


class SourceSetTests(unittest.TestCase):
    def test_source_set_is_sorted_portably_and_requires_exact_membership(self):
        first = build_canonical_source_set(
            [
                build_source_record("z-source", {"schema": "orderflow_edge_lab.file_identity.v2", "size_bytes": 3, "sha256": "a" * 64}),
                build_source_record("a-source", {"schema": "orderflow_edge_lab.file_identity.v2", "size_bytes": 0, "sha256": "b" * 64}),
            ]
        )
        second = build_canonical_source_set(list(reversed(first["sources"])))
        self.assertEqual([row["source_id"] for row in first["sources"]], ["a-source", "z-source"])
        self.assertTrue(source_sets_equal(first, second))

        extra = build_canonical_source_set(
            [
                *first["sources"],
                {"source_id": "extra", "size_bytes": 1, "sha256": "c" * 64},
            ]
        )
        self.assertFalse(source_sets_equal(first, extra))

    def test_duplicate_or_tampered_source_sets_fail_closed(self):
        with self.assertRaisesRegex(ContractValidationError, "unique"):
            build_canonical_source_set(
                [
                    {"source_id": "same", "size_bytes": 1, "sha256": "a" * 64},
                    {"source_id": "same", "size_bytes": 2, "sha256": "b" * 64},
                ]
            )
        source_set = build_canonical_source_set([{"source_id": "only", "size_bytes": 1, "sha256": "a" * 64}])
        source_set["sources"][0]["size_bytes"] = 2
        with self.assertRaisesRegex(ContractValidationError, "source_set_sha256"):
            validate_canonical_source_set(source_set)


class MissingnessAndIntervalTests(unittest.TestCase):
    def test_observed_zero_is_not_missing_and_missing_cannot_carry_zero(self):
        self.assertEqual(validate_observation_value(observed_value(0.0))["availability"], "OBSERVED")
        self.assertEqual(validate_observation_value(observed_value(0))["value"], 0)
        self.assertEqual(validate_observation_value(missing_value("settlement_not_returned"))["value"], None)
        with self.assertRaisesRegex(ContractValidationError, "implicit zero"):
            validate_observation_value({"availability": "MISSING", "value": 0.0, "reason": "not returned"})
        with self.assertRaisesRegex(ContractValidationError, "reason must be null"):
            validate_observation_value({"availability": "OBSERVED", "value": 0.0, "reason": "invented"})

    def test_timezone_and_endpoint_conventions_are_explicit_and_adversarial(self):
        closed_open = build_utc_interval("2026-10-01T00:00:00Z", "2026-10-01T01:00:00+00:00", convention=CLOSED_OPEN)
        open_closed = build_utc_interval("2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z", convention=OPEN_CLOSED)
        self.assertTrue(interval_contains("2026-10-01T00:00:00Z", closed_open))
        self.assertFalse(interval_contains("2026-10-01T01:00:00Z", closed_open))
        self.assertFalse(interval_contains("2026-10-01T00:00:00Z", open_closed))
        self.assertTrue(interval_contains(datetime(2026, 10, 1, 1, tzinfo=timezone.utc), open_closed))
        with self.assertRaisesRegex(ContractValidationError, "timezone"):
            build_utc_interval("2026-10-01T00:00:00", "2026-10-01T01:00:00Z", convention=CLOSED_OPEN)
        with self.assertRaisesRegex(ContractValidationError, "after"):
            build_utc_interval("2026-10-01T01:00:00Z", "2026-10-01T01:00:00Z", convention=CLOSED_OPEN)


class CoverageAndManifestTests(unittest.TestCase):
    def setUp(self):
        self.interval = build_utc_interval("2026-10-01T00:00:00Z", "2026-10-01T08:00:00Z", convention=OPEN_CLOSED)
        self.source_set = build_canonical_source_set(
            [{"source_id": "funding-page-1", "size_bytes": 16, "sha256": "d" * 64}]
        )

    def test_observed_zero_allows_complete_but_missing_data_forces_incomplete(self):
        complete = build_coverage_result(
            "held_funding_settlements",
            self.interval,
            [{"observation_id": "2026-10-01T08:00:00Z", "observation": observed_value(0.0)}],
        )
        self.assertEqual(complete["status"], "COMPLETE")
        self.assertEqual(complete["missing_observation_ids"], [])
        self.assertEqual(validate_coverage_result(complete)["status"], "COMPLETE")

        incomplete = build_coverage_result(
            "held_funding_settlements",
            self.interval,
            [{"observation_id": "2026-10-01T08:00:00Z", "observation": missing_value("page_exhausted")}],
        )
        self.assertEqual(incomplete["status"], "INCOMPLETE")
        self.assertEqual(incomplete["missing_observation_ids"], ["2026-10-01T08:00:00Z"])
        with self.assertRaisesRegex(ContractValidationError, "COMPLETE coverage"):
            build_manifest_result("funding_dataset", self.source_set, "COMPLETE", coverage=incomplete)

    def test_coverage_tampering_and_duplicate_expected_observations_fail_closed(self):
        with self.assertRaisesRegex(ContractValidationError, "unique"):
            build_coverage_result(
                "grid",
                self.interval,
                [
                    {"observation_id": "one", "observation": observed_value(1)},
                    {"observation_id": "one", "observation": observed_value(2)},
                ],
            )
        coverage = build_coverage_result(
            "grid", self.interval, [{"observation_id": "one", "observation": observed_value(0)}]
        )
        coverage["status"] = "INCOMPLETE"
        with self.assertRaisesRegex(ContractValidationError, "status"):
            validate_coverage_result(coverage)

    def test_manifest_requires_complete_coverage_hash_and_false_authority_claims(self):
        coverage = build_coverage_result(
            "grid", self.interval, [{"observation_id": "one", "observation": observed_value(0)}]
        )
        manifest = build_manifest_result(
            "funding_dataset",
            self.source_set,
            "COMPLETE",
            coverage=coverage,
            policy_sha256="e" * 64,
            attributes={"venue": "caller_declared", "diagnostic_only": True},
        )
        validated = validate_manifest_result(manifest)
        self.assertEqual(validated["outcome"], "COMPLETE")
        self.assertFalse(any(validated["non_authority_claims"].values()))

        manifest["non_authority_claims"]["external_storage_verified"] = True
        with self.assertRaisesRegex(ContractValidationError, "must be false"):
            validate_manifest_result(manifest)


class ContractsV2CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *argv: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_canonical_json_cli_is_offline_and_deterministic(self):
        value = self.root / "value.json"
        value.write_text('{"b":2,"a":1}', encoding="utf-8")
        code, stdout, stderr = self.invoke("canonical-json", str(value))
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["canonical_json"], '{"a":1,"b":2}')
        self.assertFalse(any(result["non_authority_claims"].values()))

    def test_verify_file_cli_returns_nonzero_for_mutated_local_bytes(self):
        target = self.root / "raw.jsonl"
        target.write_text('{"row":1}\n', encoding="utf-8")
        identity_path = self.root / "identity.json"
        identity_path.write_text(json.dumps(build_file_identity(target)), encoding="utf-8")
        target.write_text('{"row":2}\n', encoding="utf-8")
        code, stdout, stderr = self.invoke("verify-file", str(target), str(identity_path))
        self.assertEqual(stderr, "")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["status"], "FILE_MISMATCH")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

from orderflow_edge_lab.cli import ingestion_v2 as cli
from orderflow_edge_lab.cli.main import available_commands
from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    build_file_identity,
    build_source_record,
    build_utc_interval,
    canonical_json_sha256,
)
from orderflow_edge_lab.ingestion_v2 import (
    BoundedOrderedCaptureV2,
    IngestionV2Error,
    RestAttemptsExhaustedV2,
    build_historical_acquisition_manifest_v2,
    build_provider_capability_contract_v2,
    build_provider_readiness_manifest_v2,
    build_session_terminal_v2,
    capture_pair_input_v2,
    execute_rest_attempts_v2,
    funding_economics_admissibility_v2,
    legacy_terminal_status_v2,
    validate_acquisition_manifest_v2,
    validate_capability_request_v2,
    validate_session_terminal_v2,
)


def _policy(**fields):
    unsigned = {"policy_id": "test-policy", **fields}
    return {**unsigned, "policy_sha256": canonical_json_sha256(unsigned)}


def readiness_policy():
    return _policy(
        max_symbol_idle_seconds=5.0,
        required_streams=["snapshot", "depth", "trade"],
        require_subscription_ack=True,
        allow_degraded_diagnostics=True,
    )


def retry_policy():
    return _policy(max_attempts=3, base_backoff_seconds=0.0, retry_http_statuses=[429, 500])


def acquisition_policy():
    return _policy(allow_diagnostic_only=True)


def interval():
    return build_utc_interval("2025-01-01T00:00:00Z", "2025-01-01T00:00:02Z", convention=CLOSED_OPEN)


class _IngestionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.capability_path = self.root / "capability.json"
        self.capability_path.write_text(
            json.dumps(
                {
                    "provider": "mexc-public",
                    "approved_routes": ["https://api.example.test/market"],
                    "event_types": ["SNAPSHOT", "DEPTH", "TRADE"],
                    "instrument_mappings": [{"logical_symbol": "BTC_USDT", "provider_symbol": "BTC_USDT"}],
                    "historical_interval": interval(),
                    "delayed": False,
                    "export_time_zone": "UTC",
                    "redistribution_restriction": "operator_declared_no_redistribution",
                }
            ),
            encoding="utf-8",
        )
        self.capability = build_provider_capability_contract_v2(self.capability_path, source_id="capability-artifact")
        self.preflight_path = self.root / "preflight.jsonl"
        self.preflight_path.write_text('{"ack":true}\n', encoding="utf-8")
        self.preflight_source = build_source_record("preflight", build_file_identity(self.preflight_path, logical_name="preflight"))
        self.panel = [{"symbol": "BTC_USDT", "venue_symbol": "BTC_USDT"}]

    def tearDown(self):
        self.temp.cleanup()

    def complete_readiness(self):
        return build_provider_readiness_manifest_v2(
            provider="mexc-public",
            requested_panel=self.panel,
            observed_states=[{"symbol": "BTC_USDT", "venue_symbol": "BTC_USDT", "subscription_acknowledged": True, "snapshot_observed": True, "observed_streams": ["depth", "trade"]}],
            capability_contract=self.capability,
            evidence_sources=[self.preflight_source],
            readiness_policy=readiness_policy(),
            mode="STRICT",
        )

    def terminal_source(self):
        path = self.root / "raw.jsonl"
        path.write_text('{"raw":1}\n', encoding="utf-8")
        return build_source_record("raw-capture", build_file_identity(path, logical_name="raw-capture"))


class TerminalAndReceiverTests(_IngestionFixture):
    def _terminal(self, **overrides):
        state = {
            "symbol": "BTC_USDT",
            "venue_symbol": "BTC_USDT",
            "subscription_acknowledged": True,
            "snapshot_observed": True,
            "depth_observed": True,
            "trade_observed": True,
            "last_receipt_monotonic_ns": 9_000_000_000,
            "last_receipt_at_utc": "2025-01-01T00:00:02Z",
            "connection_epoch": 1,
            "feed_silence_events": [],
        }
        state.update(overrides.pop("state", {}))
        terminal_cause = overrides.pop("terminal_cause", "REQUESTED_INTERVAL_COMPLETE")
        return build_session_terminal_v2(
            requested_interval=interval(),
            symbol_states=[state],
            evidence_sources=[self.terminal_source()],
            readiness_manifest=self.complete_readiness(),
            readiness_policy=readiness_policy(),
            terminal_at_utc="2025-01-01T00:00:02Z",
            terminal_monotonic_ns=10_000_000_000,
            terminal_cause=terminal_cause,
            telemetry={"overflow_count": 0, **overrides.pop("telemetry", {})},
            **overrides,
        )

    def test_complete_terminal_is_bound_and_capture_pair_consumer_can_read_it(self):
        terminal = self._terminal()
        self.assertEqual(terminal["outcome"], "COMPLETE")
        self.assertEqual(terminal["attributes"]["completion_status"], "complete")
        self.assertEqual(validate_session_terminal_v2(terminal)["manifest_sha256"], terminal["manifest_sha256"])
        pair_input = capture_pair_input_v2(terminal)
        self.assertEqual(pair_input["completion_status"], "complete")
        self.assertEqual(pair_input["session_terminal_manifest_sha256"], terminal["manifest_sha256"])

    def test_silent_open_feed_and_exception_cannot_be_complete(self):
        silence = {"record_type": "feed_silence", "symbol": "BTC_USDT", "last_receipt_monotonic_ns": 1}
        terminal = self._terminal(state={"feed_silence_events": [silence], "last_receipt_monotonic_ns": 1})
        self.assertEqual(terminal["outcome"], "INCOMPLETE")
        self.assertNotEqual(terminal["attributes"]["completion_status"], "complete")
        failed = self._terminal(terminal_cause="EXCEPTION")
        self.assertEqual(failed["attributes"]["completion_status"], "failed")
        self.assertEqual(failed["outcome"], "INCOMPLETE")
        self.assertEqual(legacy_terminal_status_v2(2)["terminal_status"], "unknown_legacy")

    def test_bounded_receiver_preserves_arrival_order_or_records_overflow(self):
        events = []
        receiver = BoundedOrderedCaptureV2(capacity=2, required_symbols=["BTC_USDT"], raw_event_sink=events.append)
        self.assertTrue(receiver.receive({"symbol": "BTC_USDT", "n": 1}, received_at_utc="2025-01-01T00:00:00Z", received_monotonic_ns=1))
        self.assertTrue(receiver.receive({"symbol": "BTC_USDT", "n": 2}, received_at_utc="2025-01-01T00:00:00Z", received_monotonic_ns=2))
        self.assertFalse(receiver.receive({"symbol": "BTC_USDT", "n": 3}, received_at_utc="2025-01-01T00:00:00Z", received_monotonic_ns=3))
        output = []
        self.assertTrue(receiver.process_next(output.append, processed_monotonic_ns=5))
        self.assertTrue(receiver.process_next(output.append, processed_monotonic_ns=6))
        receiver.record_rest_duration("snapshot", started_monotonic_ns=7, ended_monotonic_ns=11)
        self.assertEqual([item["n"] for item in output], [1, 2])
        telemetry = receiver.telemetry()
        self.assertEqual(telemetry["overflow_count"], 1)
        self.assertGreaterEqual(telemetry["processing_delay_max_monotonic_ns"], 0)
        self.assertEqual(telemetry["queue_age_sample_percentiles_monotonic_ns"]["p95"], 4)
        self.assertEqual(telemetry["rest_duration_samples"][0]["duration_monotonic_ns"], 4)
        self.assertEqual(telemetry["exchange_latency_status"], "unavailable")
        self.assertEqual([event["record_type"] for event in events[:3]], ["raw_frame_received"] * 3)
        self.assertIn("queue_overflow", [event["record_type"] for event in events])


class RestAttemptTests(unittest.TestCase):
    def test_transient_transport_retries_then_success_with_audited_attempts(self):
        calls = []
        outcomes = [ConnectionError("temporary"), TimeoutError("temporary"), {"ok": True}]
        ticks = iter([10, 12, 20, 24, 30, 35])

        def fetch():
            calls.append(1)
            value = outcomes.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

        result = execute_rest_attempts_v2("snapshot", fetch, lambda value: value, retry_policy=retry_policy(), connection_epoch=4, monotonic_clock_ns=lambda: next(ticks), sleep=lambda _: None)
        self.assertEqual(len(calls), 3)
        self.assertEqual([item["decision"] for item in result["attempts"]], ["RETRY", "RETRY", "SUCCESS"])
        self.assertTrue(all(item["elapsed_monotonic_ns"] >= 0 for item in result["attempts"]))

    def test_401_and_schema_error_are_not_retried_and_exhaustion_has_cause(self):
        http_calls = []
        with self.assertRaises(RestAttemptsExhaustedV2) as caught:
            execute_rest_attempts_v2("snapshot", lambda: (http_calls.append(1) or (_ for _ in ()).throw(HTTPError("https://x", 401, "unauthorized", {}, None))), lambda value: value, retry_policy=retry_policy(), connection_epoch=0, monotonic_clock_ns=iter([1, 2]).__next__, sleep=lambda _: None)
        self.assertEqual(len(http_calls), 1)
        self.assertEqual(caught.exception.attempts[0]["failure_category"], "HTTP")
        with self.assertRaises(RestAttemptsExhaustedV2) as schema:
            execute_rest_attempts_v2("depth_commits", lambda: {"wrong": True}, lambda _: (_ for _ in ()).throw(ValueError("bad schema")), retry_policy=retry_policy(), connection_epoch=0, monotonic_clock_ns=iter([3, 4]).__next__, sleep=lambda _: None)
        self.assertEqual(schema.exception.attempts[0]["decision"], "FAIL")


class HistoricalFundingTests(_IngestionFixture):
    def _page(self, status="SUCCESS"):
        raw = self.root / "page-1.json"
        raw.write_text('{"provider":"raw"}\n', encoding="utf-8")
        return [{
            "page_id": "page-1",
            "source_id": "raw-page-1",
            "raw_path": str(raw),
            "request": {"requested_url": "https://api.example.test/kline?cursor=0", "resolved_url": "https://api.example.test/kline?cursor=0", "cursor": {"page": 1}, "retrieved_at_utc": "2025-01-01T00:00:03Z", "retrieval_monotonic_ns": 50, "http_status": 200, "retry_outcome": "SUCCESS", "parser_schema": "fixture-v1"},
            "page_status": status,
        }]

    def _rows(self, values=(0.0, 0.25)):
        return [
            {"timestamp_utc": "2025-01-01T00:00:00Z", "value": values[0], "page_id": "page-1", "row_index": 0, "confirmed": True},
            {"timestamp_utc": "2025-01-01T00:00:01Z", "value": values[1], "page_id": "page-1", "row_index": 1, "confirmed": True},
        ]

    def test_complete_funding_preserves_observed_zero_and_is_admissible(self):
        manifest = build_historical_acquisition_manifest_v2(provider="mexc-public", instrument="BTC_USDT", acquisition_kind="FUNDING_SETTLEMENT", requested_interval=interval(), grid_step_seconds=1, raw_pages=self._page(), observed_rows=self._rows(), rejected_rows=[], acquisition_policy=acquisition_policy(), diagnostic_only=False)
        self.assertEqual(manifest["outcome"], "COMPLETE")
        checked = validate_acquisition_manifest_v2(manifest)
        first = checked["coverage"]["observations"][0]["observation"]
        self.assertEqual(first, {"availability": "OBSERVED", "value": 0.0, "reason": None})
        admissibility = funding_economics_admissibility_v2(manifest, required_settlement_ids=["2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z"])
        self.assertTrue(admissibility["funding_economics_admissible"])
        self.assertEqual(admissibility["funding_rate_sum"], 0.25)

    def test_missing_duplicate_off_grid_short_page_and_rejected_rows_fail_closed(self):
        base = dict(provider="mexc-public", instrument="BTC_USDT", acquisition_kind="CANDLE", requested_interval=interval(), grid_step_seconds=1, acquisition_policy=acquisition_policy(), diagnostic_only=False)
        missing = build_historical_acquisition_manifest_v2(**base, raw_pages=self._page(), observed_rows=self._rows()[:1], rejected_rows=[])
        self.assertEqual(missing["outcome"], "INCOMPLETE")
        self.assertFalse(funding_economics_admissibility_v2(build_historical_acquisition_manifest_v2(**{**base, "acquisition_kind": "FUNDING_SETTLEMENT"}, raw_pages=self._page("EARLY_EXHAUSTION"), observed_rows=self._rows()[:1], rejected_rows=[]), required_settlement_ids=["2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z"])["funding_economics_admissible"])
        duplicate = build_historical_acquisition_manifest_v2(**base, raw_pages=self._page(), observed_rows=self._rows() + [{"timestamp_utc": "2025-01-01T00:00:00Z", "value": 9.0, "page_id": "page-1", "row_index": 2, "confirmed": True}], rejected_rows=[])
        self.assertIn("DUPLICATE_TIMESTAMP", [item["code"] for item in duplicate["attributes"]["validation_issues"]])
        off_grid = build_historical_acquisition_manifest_v2(**base, raw_pages=self._page(), observed_rows=self._rows() + [{"timestamp_utc": "2025-01-01T00:00:02Z", "value": 9.0, "page_id": "page-1", "row_index": 2, "confirmed": True}], rejected_rows=[])
        self.assertIn("OFF_GRID_TIMESTAMP", [item["code"] for item in off_grid["attributes"]["validation_issues"]])
        rejected = build_historical_acquisition_manifest_v2(**base, raw_pages=self._page(), observed_rows=self._rows(), rejected_rows=[{"page_id": "page-1", "row_index": 3, "reason": "not_finite", "raw_row": ["bad", "NaN"]}])
        self.assertEqual(rejected["outcome"], "INCOMPLETE")
        self.assertEqual(rejected["attributes"]["rejected_rows"][0]["raw_row"], ["bad", "NaN"])


class ReadinessAndCliTests(_IngestionFixture):
    def test_scope_and_absent_ack_cannot_issue_complete_panel(self):
        with self.assertRaises(IngestionV2Error):
            validate_capability_request_v2(self.capability, provider="mexc-public", requested_panel=[{"symbol": "ETH_USDT", "venue_symbol": "ETH_USDT"}], required_event_types=["TRADE"])
        degraded = build_provider_readiness_manifest_v2(provider="mexc-public", requested_panel=self.panel, observed_states=[{"symbol": "BTC_USDT", "venue_symbol": "BTC_USDT", "subscription_acknowledged": False, "snapshot_observed": True, "observed_streams": ["depth", "trade"]}], capability_contract=self.capability, evidence_sources=[self.preflight_source], readiness_policy=readiness_policy(), mode="DEGRADED_DIAGNOSTIC")
        self.assertEqual(degraded["outcome"], "DIAGNOSTIC_ONLY")
        self.assertEqual(degraded["attributes"]["panel_status"], "degraded")

    def test_cli_writes_only_new_output_and_dispatcher_discovers_module(self):
        self.assertIn("orderflow-ingestion-v2", available_commands())
        request = {"capacity": 1, "required_symbols": ["BTC_USDT"], "frames": [{"payload": {"symbol": "BTC_USDT", "n": 1}, "received_at_utc": "2025-01-01T00:00:00Z", "received_monotonic_ns": 1}, {"payload": {"symbol": "BTC_USDT", "n": 2}, "received_at_utc": "2025-01-01T00:00:00Z", "received_monotonic_ns": 2}]}
        input_path = self.root / "simulate-input.json"
        output_path = self.root / "simulate-output.json"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        self.assertEqual(cli.main(["simulate", "--input", str(input_path), "--output", str(output_path)]), 1)
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "INCOMPLETE_OVERFLOW")
        self.assertEqual(cli.main(["simulate", "--input", str(input_path), "--output", str(output_path)]), 2)
        capability_input = self.root / "capability-input.json"
        capability_output = self.root / "capability-output.json"
        capability_input.write_text(json.dumps({"capability_path": str(self.capability_path), "source_id": "capability-cli"}), encoding="utf-8")
        self.assertEqual(cli.main(["capability", "--input", str(capability_input), "--output", str(capability_output)]), 0)
        self.assertEqual(json.loads(capability_output.read_text(encoding="utf-8"))["schema"], "orderflow_edge_lab.provider_capability.v2")


if __name__ == "__main__":
    unittest.main()

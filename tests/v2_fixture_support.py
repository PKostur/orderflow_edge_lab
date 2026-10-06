"""Synthetic offline evidence producers; never market/provider verification."""
from pathlib import Path
import json
from orderflow_edge_lab.contracts_v2 import build_file_identity, build_source_record, canonical_json_sha256
from orderflow_edge_lab.ingestion_v2 import (
    build_provider_capability_contract_v2, build_provider_readiness_manifest_v2,
    build_session_terminal_v2,
)


def readiness_policy():
    raw = {"policy_id": "offline-fixture", "max_symbol_idle_seconds": 5.0,
           "required_streams": ["snapshot", "depth", "trade"],
           "require_subscription_ack": True, "allow_degraded_diagnostics": True}
    return {**raw, "policy_sha256": canonical_json_sha256(raw)}


def capability_file(root: Path, interval, symbols):
    path = root / "fixture_capability.json"
    value = {"provider": "fixture-public", "approved_routes": ["https://example.test/market"],
             "event_types": ["SNAPSHOT", "DEPTH", "TRADE"],
             "instrument_mappings": [{"logical_symbol": s, "provider_symbol": s} for s in symbols],
             "historical_interval": interval, "delayed": False, "export_time_zone": "UTC",
             "redistribution_restriction": "synthetic_offline_fixture_only"}
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def complete_terminal(root: Path, interval, symbols):
    capability = build_provider_capability_contract_v2(capability_file(root, interval, symbols), source_id="capability")
    evidence = root / "terminal_evidence.json"
    evidence.write_text('{"synthetic_offline":true}\n', encoding="utf-8")
    sources = [build_source_record("terminal_evidence", build_file_identity(evidence))]
    panel = [{"symbol": s, "venue_symbol": s} for s in symbols]
    policy = readiness_policy()
    readiness = build_provider_readiness_manifest_v2(provider="fixture-public", requested_panel=panel,
        observed_states=[{**row, "subscription_acknowledged": True, "snapshot_observed": True,
                          "observed_streams": ["depth", "trade"]} for row in panel],
        capability_contract=capability, evidence_sources=sources, readiness_policy=policy, mode="STRICT")
    return build_session_terminal_v2(requested_interval=interval,
        symbol_states=[{**row, "subscription_acknowledged": True, "snapshot_observed": True,
                       "depth_observed": True, "trade_observed": True,
                       "last_receipt_monotonic_ns": 1_000_000_000, "last_receipt_at_utc": interval["end_utc"],
                       "connection_epoch": 0, "feed_silence_events": []} for row in panel],
        evidence_sources=sources, readiness_manifest=readiness, readiness_policy=policy,
        terminal_at_utc=interval["end_utc"], terminal_monotonic_ns=1_000_000_000,
        terminal_cause="REQUESTED_INTERVAL_COMPLETE", telemetry={"overflow_count": 0})

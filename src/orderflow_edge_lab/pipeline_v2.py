"""Offline opt-in cross-stage producers. No collectors, watches or order routes.

All inputs are already acquired caller snapshots. Completion describes locally
validated artifacts; it never attests external storage, entitlement or truth.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from .contracts_v2 import (
    OPEN_CLOSED, build_canonical_source_set, build_coverage_result,
    build_file_identity, build_manifest_result, build_source_record,
    canonical_json_bytes, canonical_json_sha256,
    missing_value, non_authority_claims, observed_value, source_sets_equal,
    validate_utc_interval,
)
from .data_integrity_v2 import (
    CapturePairWriterV2, load_capture_pair_manifest_v2, replay_eligibility_v2,
    require_prospective_aggregation_eligible_v2, verify_capture_pair_v2,
)
from .ingestion_v2 import (
    BoundedOrderedCaptureV2, build_provider_capability_contract_v2,
    build_provider_readiness_manifest_v2, build_session_terminal_v2,
    capture_pair_input_v2,
)


class PipelineV2Error(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineV2Error("input must be a JSON object")
    return value


def _write(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(canonical_json_bytes(value) + b"\n")


def _seal(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {**value, key: canonical_json_sha256(value)}


def build_capture_pair_binding_v2(
    pair: Mapping[str, Any], raw_path: str | Path, feature_path: str | Path,
    *, eligibility_policy: Mapping[str, Any], quality_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Actual producer for the stage-03 binding, with local checks before output."""
    verified = verify_capture_pair_v2(pair, raw_path, feature_path)
    decision = require_prospective_aggregation_eligible_v2(replay_eligibility_v2(
        pair, raw_path, feature_path, eligibility_policy=eligibility_policy,
        quality_report_path=quality_report_path,
    ))
    if not source_sets_equal(verified["source_set"], pair["source_set"]):
        raise PipelineV2Error("pair verification source-set substitution")
    unsigned = {
        "schema": "orderflow_edge_lab.capture_pair_binding.v2",
        "analysis": "capture_pair_replay_eligibility",
        "source_set": decision["source_set"], "outcome": "COMPLETE",
        "replay_status": "REPLAY_ELIGIBLE",
        "capture_start_utc": pair["capture_interval"]["start_utc"],
        "capture_end_utc": pair["capture_interval"]["end_utc"],
        "non_authority_claims": non_authority_claims(),
    }
    return _seal(unsigned, "capture_pair_sha256")


def capture_offline_v2(request_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Execute raw-first queue and pair publication for saved normalized frames.

    This is NOT a network recorder. Normalized payloads must preserve original
    event type, receipt ns and depth_applied. The input file is the terminal's
    exact local evidence source. Any overflow/silence remains ineligible.
    """
    spec = _load(request_path)
    required = {"capture_id", "provider", "capability_path", "requested_panel",
                "readiness_policy", "requested_interval", "capacity", "frames",
                "terminal_at_utc", "terminal_monotonic_ns"}
    if set(spec) != required:
        raise PipelineV2Error("capture-offline request has unsupported shape")
    capture_id = spec["capture_id"]
    if not isinstance(capture_id, str) or Path(capture_id).name != capture_id or capture_id in {"", ".", ".."}:
        raise PipelineV2Error("capture_id must be a safe basename")
    interval = validate_utc_interval(spec["requested_interval"])
    sources = [build_source_record("offline_capture_input", build_file_identity(request_path))]
    capability = build_provider_capability_contract_v2(spec["capability_path"], source_id="capability")
    panel = spec["requested_panel"]
    if not isinstance(panel, list) or not panel:
        raise PipelineV2Error("requested_panel must be a nonempty array")
    states = {row["symbol"]: {
        "symbol": row["symbol"], "venue_symbol": row["venue_symbol"],
        "subscription_acknowledged": False, "snapshot_observed": False,
        "depth_observed": False, "trade_observed": False,
        "last_receipt_monotonic_ns": 0, "last_receipt_at_utc": interval["start_utc"],
        "connection_epoch": 0, "feed_silence_events": [],
    } for row in panel}
    if len(states) != len(panel):
        raise PipelineV2Error("requested_panel has duplicate symbols")
    raw_session = {"record_type": "session", "schema_version": 3,
                   "capture_id": capture_id, "symbols": sorted(states)}
    feature_session = {**raw_session, "record_type": "feature_session"}
    root = Path(output_dir)
    with CapturePairWriterV2(root, capture_id=capture_id,
            raw_file_name=f"{capture_id}_raw_v3.jsonl", feature_file_name=f"{capture_id}_features_v3.jsonl",
            capture_interval=interval, raw_session=raw_session, feature_session=feature_session,
            policy_sha256=spec["readiness_policy"]["policy_sha256"]) as writer:
        receiver = BoundedOrderedCaptureV2(capacity=spec["capacity"], required_symbols=sorted(states), raw_event_sink=writer.write_raw)
        frames = spec["frames"]
        if not isinstance(frames, list):
            raise PipelineV2Error("frames must be an array")
        last_mono = 0
        for frame in frames:
            if not isinstance(frame, dict) or set(frame) != {"payload", "received_at_utc", "received_monotonic_ns"}:
                raise PipelineV2Error("frame has unsupported shape")
            payload = frame["payload"]
            symbol = payload.get("symbol")
            if symbol not in states or type(payload.get("received_at_ns")) is not int or payload["received_at_ns"] < 0:
                raise PipelineV2Error("normalized frame requires a mapped symbol and original receipt ns")
            receiver.receive(payload, received_at_utc=frame["received_at_utc"], received_monotonic_ns=frame["received_monotonic_ns"])
            state = states[symbol]
            state["last_receipt_monotonic_ns"] = frame["received_monotonic_ns"]
            state["last_receipt_at_utc"] = frame["received_at_utc"]
            last_mono = frame["received_monotonic_ns"]
            kind = payload.get("event_type")
            if kind == "subscription_ack": state["subscription_acknowledged"] = True
            elif kind == "snapshot": state["snapshot_observed"] = True
            elif kind == "depth" and payload.get("depth_applied") is True: state["depth_observed"] = True
            elif kind == "trade": state["trade_observed"] = True
        def process(payload: Mapping[str, Any]) -> None:
            if payload.get("event_type") in {"snapshot", "depth", "trade"}:
                writer.write_feature({**payload, "record_type": "feature"})
        while receiver.process_next(process, processed_monotonic_ns=last_mono):
            pass
        terminal_mono = spec["terminal_monotonic_ns"]
        if type(terminal_mono) is not int or terminal_mono < last_mono:
            raise PipelineV2Error("terminal monotonic time must not precede receipt/processing")
        for event in receiver.check_liveness(now_monotonic_ns=terminal_mono,
                max_symbol_idle_seconds=spec["readiness_policy"]["max_symbol_idle_seconds"]):
            states[event["symbol"]]["feed_silence_events"].append(event)
        readiness = build_provider_readiness_manifest_v2(provider=spec["provider"], requested_panel=panel,
            observed_states=[{"symbol": row["symbol"], "venue_symbol": row["venue_symbol"],
                              "subscription_acknowledged": row["subscription_acknowledged"],
                              "snapshot_observed": row["snapshot_observed"],
                              "observed_streams": [kind for kind in ("depth", "trade") if row[kind+"_observed"]]}
                             for row in states.values()],
            capability_contract=capability, evidence_sources=sources,
            readiness_policy=spec["readiness_policy"], mode="STRICT")
        telemetry = receiver.telemetry()
        terminal = build_session_terminal_v2(requested_interval=interval, symbol_states=list(states.values()),
            evidence_sources=sources, readiness_manifest=readiness, readiness_policy=spec["readiness_policy"],
            terminal_at_utc=spec["terminal_at_utc"], terminal_monotonic_ns=terminal_mono,
            terminal_cause="QUEUE_OVERFLOW" if telemetry["overflow_count"] else "REQUESTED_INTERVAL_COMPLETE", telemetry=telemetry)
        facts = capture_pair_input_v2(terminal)
        ended = int(datetime.fromisoformat(spec["terminal_at_utc"].replace("Z", "+00:00")).timestamp() * 1_000_000_000)
        summary = {"record_type": "session_summary", "capture_id": capture_id, "ended_at_ns": ended,
                   "session_terminal_v2": terminal}
        pair = writer.finalize(summary, summary)
    return {"schema": "orderflow_edge_lab.offline_capture_publication.v2",
            "status": terminal["outcome"], "pair": pair, "terminal_facts": facts,
            "raw_path": str(writer.raw_path), "feature_path": str(writer.feature_path),
            "manifest_path": str(writer.manifest_path), "non_authority_claims": non_authority_claims()}


def scan_capture_v2(*, pair_path: str | Path, raw_path: str | Path, feature_path: str | Path,
                    eligibility_policy: Mapping[str, Any], feature_policy: Mapping[str, Any],
                    symbol: str, context_symbol: str, quality_report_path: str | Path | None = None) -> dict[str, Any]:
    from .features_v2 import scan_market_state_v2
    pair = load_capture_pair_manifest_v2(pair_path)
    binding = build_capture_pair_binding_v2(pair, raw_path, feature_path,
        eligibility_policy=eligibility_policy, quality_report_path=quality_report_path)
    events = [json.loads(line) for line in Path(feature_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [row for row in events if row.get("record_type") == "feature"]
    return scan_market_state_v2(events, source_set=binding["source_set"], capture_pair=binding,
                               policy=feature_policy, symbol=symbol, context_symbol=context_symbol)


def export_discovery_validation_v2(ledger: Mapping[str, Any], closure: Mapping[str, Any], graduation: Mapping[str, Any], *, interval: Mapping[str, Any]) -> dict[str, Any]:
    """Produce stage-06 generic manifests from actual stage-04 verified outputs."""
    from .discovery_governance_v2 import verify_family_closure_v2, verify_graduation_binding_v2
    family = verify_family_closure_v2(closure, family_ledger=ledger)
    graduate = verify_graduation_binding_v2(graduation)
    if (family["closure_status"] != "CLOSED_VERIFIED" or graduate["graduation_status"] != "ELIGIBLE"
            or graduate["family_closure_sha256"] != family["closure_sha256"]
            or graduate["family_ledger_sha256"] != family["family_ledger_sha256"]
            or graduate["candidate_identity"] != family["selected_candidate_identity"]
            or not source_sets_equal(graduate["source_set"], family["source_set"])):
        raise PipelineV2Error("discovery export requires exact closed family and eligible matched graduation")
    coverage = build_coverage_result("discovery_closed_family_members_v2", interval,
        [{"observation_id": row["candidate_identity"]["candidate_id"], "observation": observed_value(1)} for row in family["members"]])
    return {"discovery_family_manifest": build_manifest_result("discovery_family_v2", family["source_set"], "COMPLETE",
                coverage=coverage, policy_sha256=family["closure_policy_sha256"], attributes={"family_closure_sha256": family["closure_sha256"], "family_ledger_sha256": family["family_ledger_sha256"]}),
            "graduation_binding": build_manifest_result("graduation_binding_v2", graduate["source_set"], "COMPLETE",
                coverage=coverage, policy_sha256=graduate["graduation_policy"]["graduation_policy_sha256"], attributes={"graduation_sha256": graduate["graduation_sha256"], "candidate_id": graduate["candidate_identity"]["candidate_id"], "terminal_state": graduate["terminal_state"]}),
            "non_authority_claims": non_authority_claims()}


def paper_from_economics_v2(replay_inputs: Mapping[str, Any], qualifications: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Consume actual stage-05 datasets; exact funding rates/schedules/marks bind.

    Only venue-consistent complete, OPEN_CLOSED qualified datasets may feed this
    composition. No unknown settlement is filled with zero. The paper module
    independently checks every held interval and duplicates before calculation.
    """
    from .economics_v2 import build_economics_qualification_v2
    from .paper_replay_v2 import build_replay_bundle_v2
    expected_symbols = {row["symbol"] for row in replay_inputs["targets"]}
    by_symbol: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    for qualification in qualifications:
        rebuilt = build_economics_qualification_v2(qualification["price_dataset"], qualification["funding_dataset"],
            qualification_policy_sha256=qualification["qualification_policy_sha256"])
        if rebuilt != qualification or rebuilt["qualification_status"] != "venue_consistent_complete":
            raise PipelineV2Error("paper economics input is mismatched or incomplete")
        symbol = rebuilt["symbol"]
        if symbol in by_symbol:
            raise PipelineV2Error("duplicate paper economics symbol")
        if rebuilt["funding_dataset"]["settlement_interval_convention"] != OPEN_CLOSED:
            raise PipelineV2Error("paper funding requires OPEN_CLOSED settlement semantics")
        by_symbol[symbol] = rebuilt
        for record in rebuilt["source_set"]["sources"]:
            sources.append({**record, "source_id": symbol+":"+record["source_id"]})
    if set(by_symbol) != expected_symbols:
        raise PipelineV2Error("paper economics symbol universe does not match targets exactly")
    for symbol, qualification in by_symbol.items():
        dataset = qualification["funding_dataset"]
        schedule = dataset["settlement_schedule"]
        # A documented portable producer shape, not an inferred venue cadence.
        if set(schedule) != {"expected_settlements"} or not isinstance(schedule["expected_settlements"], list):
            raise PipelineV2Error("paper bridge requires explicit expected_settlements schedule")
        expected = sorted(row["timestamp"] for row in replay_inputs["funding_expectations"] if row["symbol"] == symbol)
        if sorted(row["timestamp_utc"] for row in schedule["expected_settlements"]) != expected:
            raise PipelineV2Error("paper expected funding schedule differs from economics")
        values = {row["observation_id"]: row["observation"] for row in dataset["coverage"]["observations"]}
        for row in schedule["expected_settlements"]:
            observation = values.get(row["observation_id"], missing_value("schedule_missing_from_coverage"))
            matches = [item for item in replay_inputs["funding"] if item["symbol"] == symbol and item["timestamp"] == row["timestamp_utc"]]
            if observation["availability"] != "OBSERVED" or len(matches) != 1 or matches[0]["rate"] != observation["value"]:
                raise PipelineV2Error("paper funding rows do not match qualified observed values")
        price_values = {row["observation_id"]: row["observation"] for row in qualification["price_dataset"]["coverage"]["observations"]}
        for row in replay_inputs["marks"]:
            if row["symbol"] != symbol: continue
            observed = price_values.get(row["timestamp"])
            if observed is None or observed["availability"] != "OBSERVED" or row["price"] != observed["value"]:
                raise PipelineV2Error("paper marks do not match qualified price coverage")
    bundle = build_replay_bundle_v2(replay_inputs, build_canonical_source_set(sources))
    return _seal({"schema": "orderflow_edge_lab.economics_paper_composition.v2", "bundle": bundle,
                  "economics_qualification_sha256": {key: value["qualification_sha256"] for key, value in sorted(by_symbol.items())},
                  "non_authority_claims": non_authority_claims()}, "composition_sha256")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline v2 cross-stage producers; no live activation or collectors")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture-offline")
    capture.add_argument("--request", required=True); capture.add_argument("--output-dir", required=True)
    scan = sub.add_parser("scan-capture")
    for name in ("pair", "raw", "features", "eligibility-policy", "feature-policy", "symbol", "context-symbol", "output"):
        scan.add_argument("--"+name, required=True)
    scan.add_argument("--quality-report")
    for name in ("paper-from-economics", "discovery-validation-export"):
        command = sub.add_parser(name); command.add_argument("--request", required=True); command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture-offline":
            result = capture_offline_v2(args.request, args.output_dir)
        elif args.command == "scan-capture":
            result = scan_capture_v2(pair_path=args.pair, raw_path=args.raw, feature_path=args.features,
                eligibility_policy=_load(args.eligibility_policy), feature_policy=_load(args.feature_policy),
                symbol=args.symbol, context_symbol=args.context_symbol, quality_report_path=args.quality_report)
            _write(args.output, result)
        elif args.command == "paper-from-economics":
            request = _load(args.request)
            result = paper_from_economics_v2(request["replay_inputs"], request["qualifications"]); _write(args.output, result)
        else:
            request = _load(args.request)
            result = export_discovery_validation_v2(request["ledger"], request["closure"], request["graduation"], interval=request["interval"]); _write(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "INVALID_OR_INELIGIBLE", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

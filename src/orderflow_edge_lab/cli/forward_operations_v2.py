"""Offline CLI for the opt-in v2 forward-operations overlays.

This command consumes local JSON/files only.  It does not call GitHub, fetch
market data, alter reports, create schedules, dispatch workflows, or trade.
Outputs are exclusive-create so an existing checkpoint/result cannot be silently
replaced by a later invocation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from orderflow_edge_lab.contracts_v2 import build_file_identity
from orderflow_edge_lab.forward_operations_v2 import (
    ForwardOperationsError,
    assess_forward_operations_heartbeat_v2,
    audit_retention_producer_contract_v2,
    build_forward_operations_registry_v2,
    build_retention_inventory_v2,
    build_source_checkpoint_v2,
    build_universe_availability_ledger_v2,
    load_json_object,
)


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n")
        handle.flush()


def _emit(payload: dict[str, Any], output: str | None) -> None:
    if output:
        _write_exclusive(Path(output), payload)
    print(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False))


def _source_identities(clock: str, template: str) -> dict[str, Any]:
    return {
        "clock_config": build_file_identity(clock, logical_name="prospective_review_clock"),
        "operational_template": build_file_identity(template, logical_name="forward_operations_v2_template"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build/validate local v2 forward-operations retention, availability, source-checkpoint, "
            "and heartbeat overlays. No network, collector, scheduler, dispatch, verdict, or trading path."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("retention-inventory", help="derive the all-open-watch retention inventory from a frozen clock")
    inventory.add_argument("--clock", required=True, help="frozen prospective clock JSON")
    inventory.add_argument("--overlay", required=True, help="caller-declared v2 retention overlay JSON")
    inventory.add_argument("--generated-at", required=True, help="offset-aware generation timestamp")
    inventory.add_argument("--output", help="exclusive-create inventory JSON path")

    availability = commands.add_parser("availability-ledger", help="write a frozen-universe availability overlay from local JSON input")
    availability.add_argument("--input", required=True, help="availability ledger input JSON")
    availability.add_argument("--output", help="exclusive-create ledger JSON path")

    checkpoint = commands.add_parser("source-checkpoint", help="write one append-only forward source checkpoint from local JSON input")
    checkpoint.add_argument("--input", required=True, help="source checkpoint input JSON")
    checkpoint.add_argument("--output", help="exclusive-create checkpoint JSON path")

    registry = commands.add_parser("registry", help="validate one forward operations row per nonterminal clock watch")
    registry.add_argument("--clock", required=True, help="frozen prospective clock JSON")
    registry.add_argument("--template", required=True, help="caller-declared registry template JSON")
    registry.add_argument("--generated-at", required=True, help="offset-aware generation timestamp")
    registry.add_argument("--output", help="exclusive-create registry JSON path")

    heartbeat = commands.add_parser("heartbeat", help="check local watch-child heartbeat observations; never dispatches")
    heartbeat.add_argument("--registry", required=True, help="registry JSON emitted by the registry command")
    heartbeat.add_argument("--observations", required=True, help="JSON array of local child observation facts")
    heartbeat.add_argument("--now", required=True, help="offset-aware check timestamp")
    heartbeat.add_argument("--output", help="exclusive-create heartbeat JSON path")

    contract = commands.add_parser("producer-contract", help="audit local workflow declarations against an emitted retention inventory")
    contract.add_argument("--inventory", required=True, help="retention inventory JSON emitted by retention-inventory")
    contract.add_argument("--repo-root", default=".", help="repository root containing named producer workflows")
    contract.add_argument("--output", help="exclusive-create producer-contract JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "retention-inventory":
            payload = build_retention_inventory_v2(
                load_json_object(args.clock),
                load_json_object(args.overlay),
                source_identities=_source_identities(args.clock, args.overlay),
                generated_at_utc=args.generated_at,
            )
            _emit(payload, args.output)
            return 0
        if args.command == "availability-ledger":
            payload = build_universe_availability_ledger_v2(**load_json_object(args.input))
            _emit(payload, args.output)
            return 0
        if args.command == "source-checkpoint":
            payload = build_source_checkpoint_v2(**load_json_object(args.input))
            _emit(payload, args.output)
            return 0
        if args.command == "registry":
            payload = build_forward_operations_registry_v2(
                load_json_object(args.clock),
                load_json_object(args.template),
                source_identities=_source_identities(args.clock, args.template),
                generated_at_utc=args.generated_at,
            )
            _emit(payload, args.output)
            return 0
        if args.command == "heartbeat":
            observations = json.loads(Path(args.observations).read_text(encoding="utf-8"))
            if not isinstance(observations, list):
                raise ForwardOperationsError("observations JSON must be an array")
            payload = assess_forward_operations_heartbeat_v2(load_json_object(args.registry), observations, now_utc=args.now)
            _emit(payload, args.output)
            return 1 if payload["operational_check_conclusion"] == "FAIL" else 0
        if args.command == "producer-contract":
            payload = audit_retention_producer_contract_v2(load_json_object(args.inventory), repo_root=Path(args.repo_root))
            _emit(payload, args.output)
            return 0 if payload["contract_ok"] else 1
    except (OSError, ValueError, TypeError, KeyError, ForwardOperationsError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

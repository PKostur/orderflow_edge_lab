"""Offline dispatcher for prospective ingestion-v2 evidence construction.

This command reads caller-provided local JSON and raw-page paths only.  It makes
no HTTP/WebSocket connection, does not start a collector, and never overwrites
an output artifact.  Exit 0 means the resulting object is complete/admissible;
exit 1 means a valid but partial/degraded/overflow/data-gap result was written;
exit 2 means malformed input or a validation error.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence

from orderflow_edge_lab.ingestion_v2 import (
    IngestionV2Error,
    build_capture_simulation_v2,
    build_historical_acquisition_manifest_v2,
    build_provider_capability_contract_v2,
    build_provider_readiness_manifest_v2,
    build_session_terminal_v2,
    capture_pair_input_v2,
    funding_economics_admissibility_v2,
)


def _read_object(path: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionV2Error(f"cannot read JSON object from {path}") from exc
    if not isinstance(parsed, Mapping):
        raise IngestionV2Error("input JSON must be an object")
    return parsed


def _write_new(path: str, result: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
    except FileExistsError as exc:
        raise IngestionV2Error(f"refusing to overwrite existing v2 output: {target}") from exc


def _result_status(result: Mapping[str, Any]) -> tuple[int, str]:
    """Return a process exit/result label without promoting non-authority facts."""

    if "outcome" in result:
        return (0, "COMPLETE") if result.get("outcome") == "COMPLETE" else (1, "PARTIAL_OR_INELIGIBLE")
    if "funding_economics_admissible" in result:
        return (0, "ADMISSIBLE") if result.get("funding_economics_admissible") is True else (1, "PARTIAL_OR_INELIGIBLE")
    if "status" in result:
        return (0, "PROCESSED") if result.get("status") in {"PROCESSED", "WITHIN_DECLARED_SCOPE"} else (1, "PARTIAL_OR_INELIGIBLE")
    if result.get("schema") in {
        "orderflow_edge_lab.provider_capability.v2",
        "orderflow_edge_lab.capture_pair_input.v2",
    }:
        return 0, "DECLARED_NOT_VERIFIED"
    return 1, "PARTIAL_OR_INELIGIBLE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and validate opt-in, offline Orderflow Edge Lab ingestion-v2 artifacts."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("terminal", "build a completion-bound session terminal from local evidence"),
        ("historical", "build a page-provenance expected-grid historical acquisition manifest"),
        ("readiness", "build a provider/panel preflight readiness manifest"),
        ("capability", "hash-bind a nonsecret provider capability artifact"),
        ("funding-admissibility", "fail closed before funding-inclusive economics"),
        ("capture-pair-input", "emit the terminal facts consumable by capture-pair validation"),
        ("simulate", "exercise the bounded receiver/ordered processor with offline frames"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--input", required=True, help="caller-supplied JSON object")
        command.add_argument("--output", required=True, help="new JSON output path; existing files are refused")
    return parser


def _dispatch(command: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if command == "terminal":
        return build_session_terminal_v2(**payload)
    if command == "historical":
        return build_historical_acquisition_manifest_v2(**payload)
    if command == "readiness":
        return build_provider_readiness_manifest_v2(**payload)
    if command == "capability":
        return build_provider_capability_contract_v2(payload.get("capability_path"), source_id=payload.get("source_id"))
    if command == "funding-admissibility":
        return funding_economics_admissibility_v2(**payload)
    if command == "capture-pair-input":
        return capture_pair_input_v2(payload.get("terminal"))
    if command == "simulate":
        return build_capture_simulation_v2(payload)
    raise AssertionError("unreachable command")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = _read_object(args.input)
        result = _dispatch(args.command, payload)
        _write_new(args.output, result)
    except (IngestionV2Error, TypeError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    exit_code, status = _result_status(result)
    print(json.dumps({"status": status, "output": str(Path(args.output)), "command": args.command}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

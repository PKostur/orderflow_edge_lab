"""Offline CLI for prospective engineering-governance v2 contracts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from orderflow_edge_lab.governance_v2 import (
    GovernanceV2Error,
    build_control_plane_status_v2,
    build_governance_map_v2,
    build_release_profile_v2,
    load_control_plane_contract_v2,
    load_policy_config,
    render_governance_map_markdown,
    verify_control_plane_status_v2,
    verify_release_profile_v2,
)


def _load_object(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GovernanceV2Error("invalid_json_object", f"{path} must contain a JSON object")
    return value


def _write(path: str, value: MappingLike) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


MappingLike = dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local, read-only Orderflow Edge Lab governance v2 checks; no data collection, schedules, storage service, or order activity occurs."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    policy = sub.add_parser("validate-policy", help="validate a prospective multi-agent v2 policy")
    policy.add_argument("--config", default="config/multi_agents_v2.json")
    profile = sub.add_parser("release-profile", help="write a deterministic advisory or release governance profile")
    profile.add_argument("--root", default=".")
    profile.add_argument("--config", default="config/multi_agents_v2.json")
    profile.add_argument("--profile", choices=("advisory", "release"), default="release")
    profile.add_argument("--output", required=True)
    profile.add_argument("--strict", action="store_true", help="return nonzero unless the release profile is reviewable")
    gov_map = sub.add_parser("governance-map", help="generate the versioned governance map from a validated policy")
    gov_map.add_argument("--config", default="config/multi_agents_v2.json")
    gov_map.add_argument("--json-output", required=True)
    gov_map.add_argument("--markdown-output", required=True)
    status = sub.add_parser("control-plane-status", help="compose a contract-bound, read-only v2 status")
    status.add_argument("--contract", default="config/research_control_plane_v2.json")
    status.add_argument("--shadow-report", required=True)
    status.add_argument("--decision", required=True)
    status.add_argument("--action", required=True)
    status.add_argument("--operational", required=True)
    status.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-policy":
            result = load_policy_config(args.config)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0
        if args.command == "release-profile":
            result = build_release_profile_v2(args.root, load_policy_config(args.config), profile=args.profile)
            if not verify_release_profile_v2(result):
                raise GovernanceV2Error("profile_hash_failed", "generated release profile did not verify")
            _write(args.output, result)
            print(json.dumps({"status": result["release_manager"]["status"], "profile": result["execution_profile"],
                              "checks_skipped_required": result["checks_skipped_required"], "report_sha256": result["report_sha256"],
                              "output": args.output}, sort_keys=True))
            return 0 if not args.strict or result["release_manager"]["status"] == "reviewable" else 2
        if args.command == "governance-map":
            result = build_governance_map_v2(load_policy_config(args.config))
            _write(args.json_output, result)
            markdown_target = Path(args.markdown_output)
            markdown_target.parent.mkdir(parents=True, exist_ok=True)
            markdown_target.write_text(render_governance_map_markdown(result), encoding="utf-8")
            print(json.dumps({"status": "generated", "map_sha256": result["map_sha256"], "json_output": args.json_output,
                              "markdown_output": args.markdown_output}, sort_keys=True))
            return 0
        if args.command == "control-plane-status":
            result = build_control_plane_status_v2(_load_object(args.shadow_report), _load_object(args.decision),
                                                    _load_object(args.action), _load_object(args.operational),
                                                    load_control_plane_contract_v2(args.contract))
            if not verify_control_plane_status_v2(result):
                raise GovernanceV2Error("status_hash_failed", "generated control-plane status did not verify")
            _write(args.output, result)
            print(json.dumps({"status": "generated", "report_sha256": result["report_sha256"], "output": args.output}, sort_keys=True))
            return 0
        raise AssertionError("unreachable")
    except (GovernanceV2Error, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

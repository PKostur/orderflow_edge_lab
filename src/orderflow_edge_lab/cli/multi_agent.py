from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.multi_agent import run_multi_agent, verify_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local multi-agent hardening control plane.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--config", default="config/multi_agents.json", help="Agent configuration path")
    parser.add_argument("--output", default="artifacts/multi_agent_report.json", help="Output report path")
    parser.add_argument("--skip-heavy", action="store_true", help="Skip compile/test/deployment subprocess checks")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when the release manager is blocked")
    parser.add_argument("--max-workers", type=int, default=7)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_multi_agent(
        args.root,
        args.config,
        run_commands=not args.skip_heavy,
        max_workers=args.max_workers,
    )
    if not verify_report(report):
        raise RuntimeError("generated report failed manifest verification")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manager = report["release_manager"]
    print(json.dumps({
        "status": manager["status"],
        "errors": manager["error_count"],
        "warnings": manager["warning_count"],
        "manifest_sha256": report["manifest_sha256"],
        "output": str(output),
    }, indent=2, sort_keys=True))
    return 2 if args.strict and manager["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

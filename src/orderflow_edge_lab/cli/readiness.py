from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.reliability import deployment_readiness, write_readiness_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed operational readiness check for the paper execution engine."
    )
    parser.add_argument("--state", default="runtime/paper_state.json", help="Execution state JSON path")
    parser.add_argument("--journal", default="runtime/paper_journal.jsonl", help="Execution journal JSONL path")
    parser.add_argument("--validation-manifest", default=None,
                        help="Optional future-only validation manifest. It is reported but never treated as proof of edge.")
    parser.add_argument("--output", default=None, help="Optional path for a JSON readiness report")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = deployment_readiness(
        Path(args.state),
        Path(args.journal),
        validation_manifest=Path(args.validation_manifest) if args.validation_manifest else None,
    )
    if args.output:
        write_readiness_report(report, Path(args.output))
    print(json.dumps(report.as_dict(), sort_keys=True, indent=2))
    return 0 if report.ready_for_paper else 2


if __name__ == "__main__":
    raise SystemExit(main())

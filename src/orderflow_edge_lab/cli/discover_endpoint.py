"""CLI for credential-free DeepCharts/dxFeed endpoint discovery."""
from __future__ import annotations

import argparse
import json
import sys

from orderflow_edge_lab.endpoint_discovery import (
    DEFAULT_PROCESS_NAMES,
    discover_windows_endpoints,
    discovery_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect established TCP peers used by DeepCharts/Volumetrica without reading credentials."
    )
    parser.add_argument(
        "--process-name",
        action="append",
        dest="process_names",
        help="Process name to inspect. Repeat for multiple names. Defaults to known DeepCharts/Volumetrica processes.",
    )
    parser.add_argument("--output", help="Optional JSON report path. Standard output is always emitted.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    process_names = tuple(args.process_names) if args.process_names else DEFAULT_PROCESS_NAMES
    try:
        observations = discover_windows_endpoints(process_names)
        report = discovery_report(observations)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2

    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
    return 0 if observations else 1


if __name__ == "__main__":
    raise SystemExit(main())

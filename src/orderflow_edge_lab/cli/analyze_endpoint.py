"""CLI for fail-closed analysis of DeepCharts endpoint watcher reports."""
from __future__ import annotations

import argparse
import json
import sys

from orderflow_edge_lab.endpoint_capture import EndpointCaptureError, analyze_capture_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and rank a DeepCharts/dxFeed endpoint watcher report without "
            "inferring external API authorization."
        )
    )
    parser.add_argument("capture", help="Path to deepcharts_dxfeed_endpoints.json")
    parser.add_argument("--output", help="Optional JSON analysis path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = analyze_capture_file(args.capture)
    except EndpointCaptureError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
    return 0 if report["candidate_is_unambiguous"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

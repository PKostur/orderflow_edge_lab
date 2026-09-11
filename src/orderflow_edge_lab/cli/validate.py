#!/usr/bin/env python3
"""Audit local observations against frozen candidates, without edge certification."""
import argparse
import json
from pathlib import Path

from orderflow_edge_lab.validation import build_validation_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="config/candidates.json")
    parser.add_argument("--observations", required=True, help="Chronological JSONL observations")
    parser.add_argument("--source-data", action="append", required=True,
                        help="Raw market-data export referenced by source_provenance; repeat for multiple files")
    parser.add_argument("--observed-through", required=True, help="Audited UTC coverage end")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        output = Path(args.output)
        protected = {Path(args.registry).resolve(), Path(args.observations).resolve(),
                     *(Path(path).resolve() for path in args.source_data)}
        if output.resolve() in protected:
            raise ValueError("output must not overwrite inputs")
        report = build_validation_report(args.registry, args.observations,
                                         observed_through=args.observed_through,
                                         source_files=args.source_data)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite an earlier report; immutable artifacts preserve audit history.
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "deployment_eligible": False}))
        return 2
    print(json.dumps({"status": "audit_written", "output": str(output), "deployment_eligible": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

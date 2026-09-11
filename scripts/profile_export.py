#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.data_lineage import profile_csv_export


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a local integrity and structure manifest for a DeepCharts/dxFeed CSV export."
    )
    parser.add_argument("source", help="CSV export to profile")
    parser.add_argument("--output", required=True, help="New JSON manifest path; existing files are not overwritten")
    parser.add_argument("--delimiter", default=",", help="Single-character CSV delimiter")
    parser.add_argument("--timestamp-column")
    parser.add_argument("--symbol-column")
    args = parser.parse_args()

    manifest = profile_csv_export(
        args.source,
        delimiter=args.delimiter,
        timestamp_column=args.timestamp_column,
        symbol_column=args.symbol_column,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({
        "output": str(output),
        "sha256": manifest["file"]["sha256"],
        "rows": manifest["csv"]["row_count"],
        "timestamp_parse_errors": manifest["timestamps"]["parse_error_count"],
        "timestamp_regressions": manifest["timestamps"]["regression_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

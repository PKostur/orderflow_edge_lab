from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.condition_aggregate import aggregate_condition_reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate pre-registered market-condition reports across independent capture batches.")
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = aggregate_condition_reports(args.reports)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

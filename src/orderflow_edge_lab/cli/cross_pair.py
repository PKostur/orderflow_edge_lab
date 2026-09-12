from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.cross_pair import aggregate_cross_pair


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate unchanged cross-pair order-flow transfer tests.")
    parser.add_argument("--screen", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = aggregate_cross_pair(args.screen, args.results_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

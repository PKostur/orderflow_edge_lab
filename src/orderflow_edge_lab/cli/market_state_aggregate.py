from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.market_state_aggregate import aggregate_market_state_reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate regime-research-v1 market-state scans across independent capture batches."
    )
    parser.add_argument("reports", nargs="+", help="Per-batch market-state scan JSON reports")
    parser.add_argument("--minimum-independent-batches", type=int, default=3)
    parser.add_argument("--minimum-positive-batch-fraction", type=float, default=2.0 / 3.0)
    parser.add_argument("--minimum-association-observations", type=int, default=20)
    parser.add_argument("--redundancy-abs-spearman-threshold", type=float, default=0.80)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = aggregate_market_state_reports(
        args.reports,
        minimum_independent_batches=args.minimum_independent_batches,
        minimum_positive_batch_fraction=args.minimum_positive_batch_fraction,
        minimum_association_observations=args.minimum_association_observations,
        redundancy_abs_spearman_threshold=args.redundancy_abs_spearman_threshold,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

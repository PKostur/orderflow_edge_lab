from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.market_state_aggregate_v1_1 import build_v1_1_state_screen


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply the frozen regime-research-v1.1 forward-only cross-batch state screen."
    )
    parser.add_argument("reports", nargs="+", help="Per-batch regime-research-v1 market-state scan reports")
    parser.add_argument("--protocol", default="config/regime_research_v1_1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = build_v1_1_state_screen(args.reports, args.protocol)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "status": report["status"],
        "independent_batch_count": report["independent_batch_count"],
        "eligible_state_association_count": report["eligible_state_association_count"],
        "eligible_incremental_feature_count": report["eligible_incremental_feature_count"],
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

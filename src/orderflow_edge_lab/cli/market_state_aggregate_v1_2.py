from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.market_state_aggregate_v1_2 import build_v1_2_state_screen


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply the frozen regime-research-v1.2 timestamp-based dependence-cluster screen."
    )
    parser.add_argument("reports", nargs="+", help="Per-batch regime-research-v1 market-state scan reports")
    parser.add_argument("--protocol", default="config/regime_research_v1_2.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = build_v1_2_state_screen(args.reports, args.protocol)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    audit = report.get("dependence_audit", {})
    print(json.dumps({
        "output": str(output),
        "status": report["status"],
        "eligible_report_count": audit.get("eligible_report_count", 0),
        "independent_cluster_count": audit.get("independent_cluster_count", 0),
        "collapsed_report_count": audit.get("collapsed_report_count", 0),
        "eligible_state_association_count": report["eligible_state_association_count"],
        "eligible_incremental_feature_count": report["eligible_incremental_feature_count"],
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

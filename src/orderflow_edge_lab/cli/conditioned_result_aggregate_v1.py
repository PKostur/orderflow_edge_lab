from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.conditioned_result_aggregate_v1 import build_conditioned_result_aggregate_v1


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate frozen conditioned experiments by v1.2 dependence cluster.")
    parser.add_argument("conditioned_reports", nargs="+", help="conditioned_experiment_v1.json files")
    parser.add_argument("--state-report", action="append", default=[], dest="state_reports", help="matching regime-research-v1 market_state.json file; repeat for each capture")
    parser.add_argument("--protocol", default="config/conditioned_result_aggregate_v1.json")
    parser.add_argument("--regime-protocol", default="config/regime_research_v1_2.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.state_reports:
        raise SystemExit("at least one --state-report is required")

    report = build_conditioned_result_aggregate_v1(
        args.conditioned_reports,
        args.state_reports,
        protocol_path=args.protocol,
        regime_protocol_path=args.regime_protocol,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "eligible_state_cluster_count": report["dependence"]["eligible_state_cluster_count"],
        "evaluated_representative_cluster_count": report["dependence"]["evaluated_representative_cluster_count"],
        "strategy_cell_count": len(report["strategy_cells"]),
        "direction_control_cell_count": len(report["direction_control_cells"]),
        "risk_path_cell_count": len(report["risk_path_cells"]),
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

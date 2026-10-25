from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.lsk_regime_router import evaluate_lsk_regime_router


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen causal LSK BTC-aligned 30s original/reversed/no-trade regime router."
    )
    parser.add_argument("features", nargs="+")
    parser.add_argument("--protocol", default="config/lsk_regime_router_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = evaluate_lsk_regime_router(args.features, config_path=args.protocol)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "experiment": report["experiment"],
        "sources": len(report["sources"]),
        "results": [
            {
                "fee_bps_round_trip": row["fee_bps_round_trip"],
                "additional_execution_stress_bps_round_trip": row["additional_execution_stress_bps_round_trip"],
                "router": row["router"],
                "route_counts": row["route_counts"],
                "independent_clusters_with_trades": row["independent_clusters_with_trades"],
                "positive_cluster_fraction": row["positive_cluster_fraction"],
                "maximum_single_cluster_positive_profit_share": row["maximum_single_cluster_positive_profit_share"],
                "numeric_forward_screen_would_pass": row["numeric_forward_screen_would_pass"],
            }
            for row in report["results"]
        ],
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

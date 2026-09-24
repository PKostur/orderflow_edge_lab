from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.volatility_state_forward import (
    VolatilityStateForwardError,
    aggregate_forward_clusters,
    evaluate_forward_cluster,
)


def _config(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VolatilityStateForwardError("config must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate frozen volatility-state forward replication.")
    sub = parser.add_subparsers(dest="command", required=True)

    cluster = sub.add_parser("cluster")
    cluster.add_argument("reports", nargs="+")
    cluster.add_argument("--config", required=True)
    cluster.add_argument("--cluster-id", required=True)
    cluster.add_argument("--output", required=True)

    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("clusters", nargs="+")
    aggregate.add_argument("--config", required=True)
    aggregate.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    try:
        cfg = _config(args.config)
        if args.command == "cluster":
            result = evaluate_forward_cluster(args.reports, cfg, cluster_id=args.cluster_id)
        else:
            result = aggregate_forward_clusters(args.clusters, cfg)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "analysis": result["analysis"],
            "watch_id": result["watch_id"],
            "formal_verdict": result["formal_verdict"],
            "summary": {
                k: result.get(k)
                for k in (
                    "cluster_id",
                    "eligible_symbol_count",
                    "cluster_median_primary_spearman",
                    "cluster_positive_symbol_fraction",
                    "eligible_cluster_count",
                    "cluster_median_spearman_median",
                    "positive_cluster_fraction",
                    "review_progress",
                )
                if k in result
            },
        }, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, VolatilityStateForwardError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

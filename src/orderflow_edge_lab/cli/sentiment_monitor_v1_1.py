from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.sentiment_monitor_v1_1 import (
    merge_sentiment_ledgers_v1_1,
    monitor_sentiment_v1_1,
)


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect strategy-aligned deterministic public-headline sentiment v1.1 as observational market-state evidence."
    )
    parser.add_argument("--protocol", default="config/sentiment_monitor_v1_1.json")
    parser.add_argument("--prior-ledger", help="Optional prior v1.1 cumulative sentiment ledger")
    parser.add_argument("--snapshot-output", required=True)
    parser.add_argument("--output", required=True, help="Cumulative v1.1 sentiment ledger output")
    args = parser.parse_args()

    protocol = _load_json(args.protocol)
    snapshot = monitor_sentiment_v1_1(protocol)
    prior = None
    if args.prior_ledger and Path(args.prior_ledger).exists():
        prior = _load_json(args.prior_ledger)
    ledger = merge_sentiment_ledgers_v1_1(prior, snapshot, protocol)

    snapshot_output = Path(args.snapshot_output)
    snapshot_output.parent.mkdir(parents=True, exist_ok=True)
    snapshot_output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    summary = ledger["summary"]
    print(
        json.dumps(
            {
                "snapshot_output": str(snapshot_output),
                "ledger_output": str(output),
                "snapshot_events": snapshot["summary"]["event_count"],
                "cumulative_events": summary["event_count"],
                "readiness_events": summary["readiness_event_count"],
                "non_neutral": summary["non_neutral_event_count"],
                "distinct_sources": summary["distinct_sources"],
                "distinct_conditioning_symbols": summary["distinct_conditioning_symbols"],
                "independent_event_clusters": summary["independent_event_cluster_count"],
                "state_screen_ready": summary["state_screen_ready"],
                "sentiment_is_strategy_filter": ledger["claims"]["sentiment_is_strategy_filter"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

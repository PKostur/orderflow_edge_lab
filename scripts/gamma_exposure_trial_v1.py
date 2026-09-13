from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from orderflow_edge_lab.gamma_exposure import (
    append_comparison_history,
    build_gamma_snapshot,
    fetch_deribit_option_inputs,
    load_json,
    verify_gamma_snapshot,
)


def _write(path: str | Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect forward BTC option gamma exposure and compare with frozen strategy reports.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--snapshot-output", required=True)
    parser.add_argument("--history-output", required=True)
    parser.add_argument("--raw-output", required=True)
    parser.add_argument("--ena-report", required=True)
    parser.add_argument("--trend-report", required=True)
    parser.add_argument("--cross-sectional-report", required=True)
    parser.add_argument("--previous-history")
    args = parser.parse_args()

    protocol = load_json(args.config)
    instruments, summaries = fetch_deribit_option_inputs(str(protocol.get("source", {}).get("currency", "BTC")))
    observed_at_ms = int(time.time() * 1000)
    snapshot = build_gamma_snapshot(instruments, summaries, protocol, observed_at_ms=observed_at_ms)
    if not verify_gamma_snapshot(snapshot):
        raise SystemExit("gamma snapshot manifest verification failed")

    previous = None
    if args.previous_history and Path(args.previous_history).is_file():
        previous = load_json(args.previous_history)

    comparison = append_comparison_history(
        snapshot,
        load_json(args.ena_report),
        load_json(args.trend_report),
        load_json(args.cross_sectional_report),
        protocol,
        previous,
    )

    _write(args.snapshot_output, snapshot)
    _write(args.history_output, comparison)
    _write(
        args.raw_output,
        {
            "observed_at_ms": observed_at_ms,
            "instruments": instruments,
            "summaries": summaries,
        },
    )
    print(json.dumps({
        "snapshot": snapshot["metrics"],
        "comparison_status": comparison["status"],
        "forward_snapshots": comparison["guards"]["observed_forward_snapshots"],
        "completed_outcome_increments": comparison["guards"]["observed_completed_outcome_increments"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

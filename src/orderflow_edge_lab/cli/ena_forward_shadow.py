from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.ena_forward_shadow import (
    build_forward_report,
    load_candidate,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic ENA paper-shadow recomputation for the frozen forward candidate."
    )
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-output", required=True)
    parser.add_argument("--as-of", default=None, help="Optional UTC timestamp for deterministic replay.")
    args = parser.parse_args()

    candidate, candidate_file_sha = load_candidate(args.candidate)
    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    closed_end = as_of.floor("h")

    warmup_start = candidate["forward_protocol"]["indicator_warmup_start_utc"]
    if closed_end <= pd.Timestamp(warmup_start):
        raise SystemExit("as-of time is before required indicator warmup")

    spec = candidate["specification"]
    frame = fetch_mexc_futures_klines(
        str(spec["symbol"]),
        str(spec["interval"]),
        str(warmup_start),
        closed_end.isoformat(),
    )
    source_output = Path(args.source_output)
    source_output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(source_output, index_label="timestamp")
    source_bytes = source_output.read_bytes()

    report = build_forward_report(
        frame,
        candidate,
        candidate_file_sha256=candidate_file_sha,
        source_sha256=sha256(source_bytes).hexdigest(),
        as_of_utc=as_of,
    )
    report["closed_data_end_exclusive_utc"] = closed_end.isoformat()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_id": report["candidate_id"],
                "status": report["status"],
                "completed_forward_trades": report["metrics"]["trades"],
                "open_position": report["open_position"],
                "claims": report["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

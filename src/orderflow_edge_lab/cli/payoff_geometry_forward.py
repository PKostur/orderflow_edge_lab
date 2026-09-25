from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.payoff_geometry_forward import (
    PayoffGeometryForwardError,
    build_payoff_geometry_forward_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run frozen prospective payoff-geometry structural replication."
    )
    parser.add_argument(
        "--config",
        default="config/payoff_geometry_forward_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
        as_of = (
            as_of.tz_localize("UTC")
            if as_of.tzinfo is None
            else as_of.tz_convert("UTC")
        )
        source = config["source"]
        symbols = [str(value) for value in source["symbols"]]
        interval = str(source["interval"])
        warmup = str(source["warmup_start_utc"])
        source_dir = Path(args.source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)
        frames: dict[str, pd.DataFrame] = {}
        hashes: dict[str, str] = {}

        def load(symbol: str) -> tuple[str, pd.DataFrame]:
            return symbol, fetch_mexc_futures_klines(
                symbol,
                interval,
                warmup,
                as_of.isoformat(),
            )

        with ThreadPoolExecutor(
            max_workers=max(1, min(int(args.max_workers), len(symbols)))
        ) as pool:
            futures = {pool.submit(load, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol, frame = future.result()
                frames[symbol] = frame
                path = source_dir / f"{symbol}_{interval}.csv"
                frame.to_csv(path, index_label="timestamp")
                hashes[symbol] = sha256(path.read_bytes()).hexdigest()

        report = build_payoff_geometry_forward_report(
            config,
            frames,
            as_of_utc=as_of,
        )
        report["source_sha256"] = dict(sorted(hashes.items()))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "watch_id": report["watch_id"],
                    "status": report["status"],
                    "prospective_start_utc": report["prospective_start_utc"],
                    "as_of_utc": report["as_of_utc"],
                    "completed_trades": {
                        row["audit_id"]: row["summary"]["completed_trade_count"]
                        for row in report["reports"]
                    },
                    "HIGH_counts": {
                        row["audit_id"]: row["state_summaries"]["HIGH"][
                            "completed_trade_count"
                        ]
                        for row in report["reports"]
                    },
                    "LOW_counts": {
                        row["audit_id"]: row["state_summaries"]["LOW"][
                            "completed_trade_count"
                        ]
                        for row in report["reports"]
                    },
                    "ready": {
                        row["audit_id"]: row["sample_progress"]["ready_for_review"]
                        for row in report["reports"]
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        PayoffGeometryForwardError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

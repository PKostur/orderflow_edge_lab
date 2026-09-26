from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.vol8_payoff_amplitude_forward import (
    Vol8PayoffAmplitudeForwardError,
    build_forward_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen VOL8 prospective payoff-amplitude watch."
    )
    parser.add_argument(
        "--config",
        default="config/vol8_payoff_amplitude_forward_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        config_path = Path(args.config)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("watch_id") != "vol8-payoff-amplitude-forward-v1":
            raise Vol8PayoffAmplitudeForwardError("unexpected watch config")
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
                expected = futures[future]
                symbol, frame = future.result()
                if symbol != expected:
                    raise Vol8PayoffAmplitudeForwardError("source identity mismatch")
                frames[symbol] = frame
                path = source_dir / f"{symbol}_{interval}.csv"
                frame.to_csv(path, index_label="timestamp")
                hashes[symbol] = sha256(path.read_bytes()).hexdigest()

        report = build_forward_report(config, frames, as_of_utc=as_of)
        report["config_sha256"] = sha256(config_path.read_bytes()).hexdigest()
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
                    "as_of_utc": report["as_of_utc"],
                    "completed_trade_count": report["completed_trade_count"],
                    "open_post_start_snapshot_count": report[
                        "open_post_start_snapshot_count"
                    ],
                    "observed_symbol_count": report["observed_symbol_count"],
                    "distinct_7d_entry_block_count": report[
                        "distinct_7d_entry_block_count"
                    ],
                    "correlations": report["correlations"],
                    "review_progress": report["review_progress"],
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
        Vol8PayoffAmplitudeForwardError,
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

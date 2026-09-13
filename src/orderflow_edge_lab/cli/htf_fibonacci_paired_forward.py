from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.htf_fibonacci_paired_forward import build_paired_report
from orderflow_edge_lab.htf_trend_forward_shadow import load_candidate
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run contemporaneous baseline versus Fibonacci HTF paper shadows."
    )
    parser.add_argument(
        "--baseline-candidate",
        default="config/htf_fibonacci_paired_control_v1.json",
    )
    parser.add_argument(
        "--fibonacci-candidate",
        default="config/htf_fibonacci_forward_candidate_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    baseline, baseline_file_sha = load_candidate(args.baseline_candidate)
    fib, fib_file_sha = load_candidate(args.fibonacci_candidate)
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    symbols = [str(value) for value in fib["specification"]["symbols"]]
    warmup_start = str(fib["forward_protocol"]["indicator_warmup_start_utc"])
    forward_start = _utc(fib["forward_signal_start_utc"])

    source_dir = Path(args.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    frames = {}
    funding = {}
    source_hashes: dict[str, str] = {}

    def load(symbol: str):
        frame = fetch_mexc_futures_klines(symbol, "8h", warmup_start, as_of.isoformat())
        if as_of <= forward_start:
            fund = pd.DataFrame(
                columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC")
            )
        else:
            fund = fetch_mexc_funding_history(
                symbol, forward_start.isoformat(), as_of.isoformat()
            )
        return symbol, frame, fund

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            expected = futures[future]
            symbol, frame, fund = future.result()
            if symbol != expected:
                raise SystemExit(f"symbol identity mismatch: expected {expected}, got {symbol}")
            frames[symbol] = frame
            funding[symbol] = fund
            candle_path = source_dir / f"{symbol}_8h.csv"
            funding_path = source_dir / f"{symbol}_funding.csv"
            frame.to_csv(candle_path, index_label="timestamp")
            fund.to_csv(funding_path, index_label="timestamp")
            source_hashes[f"{symbol}:8h"] = sha256(candle_path.read_bytes()).hexdigest()
            source_hashes[f"{symbol}:funding"] = sha256(funding_path.read_bytes()).hexdigest()

    report = build_paired_report(
        frames,
        funding,
        baseline,
        fib,
        as_of_utc=as_of,
        baseline_candidate_file_sha256=baseline_file_sha,
        fib_candidate_file_sha256=fib_file_sha,
        source_sha256=source_hashes,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "paired_reviewable": report["paired_reviewable"],
                "baseline_net_return": report["baseline"]["metrics"]["net_return"],
                "fibonacci_net_return": report["fibonacci"]["metrics"]["net_return"],
                "fib_minus_baseline_net_return": report["paired_deltas"]["net_return"],
                "baseline_completed_trades": report["baseline"]["trade_stats"]["completed_trades"],
                "fibonacci_completed_trades": report["fibonacci"]["trade_stats"]["completed_trades"],
                "entry_subset_verified": report["entry_subset_verified"],
                "claims": report["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

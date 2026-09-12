from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.htf_trend_forward_shadow import build_forward_report, load_candidate
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen multi-coin 8h trend paper-shadow agent.")
    parser.add_argument("--candidate", default="config/htf_trend_candidate_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--as-of", default=None, help="Optional UTC timestamp for deterministic replay.")
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    candidate, candidate_file_sha = load_candidate(args.candidate)
    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
    spec = candidate["specification"]
    symbols = [str(value) for value in spec["symbols"]]
    warmup_start = str(candidate["forward_protocol"]["indicator_warmup_start_utc"])
    forward_start = str(candidate["forward_signal_start_utc"])
    source_dir = Path(args.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    frames = {}
    funding = {}
    source_hashes: dict[str, str] = {}

    def load(symbol: str):
        frame = fetch_mexc_futures_klines(symbol, "8h", warmup_start, as_of.isoformat())
        fund = fetch_mexc_funding_history(symbol, forward_start, as_of.isoformat())
        return symbol, frame, fund

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            loaded, frame, fund = future.result()
            if loaded != symbol:
                raise SystemExit(f"symbol identity mismatch: expected {symbol}, got {loaded}")
            frames[symbol] = frame
            funding[symbol] = fund
            candle_path = source_dir / f"{symbol}_8h.csv"
            funding_path = source_dir / f"{symbol}_funding.csv"
            frame.to_csv(candle_path, index_label="timestamp")
            fund.to_csv(funding_path, index_label="timestamp")
            source_hashes[f"{symbol}:8h"] = sha256(candle_path.read_bytes()).hexdigest()
            source_hashes[f"{symbol}:funding"] = sha256(funding_path.read_bytes()).hexdigest()

    report = build_forward_report(
        frames,
        funding,
        candidate,
        as_of_utc=as_of,
        candidate_file_sha256=candidate_file_sha,
        source_sha256=source_hashes,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "candidate_id": report["candidate_id"],
        "status": report["status"],
        "net_return": report["metrics"]["net_return"],
        "net_pnl_per_1000_usdt": report["metrics"]["net_pnl_per_1000_usdt"],
        "completed_symbol_trades": report["metrics"]["completed_symbol_trades"],
        "open_symbol_positions": report["metrics"]["open_symbol_positions"],
        "current_weights": report["current_weights"],
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

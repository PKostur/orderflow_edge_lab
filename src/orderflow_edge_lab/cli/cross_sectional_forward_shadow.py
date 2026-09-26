from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.cross_sectional_forward_shadow import build_forward_report, load_candidate
from orderflow_edge_lab.daily_portfolio_session import build_daily_portfolio_session_report
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen 30d/7d dollar-neutral cross-sectional momentum paper-shadow agent.")
    parser.add_argument("--candidate", default="config/cross_sectional_candidate_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--as-of", default=None, help="Optional UTC timestamp for deterministic replay.")
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--session-output", default=None, help="Optional additive 8h session-attribution JSON output.")
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
    frames_8h = {}
    funding = {}
    source_hashes: dict[str, str] = {}

    def load(symbol: str):
        frame = fetch_mexc_futures_klines(symbol, "1d", warmup_start, as_of.isoformat())
        # Session attribution needs enough 8h source bars for the shared
        # history loader. Fetch from the already-declared indicator warmup
        # boundary; build_daily_portfolio_session_report still scores only
        # the frozen forward holding periods from the forward report.
        frame_8h = (
            fetch_mexc_futures_klines(symbol, "8h", warmup_start, as_of.isoformat())
            if args.session_output
            else None
        )
        fund = fetch_mexc_funding_history(symbol, forward_start, as_of.isoformat())
        return symbol, frame, frame_8h, fund

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            loaded, frame, frame_8h, fund = future.result()
            if loaded != symbol:
                raise SystemExit(f"symbol identity mismatch: expected {symbol}, got {loaded}")
            frames[symbol] = frame
            if frame_8h is not None:
                frames_8h[symbol] = frame_8h
            funding[symbol] = fund
            candle_path = source_dir / f"{symbol}_1d.csv"
            funding_path = source_dir / f"{symbol}_funding.csv"
            frame.to_csv(candle_path, index_label="timestamp")
            fund.to_csv(funding_path, index_label="timestamp")
            source_hashes[f"{symbol}:1d"] = sha256(candle_path.read_bytes()).hexdigest()
            source_hashes[f"{symbol}:funding"] = sha256(funding_path.read_bytes()).hexdigest()
            if frame_8h is not None:
                eight_path = source_dir / f"{symbol}_8h.csv"
                frame_8h.to_csv(eight_path, index_label="timestamp")
                source_hashes[f"{symbol}:8h_session_attribution"] = sha256(eight_path.read_bytes()).hexdigest()

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
    if args.session_output:
        session_report = build_daily_portfolio_session_report(
            report,
            bars_8h=frames_8h,
            funding=funding,
        )
        session_path = Path(args.session_output)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(json.dumps(session_report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "candidate_id": report["candidate_id"],
        "status": report["status"],
        "net_return": report["metrics"]["net_return"],
        "net_pnl_per_1000_usdt": report["metrics"]["net_pnl_per_1000_usdt"],
        "executed_rebalances": report["metrics"]["executed_rebalances"],
        "completed_holding_periods": report["metrics"]["completed_holding_periods"],
        "open_symbol_positions": report["metrics"]["open_symbol_positions"],
        "current_weights": report["current_weights"],
        "contribution_concentration": report["contribution_concentration"],
        "latest_completed_period_contribution_concentration": (
            report["completed_holding_periods"][-1]["contribution_concentration"]
            if report["completed_holding_periods"]
            else None
        ),
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.bybit_history import (
    fetch_bybit_linear_funding_history,
    fetch_bybit_linear_klines,
)
from orderflow_edge_lab.cross_sectional_forward_shadow import load_candidate
from orderflow_edge_lab.cross_sectional_venue_replication import (
    build_venue_replication_report,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run D2 independent-venue replication of the frozen cross-sectional candidate."
    )
    parser.add_argument(
        "--candidate",
        default="config/cross_sectional_candidate_v1.json",
    )
    parser.add_argument(
        "--config",
        default="config/cross_sectional_venue_replication_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args(argv)

    candidate, candidate_file_sha = load_candidate(args.candidate)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    symbols = [str(v) for v in config["symbols"]]
    start = str(config["window"]["start"])
    end = str(config["window"]["end_exclusive"])
    source = Path(args.source_dir)
    source.mkdir(parents=True, exist_ok=True)

    mexc_frames = {}
    mexc_funding = {}
    replication_frames = {}
    replication_funding = {}
    hashes: dict[str, str] = {
        "candidate_file": candidate_file_sha,
        "replication_config": sha256(Path(args.config).read_bytes()).hexdigest(),
    }

    def load(symbol: str):
        return (
            symbol,
            fetch_mexc_futures_klines(symbol, "1d", start, end),
            fetch_mexc_funding_history(symbol, start, end),
            fetch_bybit_linear_klines(symbol, "1d", start, end),
            fetch_bybit_linear_funding_history(symbol, start, end),
        )

    with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            expected = futures[future]
            symbol, mf, mfund, bf, bfund = future.result()
            if symbol != expected:
                raise SystemExit(f"symbol identity mismatch: {expected} != {symbol}")
            mexc_frames[symbol] = mf
            mexc_funding[symbol] = mfund
            replication_frames[symbol] = bf
            replication_funding[symbol] = bfund
            for venue, kind, frame in (
                ("mexc", "1d", mf),
                ("mexc", "funding", mfund),
                ("bybit_linear", "1d", bf),
                ("bybit_linear", "funding", bfund),
            ):
                path = source / f"{venue}_{symbol}_{kind}.csv"
                frame.to_csv(path, index_label="timestamp")
                hashes[f"{venue}:{symbol}:{kind}"] = sha256(path.read_bytes()).hexdigest()

    report = build_venue_replication_report(
        candidate,
        mexc_frames,
        mexc_funding,
        replication_frames,
        replication_funding,
        config,
        source_sha256=hashes,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_id": report["candidate_id"],
                "evidence_independence": report["evidence_independence"],
                "shared_daily_observations": report["shared_daily_observations"],
                "mexc_net_return": report["mexc"]["net_return"],
                "independent_venue": report["economics"]["independent_venue"],
                "independent_net_return": report["independent_venue"]["net_return"],
                "signal_agreement": report["signal_agreement"],
                "formal_verdict": report["formal_verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

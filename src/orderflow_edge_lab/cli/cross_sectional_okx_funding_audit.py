from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

from orderflow_edge_lab.cross_sectional_forward_shadow import load_candidate
from orderflow_edge_lab.funding_coverage import build_funding_coverage_report
from orderflow_edge_lab.okx_history import (
    fetch_okx_swap_funding_history,
    fetch_okx_swap_klines,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit OKX realized-funding coverage for held intervals without recomputing candidate PnL."
    )
    parser.add_argument(
        "--candidate",
        default="config/cross_sectional_candidate_v1.json",
    )
    parser.add_argument(
        "--config",
        default="config/cross_sectional_okx_funding_audit_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--max-workers", type=int, default=1)
    args = parser.parse_args(argv)

    candidate, candidate_file_sha = load_candidate(args.candidate)
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("audit_id") != "cross-sectional-okx-funding-coverage-audit-v1":
        raise SystemExit("unexpected funding-audit config")

    symbols = [str(value) for value in config["symbols"]]
    start = str(config["window"]["start"])
    end = str(config["window"]["end_exclusive"])
    rest_base = str(config["okx_api"]["rest_base"])
    source = Path(args.source_dir)
    source.mkdir(parents=True, exist_ok=True)

    prices = {}
    funding = {}
    hashes: dict[str, str] = {
        "candidate_file": candidate_file_sha,
        "audit_config": sha256(config_path.read_bytes()).hexdigest(),
    }

    def load(symbol: str):
        return (
            symbol,
            fetch_okx_swap_klines(
                symbol,
                "1d",
                start,
                end,
                rest_base=rest_base,
            ),
            fetch_okx_swap_funding_history(
                symbol,
                start,
                end,
                rest_base=rest_base,
            ),
        )

    with ThreadPoolExecutor(
        max_workers=max(1, min(int(args.max_workers), len(symbols)))
    ) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            expected = futures[future]
            symbol, price, fund = future.result()
            if symbol != expected:
                raise SystemExit(f"symbol identity mismatch: {expected} != {symbol}")
            prices[symbol] = price
            funding[symbol] = fund
            for kind, frame in (("1d", price), ("funding", fund)):
                path = source / f"okx_swap_{symbol}_{kind}.csv"
                frame.to_csv(path, index_label="timestamp")
                hashes[f"okx_swap:{symbol}:{kind}"] = sha256(
                    path.read_bytes()
                ).hexdigest()

    report = build_funding_coverage_report(candidate, prices, funding, config)
    report["source_sha256"] = hashes
    report["source_access"] = {
        "rest_base": rest_base,
        "candles_endpoint": config["okx_api"]["candles_endpoint"],
        "funding_endpoint": config["okx_api"]["funding_endpoint"],
        "funding_field": config["okx_api"]["funding_field"],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "audit_id": report["audit_id"],
                "candidate_id": report["candidate_id"],
                "status": report["status"],
                "coverage_fraction": report["coverage_fraction"],
                "required_held_intervals": report["required_held_intervals"],
                "covered_held_intervals": report["covered_held_intervals"],
                "funding_economics_admissible": report["funding_economics_admissible"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

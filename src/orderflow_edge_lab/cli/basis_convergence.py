from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from orderflow_edge_lab.basis_convergence import evaluate_basis_grid, load_mexc_basis_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen MEXC positive-basis convergence development grid.")
    parser.add_argument("--config", default="config/evidence_backed_strategies_v2.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    spec = protocol["basis_convergence"]
    symbols = [str(value).upper() for value in spec["symbols"]]
    datasets = {}
    failures: list[dict[str, str]] = []

    def load(symbol: str):
        return symbol, load_mexc_basis_dataset(symbol, str(spec["start"]), str(spec["end_exclusive"]))

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                loaded_symbol, dataset = future.result()
                datasets[loaded_symbol] = dataset
            except Exception as exc:
                failures.append({"symbol": symbol, "error_type": type(exc).__name__, "message": str(exc)[:300]})

    if len(datasets) < 3:
        raise SystemExit(f"only {len(datasets)} basis datasets loaded; need at least 3; failures={failures}")

    report = evaluate_basis_grid(
        datasets,
        entry_thresholds=[float(v) for v in spec["upper_entry_bps"]],
        exit_thresholds=[float(v) for v in spec["lower_exit_bps"]],
        cost_cases=[float(v) for v in spec["round_trip_pair_cost_bps"]],
        fold_days=int(spec["fold_days"]),
        minimum_trades=int(spec["minimum_trades"]),
        minimum_folds=int(spec["minimum_folds"]),
        minimum_positive_fold_fraction=float(spec["minimum_positive_fold_fraction"]),
        minimum_positive_symbol_fraction=float(spec["minimum_positive_symbol_fraction"]),
    )
    report.update({
        "protocol_name": protocol["protocol_name"],
        "source_prior": protocol["sources"][0],
        "loaded_symbols": sorted(datasets),
        "load_failures": sorted(failures, key=lambda row: row["symbol"]),
        "frozen_spec": spec,
    })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "loaded_symbols": sorted(datasets),
        "variant_count": report["variant_count"],
        "eligible_count": report["eligible_count"],
        "top": report["variants"][:5],
    }, indent=2))


if __name__ == "__main__":
    main()

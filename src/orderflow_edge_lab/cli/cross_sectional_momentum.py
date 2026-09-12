from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from orderflow_edge_lab.cross_sectional_momentum import run_frozen_grid
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen published cross-sectional crypto momentum replication.")
    parser.add_argument("--config", default="config/published_cross_sectional_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    data = protocol["data"]
    symbols = [str(value).upper() for value in data["symbols"]]
    frames = {}
    failures: list[dict[str, str]] = []

    def load(symbol: str):
        frame = fetch_mexc_futures_klines(symbol, "1d", str(data["start"]), str(data["end_exclusive"]))
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                loaded, frame = future.result()
                frames[loaded] = frame
            except Exception as exc:
                failures.append({"symbol": symbol, "error_type": type(exc).__name__, "message": str(exc)[:300]})

    if len(frames) < 8:
        raise SystemExit(f"only {len(frames)} symbols loaded; require at least 8; failures={failures}")

    report = run_frozen_grid(frames, protocol)
    report.update({
        "loaded_symbols": sorted(frames),
        "load_failures": sorted(failures, key=lambda row: row["symbol"]),
        "survivorship_warning": data["survivorship_warning"],
    })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "loaded_symbols": report["loaded_symbols"],
        "trial_count": report["trial_count"],
        "eligible_count": report["eligible_count"],
        "trials": report["trials"],
    }, indent=2))


if __name__ == "__main__":
    main()

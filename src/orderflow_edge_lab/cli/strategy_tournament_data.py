from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.strategy_tournament import fetch_binance_usdm_klines


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare one interval of immutable public historical data for a frozen strategy tournament.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--interval", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.interval not in cfg["data"]["intervals"]:
        raise SystemExit(f"interval {args.interval!r} not frozen in tournament protocol")
    start = str(cfg["data"]["start"])
    end = str(cfg["data"]["end_exclusive"])
    symbols = [str(value).upper() for value in cfg["data"]["symbols"]]
    source = str(cfg["data"]["source"]).lower()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": 1,
        "protocol_name": cfg["protocol_name"],
        "source": cfg["data"]["source"],
        "interval": args.interval,
        "start": start,
        "end_exclusive": end,
        "files": [],
        "failures": [],
    }

    def load(symbol: str):
        if "mexc" in source:
            frame = fetch_mexc_futures_klines(symbol, args.interval, start, end)
        elif "binance" in source:
            frame = fetch_binance_usdm_klines(symbol, args.interval, start, end)
        else:
            raise ValueError(f"unsupported frozen source: {cfg['data']['source']}")
        path = output_dir / f"{symbol}_{args.interval}.csv"
        frame.to_csv(path, index=True)
        return symbol, path, len(frame), str(frame.index.min()), str(frame.index.max())

    with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                loaded_symbol, path, rows, first_ts, last_ts = future.result()
                manifest["files"].append(
                    {
                        "symbol": loaded_symbol,
                        "path": path.name,
                        "rows": rows,
                        "first_timestamp": first_ts,
                        "last_timestamp": last_ts,
                        "sha256": _sha256(path),
                    }
                )
            except Exception as exc:
                manifest["failures"].append(
                    {"symbol": symbol, "error_type": type(exc).__name__, "message": str(exc)[:300]}
                )

    manifest["files"].sort(key=lambda row: row["symbol"])
    manifest["failures"].sort(key=lambda row: row["symbol"])
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if manifest["failures"]:
        print(json.dumps({"failures": manifest["failures"]}, indent=2))
    if len(manifest["files"]) < 6:
        raise SystemExit(f"only {len(manifest['files'])} symbols loaded; need at least 6; see {manifest_path}")
    print(manifest_path)


if __name__ == "__main__":
    main()

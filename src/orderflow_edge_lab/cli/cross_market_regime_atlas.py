from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.cross_market_regime_atlas import (
    CrossMarketRegimeAtlasError,
    build_regime_atlas_report,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def _load_config(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CrossMarketRegimeAtlasError("config must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the frozen cross-market regime-atlas Phase A development report."
    )
    parser.add_argument(
        "--config",
        default="config/cross_market_regime_atlas_v1_1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        config = _load_config(args.config)
        data = config["development_data"]
        if not isinstance(data, dict):
            raise CrossMarketRegimeAtlasError("development_data must be an object")
        symbols = [str(value) for value in data["symbols"]]
        interval = str(data["interval"])
        start = str(data["start_utc"])
        end = str(data["end_exclusive_utc"])
        source_dir = Path(args.source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)

        frames: dict[str, pd.DataFrame] = {}
        source_hashes: dict[str, str] = {}

        def load(symbol: str) -> tuple[str, pd.DataFrame]:
            return symbol, fetch_mexc_futures_klines(symbol, interval, start, end)

        with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(symbols)))) as pool:
            futures = {pool.submit(load, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                expected = futures[future]
                symbol, frame = future.result()
                if symbol != expected:
                    raise CrossMarketRegimeAtlasError("source identity mismatch")
                frames[symbol] = frame
                path = source_dir / f"{symbol}_{interval}.csv"
                frame.to_csv(path, index_label="timestamp")
                source_hashes[symbol] = sha256(path.read_bytes()).hexdigest()

        report = build_regime_atlas_report(frames, config)
        report["source_sha256"] = dict(sorted(source_hashes.items()))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        sufficient = sum(bool(row["descriptive_cell_sufficient"]) for row in report["cells"])
        print(
            json.dumps(
                {
                    "protocol_name": report["protocol_name"],
                    "phase": report["phase"],
                    "observation_count": report["observation_count"],
                    "cell_count": report["cell_count"],
                    "sufficient_cell_count": sufficient,
                    "instrument_count": len(symbols),
                    "horizons_bars": report["raw_future_outcomes"]["horizons_bars"],
                    "source_sha256": report["source_sha256"],
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
        CrossMarketRegimeAtlasError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

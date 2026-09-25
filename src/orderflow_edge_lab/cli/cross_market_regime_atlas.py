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


def _source_coverage(
    symbol: str,
    frame: pd.DataFrame,
    config: dict[str, object],
) -> dict[str, object]:
    data = config["development_data"]
    quality = config["data_quality"]
    if not isinstance(data, dict) or not isinstance(quality, dict):
        raise CrossMarketRegimeAtlasError("development_data/data_quality must be objects")
    step = pd.Timedelta(hours=int(quality["expected_interval_hours"]))
    start = pd.Timestamp(str(data["start_utc"]))
    end = pd.Timestamp(str(data["end_exclusive_utc"]))
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    expected_last = end - step
    index = pd.to_datetime(frame.index, utc=True)
    if index.empty:
        raise CrossMarketRegimeAtlasError(f"{symbol}: empty source frame")
    diffs = index.to_series().diff().dropna()
    gaps = diffs[diffs != step]
    if len(gaps):
        raise CrossMarketRegimeAtlasError(
            f"{symbol}: {len(gaps)} internal interval gaps/nonconforming steps"
        )
    full = {str(value) for value in quality.get("full_window_symbols", [])}
    leading_allowed = {str(value) for value in quality.get("allow_leading_missing_symbols", [])}
    first = pd.Timestamp(index[0])
    last = pd.Timestamp(index[-1])
    if symbol in full and first != start:
        raise CrossMarketRegimeAtlasError(
            f"{symbol}: full-window source starts {first.isoformat()} not {start.isoformat()}"
        )
    if symbol not in full and symbol not in leading_allowed:
        raise CrossMarketRegimeAtlasError(f"{symbol}: no declared source coverage policy")
    if first < start:
        raise CrossMarketRegimeAtlasError(f"{symbol}: source starts before frozen window")
    if last != expected_last:
        raise CrossMarketRegimeAtlasError(
            f"{symbol}: trailing coverage ends {last.isoformat()} not {expected_last.isoformat()}"
        )
    return {
        "rows": len(frame),
        "first_timestamp_utc": first.isoformat(),
        "last_timestamp_utc": last.isoformat(),
        "leading_missing_allowed": symbol in leading_allowed,
        "starts_at_frozen_window": first == start,
        "internal_gap_count": 0,
        "expected_interval_hours": int(quality["expected_interval_hours"]),
    }


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
        source_coverage: dict[str, dict[str, object]] = {}

        def load(symbol: str) -> tuple[str, pd.DataFrame]:
            return symbol, fetch_mexc_futures_klines(symbol, interval, start, end)

        with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(symbols)))) as pool:
            futures = {pool.submit(load, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                expected = futures[future]
                symbol, frame = future.result()
                if symbol != expected:
                    raise CrossMarketRegimeAtlasError("source identity mismatch")
                source_coverage[symbol] = _source_coverage(symbol, frame, config)
                frames[symbol] = frame
                path = source_dir / f"{symbol}_{interval}.csv"
                frame.to_csv(path, index_label="timestamp")
                source_hashes[symbol] = sha256(path.read_bytes()).hexdigest()

        report = build_regime_atlas_report(frames, config)
        report["protocol_config_sha256"] = sha256(config_bytes).hexdigest()
        report["source_sha256"] = dict(sorted(source_hashes.items()))
        report["source_coverage"] = dict(sorted(source_coverage.items()))
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
                    "protocol_config_sha256": report["protocol_config_sha256"],
                    "source_sha256": report["source_sha256"],
                    "source_coverage": report["source_coverage"],
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

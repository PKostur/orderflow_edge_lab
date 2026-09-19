from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Callable

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.htf_trend_forward_shadow import load_candidate as load_trend_candidate
from orderflow_edge_lab.cross_sectional_forward_shadow import load_candidate as load_xs_candidate
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.strategy_tournament import fetch_binance_usdm_klines
from orderflow_edge_lab.strongest_candidate_hardening import (
    evaluate_cross_sectional_panel,
    evaluate_trend_panel,
    fetch_binance_usdm_funding_history,
)


def _retry(fn: Callable[[], Any], *, attempts: int = 4, base_sleep: float = 1.0) -> Any:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(base_sleep * (2 ** i))
    assert last is not None
    raise last


def _load_protocol(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _source_payload(
    source: str,
    symbols: list[str],
    start: str,
    end: str,
    *,
    max_workers: int,
    source_dir: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, str]]:
    trend_frames: dict[str, pd.DataFrame] = {}
    daily_frames: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    hashes: dict[str, str] = {}

    def load(symbol: str):
        if source == "mexc":
            trend = _retry(lambda: fetch_mexc_futures_klines(symbol, "8h", start, end))
            daily = _retry(lambda: fetch_mexc_futures_klines(symbol, "1d", start, end))
            fund = _retry(lambda: fetch_mexc_funding_history(symbol, start, end))
        elif source == "binance_usdm":
            normalized = symbol.replace("_", "")
            trend = _retry(lambda: fetch_binance_usdm_klines(normalized, "8h", start, end))
            daily = _retry(lambda: fetch_binance_usdm_klines(normalized, "1d", start, end))
            fund = _retry(lambda: fetch_binance_usdm_funding_history(normalized, start, end))
        else:
            raise ValueError(f"unknown source {source}")
        return symbol, trend, daily, fund

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            expected = futures[future]
            symbol, trend, daily, fund = future.result()
            if symbol != expected:
                raise RuntimeError(f"source identity mismatch {expected} != {symbol}")
            trend_frames[symbol] = trend
            daily_frames[symbol] = daily
            funding[symbol] = fund
            for label, frame in (("8h", trend), ("1d", daily), ("funding", fund)):
                path = source_dir / f"{symbol}_{label}.csv"
                frame.to_csv(path, index_label="timestamp")
                hashes[f"{symbol}:{label}"] = sha256(path.read_bytes()).hexdigest()
    return trend_frames, daily_frames, funding, hashes


def main() -> None:
    parser = argparse.ArgumentParser(description="Adversarially harden the two strongest frozen candidates.")
    parser.add_argument("--config", default="config/strongest_candidate_hardening_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    protocol = _load_protocol(args.config)
    trend_candidate, _ = load_trend_candidate(protocol["candidates"]["htf_trend"]["config"])
    xs_candidate, _ = load_xs_candidate(protocol["candidates"]["cross_sectional"]["config"])
    if trend_candidate["spec_sha256"] != protocol["candidates"]["htf_trend"]["spec_sha256"]:
        raise SystemExit("trend candidate hash changed after hardening freeze")
    if xs_candidate["spec_sha256"] != protocol["candidates"]["cross_sectional"]["spec_sha256"]:
        raise SystemExit("cross-sectional candidate hash changed after hardening freeze")

    symbols = [str(x) for x in trend_candidate["specification"]["symbols"]]
    if symbols != [str(x) for x in xs_candidate["specification"]["symbols"]]:
        raise SystemExit("candidate symbol panels differ")
    window = protocol["development_window"]
    start = str(window["start_utc"])
    end = str(window["end_exclusive_utc"])
    stress = protocol["stress_protocol"]
    costs = [float(x) for x in stress["round_trip_cost_bps"]]
    fold_days = int(stress["fold_days"])
    permutations = int(stress["cross_sectional_random_rank_placebos"])
    seed = int(stress["placebo_seed"])

    root = Path(args.source_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_reports: dict[str, Any] = {}
    for source in ("mexc", "binance_usdm"):
        source_path = root / source
        source_path.mkdir(parents=True, exist_ok=True)
        trend_frames, daily_frames, funding, source_hashes = _source_payload(
            source,
            symbols,
            start,
            end,
            max_workers=int(args.max_workers),
            source_dir=source_path,
        )
        source_reports[source] = {
            "source_hashes": source_hashes,
            "trend": [
                evaluate_trend_panel(
                    trend_frames,
                    funding,
                    trend_candidate,
                    cost_bps=cost,
                    fold_days=fold_days,
                    regime_return_days=int(stress["trend_regime_diagnostics"]["btc_trailing_return_days"]),
                    regime_vol_days=int(stress["trend_regime_diagnostics"]["btc_realized_vol_days"]),
                )
                for cost in costs
            ],
            "cross_sectional": [
                evaluate_cross_sectional_panel(
                    daily_frames,
                    funding,
                    xs_candidate,
                    cost_bps=cost,
                    fold_days=fold_days,
                    placebo_permutations=permutations,
                    placebo_seed=seed,
                )
                for cost in costs
            ],
        }

    report = {
        "schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "protocol_frozen_at_utc": protocol["frozen_at_utc"],
        "development_window": window,
        "candidate_hashes": {
            "htf_trend": trend_candidate["spec_sha256"],
            "cross_sectional": xs_candidate["spec_sha256"],
        },
        "sources": source_reports,
        "claims": {
            "candidate_parameters_changed": False,
            "prospective_forward_records_modified": False,
            "development_hardening_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")

    compact: dict[str, Any] = {"output": str(output), "sources": {}}
    for source, item in source_reports.items():
        trend20 = item["trend"][0]
        xs20 = item["cross_sectional"][0]
        compact["sources"][source] = {
            "trend_20bps": {
                "original": trend20["modes"]["frozen_original"],
                "reversed_net_return": trend20["modes"]["exact_signal_reversal"]["net_return"],
                "long_only_net_return": trend20["modes"]["equal_weight_long_only"]["net_return"],
                "leave_one_out_all_positive": trend20["leave_one_out_all_positive"],
            },
            "cross_sectional_20bps": {
                "net_return": xs20["actual"]["net_return"],
                "positive_fold_fraction": xs20["actual"]["positive_fold_fraction"],
                "placebo": xs20["random_rank_placebo"],
                "leave_one_out_all_positive": xs20["leave_one_out_all_positive"],
            },
        }
    print(json.dumps(compact, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

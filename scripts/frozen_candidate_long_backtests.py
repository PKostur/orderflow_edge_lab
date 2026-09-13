from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.cross_sectional_forward_shadow import build_forward_report as build_cross_sectional_report
from orderflow_edge_lab.ena_forward_shadow import build_forward_report as build_ena_report
from orderflow_edge_lab.htf_trend_forward_shadow import build_forward_report as build_htf_report
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


UTC = "UTC"


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(UTC) if ts.tzinfo is None else ts.tz_convert(UTC)


def _iso(value: pd.Timestamp) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _load_json(path: str | Path) -> tuple[dict[str, Any], str]:
    source = Path(path)
    raw = source.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {source}")
    return payload, sha256(raw).hexdigest()


def _retry(call: Callable[[], Any], *, attempts: int = 3, pause_seconds: float = 2.0) -> Any:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # network retry is intentionally broad for public REST instability
            last = exc
            if attempt == attempts:
                raise
            time.sleep(pause_seconds * attempt)
    raise RuntimeError("retry loop terminated unexpectedly") from last


def _write_frame(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index_label="timestamp")
    return sha256(path.read_bytes()).hexdigest()


def _stress_candidate(
    source: Mapping[str, Any],
    *,
    window_start: pd.Timestamp,
    history_start: pd.Timestamp,
    cost_bps: float,
    protocol_sha256: str,
) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(source))
    original_id = str(candidate["candidate_id"])
    original_spec = copy.deepcopy(candidate["specification"])
    frozen_cost = float(original_spec["round_trip_cost_bps"])
    if not math.isclose(frozen_cost, 20.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"unexpected frozen cost for {original_id}: {frozen_cost}")

    candidate["candidate_id"] = f"{original_id}::historical_stress_v1"
    candidate["forward_signal_start_utc"] = _iso(window_start)
    candidate["specification"]["round_trip_cost_bps"] = float(cost_bps)
    forward = candidate.get("forward_protocol")
    if isinstance(forward, dict):
        if "indicator_warmup_start_utc" in forward:
            forward["indicator_warmup_start_utc"] = _iso(history_start)
        if "first_possible_execution_utc" in forward:
            interval = str(candidate["specification"].get("interval", ""))
            delay = pd.Timedelta(days=1) if interval == "1d" else pd.Timedelta(hours=8)
            forward["first_possible_execution_utc"] = _iso(window_start + delay)

    candidate["historical_stress_provenance"] = {
        "protocol": "frozen-candidate-long-backtest-v1",
        "protocol_sha256": protocol_sha256,
        "source_candidate_id": original_id,
        "source_candidate_spec_sha256": source.get("spec_sha256"),
        "retrospective_only": True,
        "untouched_oos": False,
        "parameter_retuning": False,
        "only_allowed_strategy_change": (
            "round_trip_cost_bps may increase from the frozen 20 bps to a predeclared adverse cost stress"
        ),
    }
    candidate["claims"] = {
        "source_strategy_specification_frozen": True,
        "retrospective_development_stress_only": True,
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
        "live_order_transmission_supported": False,
    }
    candidate.pop("spec_sha256", None)
    candidate["spec_sha256"] = _canonical_sha256(candidate)

    stress_spec = copy.deepcopy(candidate["specification"])
    source_compare = copy.deepcopy(original_spec)
    stress_compare = copy.deepcopy(stress_spec)
    source_compare.pop("round_trip_cost_bps", None)
    stress_compare.pop("round_trip_cost_bps", None)
    if source_compare != stress_compare:
        raise ValueError(f"strategy specification drift detected for {original_id}")
    if float(stress_spec["round_trip_cost_bps"]) < frozen_cost:
        raise ValueError("historical stress may not improve the frozen transaction-cost assumption")
    return candidate


def _window_set(
    effective_start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    protocol: Mapping[str, Any],
) -> list[dict[str, Any]]:
    windows_cfg = protocol["windows"]
    minimum = pd.Timedelta(days=int(windows_cfg["minimum_window_days"]))
    start = _utc(effective_start).floor("d")
    end = _utc(end_exclusive).floor("d")
    windows: list[dict[str, Any]] = []

    if bool(windows_cfg.get("include_full_available_history", True)) and end - start >= minimum:
        windows.append({"name": "full_available", "kind": "full", "start": start, "end": end})

    if bool(windows_cfg.get("include_calendar_years", True)):
        for year in range(start.year, end.year + 1):
            left = max(start, pd.Timestamp(f"{year}-01-01", tz=UTC))
            right = min(end, pd.Timestamp(f"{year + 1}-01-01", tz=UTC))
            if right - left >= minimum:
                windows.append({"name": f"calendar_{year}", "kind": "calendar", "start": left, "end": right})

    for rolling in windows_cfg.get("rolling_windows", []):
        length = pd.Timedelta(days=int(rolling["length_days"]))
        step = pd.Timedelta(days=int(rolling["step_days"]))
        cursor = start
        index = 1
        while cursor + length <= end:
            right = cursor + length
            windows.append(
                {
                    "name": f"rolling_{int(rolling['length_days'])}d_{index:02d}",
                    "kind": f"rolling_{int(rolling['length_days'])}d",
                    "start": cursor,
                    "end": right,
                }
            )
            cursor += step
            index += 1

    unique: dict[tuple[int, int, str], dict[str, Any]] = {}
    for window in windows:
        key = (int(window["start"].value), int(window["end"].value), str(window["kind"]))
        unique[key] = window
    return sorted(unique.values(), key=lambda row: (row["start"], row["end"], row["kind"]))


def _profit_factor(values: list[float]) -> float | str | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses > 0:
        return float(gains / losses)
    if gains > 0:
        return "INF"
    return None


def _return_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "observations": 0,
            "mean_return_bps": None,
            "profit_factor": None,
            "positive_fraction": None,
            "compounded_return": None,
            "max_drawdown": None,
        }
    arr = np.asarray(values, dtype=float)
    equity = np.cumprod(1.0 + arr)
    peaks = np.maximum.accumulate(equity)
    return {
        "observations": int(len(arr)),
        "mean_return_bps": float(arr.mean() * 10_000.0),
        "profit_factor": _profit_factor([float(v) for v in arr]),
        "positive_fraction": float(np.mean(arr > 0)),
        "compounded_return": float(equity[-1] - 1.0),
        "max_drawdown": float(np.min(equity / peaks - 1.0)),
    }


def _summary_from_report(strategy: str, report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = dict(report.get("metrics") or {})
    if strategy == "ena_mean_reversion":
        completed = list(report.get("completed_trades") or [])
        trade_returns = [float(row["net_return"]) for row in completed]
        stats = _return_stats(trade_returns)
        return {
            **metrics,
            "completed_trade_stats": stats,
            "open_positions": 1 if report.get("open_position") else 0,
        }
    if strategy == "htf_trend":
        completed = list(report.get("completed_trades") or [])
        intervals = list(report.get("portfolio_intervals") or [])
        return {
            **metrics,
            "completed_trade_stats": _return_stats([float(row["net_return"]) for row in completed]),
            "portfolio_interval_stats": _return_stats([float(row["net_return"]) for row in intervals]),
        }
    if strategy == "cross_sectional":
        intervals = list(report.get("portfolio_intervals") or [])
        return {
            **metrics,
            "portfolio_interval_stats": _return_stats([float(row["net_return"]) for row in intervals]),
        }
    raise ValueError(f"unknown strategy: {strategy}")


def _fetch_price_panel(
    symbols: list[str],
    interval: str,
    start: str,
    end: str,
    *,
    max_workers: int,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> tuple[str, pd.DataFrame]:
        frame = _retry(lambda: fetch_mexc_futures_klines(symbol, interval, start, end))
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, frame = future.result()
            frames[symbol] = frame
    return frames


def _fetch_funding_panel(
    symbols: list[str],
    start: str,
    end: str,
    *,
    max_workers: int,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> tuple[str, pd.DataFrame]:
        frame = _retry(lambda: fetch_mexc_funding_history(symbol, start, end), attempts=3, pause_seconds=3.0)
        return symbol, frame

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(symbols)))) as pool:
        futures = {pool.submit(load, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, frame = future.result()
            frames[symbol] = frame
    return frames


def _data_coverage(frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for symbol in sorted(frames):
        frame = frames[symbol]
        result[symbol] = {
            "rows": int(len(frame)),
            "first": frame.index.min().isoformat() if len(frame) else None,
            "last": frame.index.max().isoformat() if len(frame) else None,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Long-history retrospective stress of the exact watched frozen candidates.")
    parser.add_argument("--config", default="config/frozen_candidate_long_backtest_v1.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()

    protocol_path = Path(args.config)
    protocol_raw = protocol_path.read_bytes()
    protocol = json.loads(protocol_raw.decode("utf-8"))
    if protocol.get("protocol_name") != "frozen-candidate-long-backtest-v1":
        raise SystemExit("unexpected long-history protocol")
    protocol_sha = sha256(protocol_raw).hexdigest()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    end_exclusive = _utc(protocol["data_end_exclusive_utc"])
    frozen_cost = float(protocol["economics"]["frozen_round_trip_cost_bps"])
    cost_cases = [frozen_cost] + [float(v) for v in protocol["economics"].get("adverse_cost_stress_bps", [])]
    if any(value < frozen_cost for value in cost_cases):
        raise SystemExit("cost stress cannot be more favorable than the frozen candidate economics")

    summaries: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": protocol["protocol_name"],
        "protocol_sha256": protocol_sha,
        "status": protocol["status"],
        "data_end_exclusive_utc": _iso(end_exclusive),
        "candidates": {},
        "claims": protocol["claims"],
    }

    for strategy, cfg in protocol["candidates"].items():
        candidate, candidate_file_sha = _load_json(cfg["candidate_path"])
        history_start = _utc(cfg["history_start_utc"])
        minimum_signal_start = _utc(cfg["minimum_signal_start_utc"])
        interval = str(cfg["interval"])
        spec = candidate["specification"]
        symbols = [str(spec["symbol"])] if "symbol" in spec else [str(v) for v in spec["symbols"]]

        prices = _fetch_price_panel(
            symbols,
            interval,
            _iso(history_start),
            _iso(end_exclusive),
            max_workers=int(args.max_workers),
        )
        funding: dict[str, pd.DataFrame] = {}
        if bool(cfg.get("uses_funding")):
            funding = _fetch_funding_panel(
                symbols,
                _iso(history_start),
                _iso(end_exclusive),
                max_workers=max(1, min(3, int(args.max_workers))),
            )

        source_hashes: dict[str, str] = {}
        for symbol, frame in prices.items():
            source_hashes[f"{symbol}:{interval}"] = _write_frame(
                frame, data_dir / strategy / f"{symbol}_{interval}.csv"
            )
        for symbol, frame in funding.items():
            source_hashes[f"{symbol}:funding"] = _write_frame(
                frame, data_dir / strategy / f"{symbol}_funding.csv"
            )

        if strategy == "cross_sectional":
            common: pd.DatetimeIndex | None = None
            for symbol in symbols:
                common = prices[symbol].index if common is None else common.intersection(prices[symbol].index)
            if common is None or len(common) < int(spec["lookback_days"]) + 2:
                raise SystemExit("cross-sectional candidate has insufficient common history")
            common = common.sort_values()
            effective_start = max(
                minimum_signal_start,
                _utc(common[0]) + pd.Timedelta(days=int(spec["lookback_days"]) + 1),
            )
        elif strategy == "ena_mean_reversion":
            frame = prices[symbols[0]]
            warmup_hours = max(int(spec["bollinger_period"]), int(spec["rsi_period"]), int(spec["atr_period"])) + 2
            effective_start = max(minimum_signal_start, _utc(frame.index[0]) + pd.Timedelta(hours=warmup_hours))
        elif strategy == "htf_trend":
            effective_start = minimum_signal_start
        else:
            raise SystemExit(f"unsupported watched strategy: {strategy}")

        windows = _window_set(effective_start, end_exclusive, protocol)
        if not windows:
            raise SystemExit(f"no valid historical windows for {strategy}")

        provenance["candidates"][strategy] = {
            "candidate_id": candidate["candidate_id"],
            "candidate_path": cfg["candidate_path"],
            "candidate_file_sha256": candidate_file_sha,
            "candidate_spec_sha256": candidate.get("spec_sha256"),
            "history_start_requested_utc": _iso(history_start),
            "effective_signal_start_utc": _iso(effective_start),
            "interval": interval,
            "symbols": symbols,
            "price_coverage": _data_coverage(prices),
            "funding_coverage": _data_coverage(funding) if funding else {},
            "source_sha256": source_hashes,
            "window_count": len(windows),
            "cost_cases_bps": cost_cases,
        }

        for window in windows:
            start = _utc(window["start"])
            end = _utc(window["end"])
            as_of = end - pd.Timedelta(seconds=1)
            for cost_bps in cost_cases:
                stress_candidate = _stress_candidate(
                    candidate,
                    window_start=start,
                    history_start=history_start,
                    cost_bps=cost_bps,
                    protocol_sha256=protocol_sha,
                )
                if strategy == "ena_mean_reversion":
                    frame = prices[symbols[0]]
                    frame_slice = frame[frame.index < end]
                    report = build_ena_report(
                        frame_slice,
                        stress_candidate,
                        candidate_file_sha256=candidate_file_sha,
                        source_sha256=source_hashes[f"{symbols[0]}:{interval}"],
                        as_of_utc=as_of,
                    )
                elif strategy == "htf_trend":
                    frame_slice = {symbol: frame[frame.index < end] for symbol, frame in prices.items()}
                    funding_slice = {symbol: frame[frame.index < end] for symbol, frame in funding.items()}
                    report = build_htf_report(
                        frame_slice,
                        funding_slice,
                        stress_candidate,
                        as_of_utc=as_of,
                        candidate_file_sha256=candidate_file_sha,
                        source_sha256=source_hashes,
                    )
                else:
                    frame_slice = {symbol: frame[frame.index < end] for symbol, frame in prices.items()}
                    funding_slice = {symbol: frame[frame.index < end] for symbol, frame in funding.items()}
                    report = build_cross_sectional_report(
                        frame_slice,
                        funding_slice,
                        stress_candidate,
                        as_of_utc=as_of,
                        candidate_file_sha256=candidate_file_sha,
                        source_sha256=source_hashes,
                    )

                wrapper = {
                    "schema_version": 1,
                    "experiment": "frozen-candidate-long-backtest-v1",
                    "strategy": strategy,
                    "source_candidate_id": candidate["candidate_id"],
                    "source_candidate_spec_sha256": candidate.get("spec_sha256"),
                    "protocol_sha256": protocol_sha,
                    "window": {
                        "name": window["name"],
                        "kind": window["kind"],
                        "start_utc": _iso(start),
                        "end_exclusive_utc": _iso(end),
                        "duration_days": float((end - start) / pd.Timedelta(days=1)),
                        "position_state_at_start": "flat",
                    },
                    "cost_bps": float(cost_bps),
                    "is_exact_frozen_cost_case": math.isclose(cost_bps, frozen_cost),
                    "metrics": _summary_from_report(strategy, report),
                    "engine_report": report,
                    "claims": {
                        "retrospective_development_stress_only": True,
                        "untouched_oos": False,
                        "parameter_retuning": False,
                        "window_or_cost_selected_by_pnl": False,
                        "profitable_edge_established": False,
                        "live_order_transmission_supported": False,
                    },
                }
                safe_window = str(window["name"]).replace("/", "_")
                cost_label = str(int(cost_bps)) if float(cost_bps).is_integer() else str(cost_bps).replace(".", "p")
                report_path = reports_dir / strategy / f"{safe_window}_cost_{cost_label}bps.json"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(wrapper, indent=2, allow_nan=False), encoding="utf-8")

                metrics = wrapper["metrics"]
                summaries.append(
                    {
                        "strategy": strategy,
                        "source_candidate_id": candidate["candidate_id"],
                        "window_name": window["name"],
                        "window_kind": window["kind"],
                        "start_utc": _iso(start),
                        "end_exclusive_utc": _iso(end),
                        "duration_days": wrapper["window"]["duration_days"],
                        "cost_bps": float(cost_bps),
                        "is_exact_frozen_cost_case": wrapper["is_exact_frozen_cost_case"],
                        "metrics": metrics,
                        "report_path": str(report_path),
                    }
                )

    summary_payload = {
        **provenance,
        "cell_count": len(summaries),
        "all_predeclared_cells_retained": True,
        "cells": summaries,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, allow_nan=False), encoding="utf-8"
    )

    flat_rows: list[dict[str, Any]] = []
    for row in summaries:
        metrics = row["metrics"]
        flat = {key: value for key, value in row.items() if key != "metrics"}
        for key, value in metrics.items():
            if isinstance(value, (dict, list)):
                flat[key] = json.dumps(value, sort_keys=True, allow_nan=False)
            else:
                flat[key] = value
        flat_rows.append(flat)
    pd.DataFrame(flat_rows).to_csv(output_dir / "summary.csv", index=False)

    primary = [
        row for row in summaries
        if row["window_name"] == "full_available" and bool(row["is_exact_frozen_cost_case"])
    ]
    print(
        json.dumps(
            {
                "protocol": protocol["protocol_name"],
                "cell_count": len(summaries),
                "primary_full_history_exact_cost": primary,
                "claims": protocol["claims"],
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

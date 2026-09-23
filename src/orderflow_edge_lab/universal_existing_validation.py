from __future__ import annotations

"""Compatibility and diagnostic runner for the already-frozen price strategies.

This module deliberately keeps the legacy engine in the comparison path.  It is
not a replacement for the evidence-v2 audit and it does not select parameters.
Its purpose is to make the Universal Backtest Framework reviewable against the
existing implementation on one immutable, target-venue data snapshot.
"""

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import backtest as legacy_backtest
from orderflow_edge_lab.strategy_tournament import generate_target_position
from orderflow_edge_lab.universal_accounting_audit import audit_accounting
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    FunctionStrategy,
    legacy_strategy,
    run_backtest,
)


class UniversalExistingValidationError(ValueError):
    pass


REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _interval_delta(interval: str) -> pd.Timedelta:
    try:
        delta = pd.Timedelta(interval)
    except ValueError as exc:
        raise UniversalExistingValidationError(f"unsupported interval: {interval}") from exc
    if delta <= pd.Timedelta(0):
        raise UniversalExistingValidationError("interval must be positive")
    return delta


def load_protocol(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UniversalExistingValidationError(f"cannot read protocol {config_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UniversalExistingValidationError("protocol must be a JSON object")
    for key in ("protocol_name", "data", "costs_bps", "fold_days", "strategies"):
        if key not in value:
            raise UniversalExistingValidationError(f"protocol missing {key!r}")
    data = value["data"]
    if not isinstance(data, dict):
        raise UniversalExistingValidationError("protocol data must be an object")
    for key in ("source", "start", "end_exclusive", "interval", "symbols"):
        if key not in data:
            raise UniversalExistingValidationError(f"protocol data missing {key!r}")
    if "mexc" not in str(data["source"]).lower():
        raise UniversalExistingValidationError("compatibility runner requires the frozen MEXC source")
    costs = value["costs_bps"]
    if not isinstance(costs, list) or not costs:
        raise UniversalExistingValidationError("costs_bps must be a non-empty list")
    if any(not np.isfinite(float(cost)) or float(cost) < 0.0 for cost in costs):
        raise UniversalExistingValidationError("costs_bps must be finite and non-negative")
    if int(value["fold_days"]) <= 0:
        raise UniversalExistingValidationError("fold_days must be positive")
    symbols = data["symbols"]
    normalized_symbols = [str(symbol).upper() for symbol in symbols] if isinstance(symbols, list) else []
    if not isinstance(symbols, list) or not symbols or len(set(normalized_symbols)) != len(symbols):
        raise UniversalExistingValidationError("data.symbols must be a non-empty unique list")
    strategies = value["strategies"]
    if not isinstance(strategies, list) or not strategies:
        raise UniversalExistingValidationError("strategies must be a non-empty list")
    for spec in strategies:
        if not isinstance(spec, dict) or not all(k in spec for k in ("audit_id", "family", "parameters")):
            raise UniversalExistingValidationError("each strategy needs audit_id, family and parameters")
    _interval_delta(str(data["interval"]))
    window = _as_utc(data["end_exclusive"]) - _as_utc(data["start"])
    if window <= pd.Timedelta(0):
        raise UniversalExistingValidationError("data end_exclusive must be after start")
    if window % _interval_delta(str(data["interval"])) != pd.Timedelta(0):
        raise UniversalExistingValidationError("data window is not an exact number of intervals")
    return value


def _load_frame(path: Path, *, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError) as exc:
        raise UniversalExistingValidationError(f"cannot read {path}: {exc}") from exc
    if "timestamp" not in frame.columns:
        raise UniversalExistingValidationError(f"{path}: missing timestamp")
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise UniversalExistingValidationError(f"{path}: missing columns {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise UniversalExistingValidationError(f"{path}: invalid timestamp")
    frame = frame.set_index("timestamp")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise UniversalExistingValidationError(f"{path}: timestamps are not unique and increasing")
    for column in REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(REQUIRED_COLUMNS)].isna().any().any():
        raise UniversalExistingValidationError(f"{path}: non-numeric market value")
    if not np.isfinite(frame[list(REQUIRED_COLUMNS)].to_numpy(dtype=float)).all():
        raise UniversalExistingValidationError(f"{path}: non-finite market value")
    if (frame[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise UniversalExistingValidationError(f"{path}: non-positive OHLC")
    interval_delta = _interval_delta(interval)
    if frame.index.max() != end - interval_delta:
        raise UniversalExistingValidationError(
            f"{path}: incomplete requested window; got {frame.index.min()} to {frame.index.max()} ({len(frame)} rows), "
            f"expected a trailing endpoint at {end - interval_delta}"
        )
    if len(frame) > 1 and not np.all(np.diff(frame.index.view("int64")) == interval_delta.value):
        raise UniversalExistingValidationError(f"{path}: timestamp gap or unexpected interval")
    frame.attrs["symbol"] = symbol
    frame.attrs["interval"] = interval
    return frame


def load_snapshot(protocol: Mapping[str, Any], data_dir: str | Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    data = protocol["data"]
    root = Path(data_dir)
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UniversalExistingValidationError(f"cannot read data manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("failures"):
        raise UniversalExistingValidationError("data manifest reports failures")
    expected_symbols = [str(symbol).upper() for symbol in data["symbols"]]
    files = manifest.get("files")
    if not isinstance(files, list):
        raise UniversalExistingValidationError("data manifest files must be a list")
    by_symbol: dict[str, Mapping[str, Any]] = {}
    for row in files:
        if not isinstance(row, dict) or "symbol" not in row or "path" not in row or "sha256" not in row:
            raise UniversalExistingValidationError("data manifest has malformed file row")
        symbol = str(row["symbol"]).upper()
        if symbol in by_symbol:
            raise UniversalExistingValidationError(f"duplicate manifest symbol: {symbol}")
        by_symbol[symbol] = row
    if set(by_symbol) != set(expected_symbols):
        raise UniversalExistingValidationError(
            f"manifest symbol set mismatch: expected {expected_symbols}, got {sorted(by_symbol)}"
        )

    start = _as_utc(str(data["start"]))
    end = _as_utc(str(data["end_exclusive"]))
    interval = str(data["interval"])
    if "interval" in manifest and str(manifest["interval"]) != interval:
        raise UniversalExistingValidationError("data manifest interval does not match frozen protocol")
    if "start" in manifest and _as_utc(str(manifest["start"])) != start:
        raise UniversalExistingValidationError("data manifest start does not match frozen protocol")
    if "end_exclusive" in manifest and _as_utc(str(manifest["end_exclusive"])) != end:
        raise UniversalExistingValidationError("data manifest end does not match frozen protocol")
    coverage = data.get("coverage", {})
    if not isinstance(coverage, dict):
        raise UniversalExistingValidationError("data.coverage must be an object")
    full_window_symbols = {str(symbol).upper() for symbol in coverage.get("full_window_symbols", expected_symbols)}
    allow_leading_missing_symbols = {str(symbol).upper() for symbol in coverage.get("allow_leading_missing_symbols", [])}
    expected_symbol_set = set(expected_symbols)
    if full_window_symbols & allow_leading_missing_symbols:
        raise UniversalExistingValidationError("coverage policy cannot classify a symbol in both groups")
    if full_window_symbols | allow_leading_missing_symbols != expected_symbol_set:
        raise UniversalExistingValidationError("coverage policy must classify every frozen symbol")
    try:
        minimum_rows = int(coverage.get("minimum_rows", 100))
    except (TypeError, ValueError) as exc:
        raise UniversalExistingValidationError("coverage.minimum_rows must be a positive integer") from exc
    if minimum_rows <= 0:
        raise UniversalExistingValidationError("coverage.minimum_rows must be a positive integer")
    frames: dict[str, pd.DataFrame] = {}
    checked_files: list[dict[str, Any]] = []
    for symbol in expected_symbols:
        row = by_symbol[symbol]
        path = root / str(row["path"])
        if path.name != f"{symbol}_{interval}.csv" or not path.is_file():
            raise UniversalExistingValidationError(f"manifest path mismatch or missing file for {symbol}: {path}")
        actual_hash = _sha256_file(path)
        if actual_hash != str(row["sha256"]):
            raise UniversalExistingValidationError(f"hash mismatch for {symbol}: {actual_hash} != {row['sha256']}")
        frame = _load_frame(path, symbol=symbol, interval=interval, start=start, end=end)
        first_timestamp = frame.index.min()
        if symbol in full_window_symbols and first_timestamp != start:
            raise UniversalExistingValidationError(f"{symbol}: unexpected leading coverage gap")
        if symbol in allow_leading_missing_symbols and first_timestamp < start:
            raise UniversalExistingValidationError(f"{symbol}: data begins before frozen start")
        if len(frame) < minimum_rows:
            raise UniversalExistingValidationError(f"{symbol}: fewer than {minimum_rows} usable bars")
        if int(row.get("rows", len(frame))) != len(frame):
            raise UniversalExistingValidationError(f"manifest row count mismatch for {symbol}")
        frames[symbol] = frame
        checked_files.append(
            {
                "symbol": symbol,
                "path": path.name,
                "sha256": actual_hash,
                "rows": len(frame),
                "first_timestamp": first_timestamp.isoformat(),
                "last_timestamp": frame.index.max().isoformat(),
                "full_requested_window": first_timestamp == start,
            }
        )
    return frames, {"manifest_path": str(manifest_path), "files": checked_files}


def _same_value(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) or isinstance(right, str):
        return left == right
    return bool(np.isclose(float(left), float(right), rtol=0.0, atol=tolerance, equal_nan=True))


def _metric_parity(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    checks = {key: _same_value(old.get(key), new.get(key)) for key in ("trades", "total_return", "expectancy_bps", "max_drawdown", "win_rate", "profit_factor")}
    return {"passed": all(checks.values()), "checks": checks}


def _prefix_causality(frame: pd.DataFrame, family: str, params: Mapping[str, Any], warmup: int) -> dict[str, Any]:
    full = generate_target_position(frame, family, params).astype(float)
    candidate_cuts = [max(warmup + 1, len(frame) // 3), len(frame) // 2, (2 * len(frame)) // 3]
    cuts = sorted({cut for cut in candidate_cuts if warmup < cut < len(frame)})
    rows = []
    for cut in cuts:
        prefix = frame.iloc[:cut]
        observed = generate_target_position(prefix, family, params).astype(float)
        expected = full.iloc[:cut]
        passed = bool(np.array_equal(observed.to_numpy(), expected.to_numpy()))
        rows.append({"prefix_rows": cut, "passed": passed})
    return {"sample_count": len(rows), "all_passed": all(row["passed"] for row in rows), "samples": rows}


def _fold_diagnostics(
    frame: pd.DataFrame,
    strategy: Any,
    params: Mapping[str, Any],
    execution: ExecutionModel,
    fold_days: int,
) -> dict[str, Any]:
    start = frame.index.min().normalize()
    end_exclusive = frame.index.max() + pd.Timedelta(nanoseconds=1)
    delta = pd.Timedelta(days=int(fold_days))
    rows = []
    cursor = start
    while cursor < end_exclusive:
        nxt = min(cursor + delta, end_exclusive)
        window = frame[(frame.index >= cursor) & (frame.index < nxt)]
        if len(window) < max(3, int(strategy.warmup_bars)):
            rows.append({"start": cursor.isoformat(), "end": nxt.isoformat(), "status": "insufficient_warmup", "bars": len(window)})
        else:
            result = run_backtest(window, strategy, params, execution)
            rows.append(
                {
                    "start": cursor.isoformat(),
                    "end": nxt.isoformat(),
                    "status": "diagnostic",
                    "bars": len(window),
                    "trades": result.get("trades", 0),
                    "expectancy_bps": result.get("expectancy_bps"),
                    "total_return": result.get("total_return"),
                    "cold_start_reset": True,
                }
            )
        cursor = nxt
    usable = [row for row in rows if row["status"] == "diagnostic" and row.get("expectancy_bps") is not None]
    ev = [float(row["expectancy_bps"]) for row in usable]
    return {
        "fold_days": int(fold_days),
        "fold_count": len(rows),
        "usable_fold_count": len(usable),
        "positive_fold_fraction": sum(value > 0.0 for value in ev) / len(ev) if ev else None,
        "median_fold_expectancy_bps": float(np.median(ev)) if ev else None,
        "semantics": "descriptive_cold_start_fold_diagnostic_not_OOS",
        "folds": rows,
    }


def _reversed_control(frame: pd.DataFrame, family: str, params: Mapping[str, Any], execution: ExecutionModel) -> dict[str, Any]:
    target = -generate_target_position(frame, family, params).astype(float)
    strategy = FunctionStrategy(f"{family}@reversed", lambda _frame, _params, value=target: value, warmup_bars=100)
    result = run_backtest(frame, strategy, params, execution)
    return {key: result.get(key) for key in ("trades", "expectancy_bps", "total_return", "max_drawdown", "win_rate", "profit_factor")}


def run_validation(protocol: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], *, protocol_path: str | Path) -> dict[str, Any]:
    costs = [float(value) for value in protocol["costs_bps"]]
    results: list[dict[str, Any]] = []
    all_passed = True
    for spec in protocol["strategies"]:
        family = str(spec["family"])
        params = dict(spec["parameters"])
        strategy = legacy_strategy(family)
        strategy_rows = []
        for cost in costs:
            execution = ExecutionModel(round_trip_cost_bps=cost)
            symbol_rows = []
            for symbol in sorted(frames):
                frame = frames[symbol]
                old = legacy_backtest(frame, family, params, cost)
                new = run_backtest(frame, strategy, params, execution)
                old_target = generate_target_position(frame, family, params).astype(float)
                new_target = strategy.generate_target(frame, params).reindex(frame.index).fillna(0.0).astype(float)
                target_equal = bool(np.array_equal(old_target.to_numpy(), new_target.to_numpy()))
                parity = _metric_parity(old, new)
                prefix_causality = _prefix_causality(frame, family, params, strategy.warmup_bars)
                accounting_audit = audit_accounting(frame, strategy, params, execution)
                row_passed = bool(target_equal and parity["passed"] and prefix_causality["all_passed"])
                all_passed = all_passed and row_passed
                symbol_rows.append(
                    {
                        "symbol": symbol,
                        "passed": row_passed,
                        "target_equal": target_equal,
                        "legacy": {key: old.get(key) for key in ("trades", "expectancy_bps", "total_return", "max_drawdown", "win_rate", "profit_factor")},
                        "universal": {key: new.get(key) for key in ("trades", "expectancy_bps", "total_return", "max_drawdown", "win_rate", "profit_factor")},
                        "metric_parity": parity,
                        "prefix_causality": prefix_causality,
                        "accounting_audit": accounting_audit,
                    }
                )
            ordered_returns = [row["universal"]["total_return"] for row in symbol_rows if row["universal"]["total_return"] is not None]
            cost_monotonic = True
            if strategy_rows:
                previous = strategy_rows[-1].get("median_total_return")
                current = float(np.median(ordered_returns)) if ordered_returns else None
                cost_monotonic = previous is None or current is None or current <= float(previous) + 1e-12
            else:
                current = float(np.median(ordered_returns)) if ordered_returns else None
            if not cost_monotonic:
                all_passed = False
            strategy_rows.append(
                {
                    "cost_bps": cost,
                    "symbols": symbol_rows,
                    "median_total_return": current,
                    "cost_monotonic_vs_previous": cost_monotonic,
                    "reversed_control": {
                        symbol: _reversed_control(frames[symbol], family, params, execution)
                        for symbol in sorted(frames)
                    },
                    "fold_diagnostics": {
                        symbol: _fold_diagnostics(frames[symbol], strategy, params, execution, int(protocol["fold_days"]))
                        for symbol in sorted(frames)
                    },
                }
            )
        results.append(
            {
                "audit_id": str(spec["audit_id"]),
                "family": family,
                "parameters": params,
                "role": spec.get("role"),
                "cost_cases": strategy_rows,
            }
        )
    return {
        "schema_version": 1,
        "protocol_name": str(protocol["protocol_name"]),
        "protocol_path": str(protocol_path),
        "status": "compatibility_pass" if all_passed else "compatibility_fail",
        "compatibility_pass": all_passed,
        "strategies": results,
        "claims": {
            "existing_strategy_definitions_unchanged": True,
            "legacy_universal_compatibility_checked": True,
            "accounting_audit_included": True,
            "canonical_economic_accounting_established": False,
            "coverage_policy_checked": True,
            "leading_listing_gaps_are_not_silent": True,
            "folds_are_descriptive_cold_start_diagnostics": True,
            "prefix_causality_is_sampled_only": True,
            "development_only": True,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
        },
    }


def build_report(protocol_path: str | Path, data_dir: str | Path) -> dict[str, Any]:
    protocol = load_protocol(protocol_path)
    frames, snapshot = load_snapshot(protocol, data_dir)
    report = run_validation(protocol, frames, protocol_path=protocol_path)
    report["data"] = {
        "source": protocol["data"]["source"],
        "interval": protocol["data"]["interval"],
        "start": protocol["data"]["start"],
        "end_exclusive": protocol["data"]["end_exclusive"],
        "symbols": sorted(frames),
        "snapshot": snapshot,
    }
    report["protocol_sha256"] = _sha256_file(Path(protocol_path))
    return report

from __future__ import annotations

from collections import Counter
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import enrich_trade_geometry
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    legacy_strategy,
    run_canonical_backtest,
)


class Vol8PayoffAmplitudeForwardError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _validate_frame(
    frame: pd.DataFrame,
    symbol: str,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise Vol8PayoffAmplitudeForwardError(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise Vol8PayoffAmplitudeForwardError(f"{symbol}: duplicate timestamps")
    required = {"open", "high", "low", "close"}
    if not required.issubset(out.columns):
        raise Vol8PayoffAmplitudeForwardError(f"{symbol}: missing OHLC columns")
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    values = out[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise Vol8PayoffAmplitudeForwardError(f"{symbol}: invalid OHLC values")
    boundary = as_of.floor("8h")
    out = out[out.index <= boundary]
    if len(out) < 100:
        raise Vol8PayoffAmplitudeForwardError(f"{symbol}: insufficient warmup bars")
    return out


def _pre_entry_volatility(
    frame: pd.DataFrame,
    entry: pd.Timestamp,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        loc = frame.index.get_loc(entry)
    except KeyError as exc:
        raise Vol8PayoffAmplitudeForwardError(
            f"entry timestamp absent from source frame: {entry.isoformat()}"
        ) from exc
    if not isinstance(loc, (int, np.integer)):
        raise Vol8PayoffAmplitudeForwardError("entry timestamp must resolve uniquely")
    entry_i = int(loc)
    realized_window = int(config["realized_window_bars"])
    rank_history = int(config["rank_history_bars"])
    minimum_history = int(config["minimum_rank_history"])
    current_i = entry_i - 1
    if current_i < realized_window:
        return {
            "pre_entry_volatility": None,
            "pre_entry_volatility_percentile": None,
            "pre_entry_volatility_state": "UNKNOWN",
            "volatility_rank_history_count": 0,
        }

    returns = frame["close"].astype(float).pct_change()
    realized = returns.rolling(
        realized_window,
        min_periods=realized_window,
    ).std(ddof=0)
    current = realized.iloc[current_i]
    if current is None or not math.isfinite(float(current)):
        return {
            "pre_entry_volatility": None,
            "pre_entry_volatility_percentile": None,
            "pre_entry_volatility_state": "UNKNOWN",
            "volatility_rank_history_count": 0,
        }

    start = max(0, current_i - rank_history)
    history = pd.to_numeric(realized.iloc[start:current_i], errors="coerce").dropna()
    count = len(history)
    if count < minimum_history:
        return {
            "pre_entry_volatility": float(current),
            "pre_entry_volatility_percentile": None,
            "pre_entry_volatility_state": "UNKNOWN",
            "volatility_rank_history_count": count,
        }

    arr = history.to_numpy(dtype=float)
    current_f = float(current)
    less = int(np.sum(arr < current_f))
    equal = int(np.sum(arr == current_f))
    percentile = (less + 0.5 * equal) / count
    q33, q67 = np.quantile(arr, [1.0 / 3.0, 2.0 / 3.0])
    state = (
        "LOW"
        if current_f <= float(q33)
        else "HIGH"
        if current_f >= float(q67)
        else "MID"
    )
    return {
        "pre_entry_volatility": current_f,
        "pre_entry_volatility_percentile": float(percentile),
        "pre_entry_volatility_state": state,
        "volatility_rank_history_count": count,
    }


def _partition_trades(
    trades: Sequence[Mapping[str, Any]],
    start: pd.Timestamp,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    completed: list[Mapping[str, Any]] = []
    open_snapshots: list[Mapping[str, Any]] = []
    for trade in trades:
        entry = _utc(trade["entry"])
        if entry < start:
            continue
        if bool(trade.get("terminal_liquidation")):
            open_snapshots.append(trade)
        else:
            completed.append(trade)
    return completed, open_snapshots


def _finite_pairs(
    rows: Sequence[Mapping[str, Any]],
    target: str,
) -> tuple[np.ndarray, np.ndarray]:
    x: list[float] = []
    y: list[float] = []
    for row in rows:
        percentile = row.get("pre_entry_volatility_percentile")
        value = row.get(target)
        if percentile is None or value is None:
            continue
        px = float(percentile)
        py = float(value)
        if math.isfinite(px) and math.isfinite(py):
            x.append(px)
            y.append(py)
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _spearman(
    rows: Sequence[Mapping[str, Any]],
    target: str,
) -> float | None:
    x, y = _finite_pairs(rows, target)
    if len(x) < 2 or np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
        return None
    rx = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    ry = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    value = float(np.corrcoef(rx, ry)[0, 1])
    return value if math.isfinite(value) else None


def _median(values: Sequence[float]) -> float | None:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return float(np.median(finite)) if finite else None


def _state_summary(
    rows: Sequence[Mapping[str, Any]],
    state: str,
) -> dict[str, Any]:
    selected = [
        row for row in rows
        if str(row.get("pre_entry_volatility_state")) == state
    ]
    net = [float(row["net_bps"]) for row in selected]
    mfe = [float(row["mfe_bps"]) for row in selected]
    mae = [float(row["abs_mae_bps"]) for row in selected]
    winner_capture = [
        float(row["winner_gross_to_mfe_ratio"])
        for row in selected
        if row.get("winner_gross_to_mfe_ratio") is not None
    ]
    time_to_mfe = [
        float(row["time_to_mfe_hours"])
        for row in selected
        if row.get("time_to_mfe_hours") is not None
    ]
    return {
        "state": state,
        "completed_trade_count": len(selected),
        "observed_symbol_count": len({str(row["symbol"]) for row in selected}),
        "win_rate": (
            sum(value > 0.0 for value in net) / len(net)
            if net else None
        ),
        "correct_direction_rate": (
            sum(bool(row["correct_direction"]) for row in selected) / len(selected)
            if selected else None
        ),
        "expectancy_bps": float(np.mean(net)) if net else None,
        "median_mfe_bps": _median(mfe),
        "median_abs_mae_bps": _median(mae),
        "median_winner_gross_to_mfe_ratio": _median(winner_capture),
        "median_time_to_mfe_hours": _median(time_to_mfe),
    }


def _assign_blocks(
    rows: Sequence[dict[str, Any]],
    *,
    start: pd.Timestamp,
    block_days: int,
) -> list[int]:
    block = pd.Timedelta(days=block_days)
    blocks: set[int] = set()
    for row in rows:
        entry = _utc(row["entry"])
        block_id = int((entry - start) // block)
        row["_block_id"] = block_id
        blocks.add(block_id)
    return sorted(blocks)


def _bootstrap_correlations(
    rows: Sequence[Mapping[str, Any]],
    blocks: Sequence[int],
    *,
    replicates: int,
    seed: int,
    ci: Sequence[float],
) -> dict[str, Any]:
    targets = (
        "mfe_bps",
        "abs_mae_bps",
        "correct_direction_numeric",
    )
    output = {
        target: {"lower": None, "upper": None, "valid_replicates": 0}
        for target in targets
    }
    if not blocks or replicates <= 0:
        return output
    rng = np.random.default_rng(seed)
    block_arr = np.asarray(blocks, dtype=int)
    samples: dict[str, list[float]] = {target: [] for target in targets}
    for _ in range(replicates):
        chosen = rng.choice(block_arr, size=len(block_arr), replace=True)
        weights = Counter(int(value) for value in chosen)
        sampled: list[Mapping[str, Any]] = []
        for row in rows:
            weight = int(weights.get(int(row["_block_id"]), 0))
            if weight > 0:
                sampled.extend([row] * weight)
        for target in targets:
            value = _spearman(sampled, target)
            if value is not None:
                samples[target].append(value)
    for target, values in samples.items():
        if values:
            output[target] = {
                "lower": float(np.quantile(values, float(ci[0]))),
                "upper": float(np.quantile(values, float(ci[1]))),
                "valid_replicates": len(values),
            }
    return output


def _review_progress(
    rows: Sequence[Mapping[str, Any]],
    *,
    start: pd.Timestamp,
    as_of: pd.Timestamp,
    symbols: Sequence[str],
    distinct_blocks: int,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    rule = config["review_rule"]
    days_elapsed = (
        max(0, int((as_of - start).total_seconds() // 86_400.0))
        if as_of >= start else 0
    )
    observed = sorted({str(row["symbol"]) for row in rows})
    requirements = {
        "calendar_days": {
            "observed": days_elapsed,
            "required": int(rule["minimum_calendar_days"]),
            "met": days_elapsed >= int(rule["minimum_calendar_days"]),
        },
        "completed_trades": {
            "observed": len(rows),
            "required": int(rule["minimum_completed_trades"]),
            "met": len(rows) >= int(rule["minimum_completed_trades"]),
        },
        "observed_symbols": {
            "observed": len(observed),
            "required": int(rule["minimum_observed_symbols"]),
            "met": len(observed) >= int(rule["minimum_observed_symbols"]),
        },
        "distinct_7d_entry_blocks": {
            "observed": distinct_blocks,
            "required": int(rule["minimum_distinct_7d_entry_blocks"]),
            "met": distinct_blocks >= int(rule["minimum_distinct_7d_entry_blocks"]),
        },
    }
    ready = all(bool(item["met"]) for item in requirements.values())
    return {
        "requirements": requirements,
        "ready_for_review": ready,
        "formal_output": "READY_FOR_REVIEW" if ready else "WITHHELD",
        "early_pass_fail_permitted": False,
        "observed_symbols": observed,
        "frozen_symbol_universe_size": len(symbols),
    }


def build_forward_report(
    config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of = _utc(as_of_utc)
    symbols = [str(value) for value in config["source"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise Vol8PayoffAmplitudeForwardError(f"missing symbol frames: {missing}")
    clean = {
        symbol: _validate_frame(frames[symbol], symbol, as_of)
        for symbol in symbols
    }

    strategy_cfg = config["strategy"]
    if str(strategy_cfg["audit_id"]) != "VOL8":
        raise Vol8PayoffAmplitudeForwardError("v1 watch requires audit_id VOL8")
    strategy = legacy_strategy(str(strategy_cfg["family"]))
    params = dict(strategy_cfg["parameters"])
    cost = float(strategy_cfg["round_trip_cost_bps"])

    completed_rows: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        result = run_canonical_backtest(
            clean[symbol],
            strategy,
            params,
            ExecutionModel(
                round_trip_cost_bps=cost,
                max_abs_position=float(strategy_cfg.get("max_abs_position", 1.0)),
            ),
        )
        accounting = result.get("accounting") or {}
        if result.get("trades", 0) and int(accounting.get("version") or 0) != 2:
            raise Vol8PayoffAmplitudeForwardError(
                f"{symbol}: canonical accounting v2 required"
            )
        completed, open_snapshots = _partition_trades(
            result.get("trades_ledger") or [],
            start,
        )
        for trade in completed:
            geometry = enrich_trade_geometry(
                trade,
                clean[symbol],
                strategy_id="VOL8",
                symbol=symbol,
                cost_bps=cost,
                btc_frame=None,
                volatility_config=config["causal_pre_entry_volatility"],
            )
            vol = _pre_entry_volatility(
                clean[symbol],
                _utc(trade["entry"]),
                config["causal_pre_entry_volatility"],
            )
            if (
                str(geometry["pre_entry_volatility_state"])
                != str(vol["pre_entry_volatility_state"])
            ):
                raise Vol8PayoffAmplitudeForwardError(
                    f"{symbol}: volatility-state implementations disagree"
                )
            row = {
                **geometry,
                **vol,
                "correct_direction_numeric": (
                    1.0 if bool(geometry["correct_direction"]) else 0.0
                ),
            }
            completed_rows.append(row)
        for trade in open_snapshots:
            open_rows.append(
                {
                    "symbol": symbol,
                    "entry": _utc(trade["entry"]).isoformat(),
                    "side": int(trade["side"]),
                    "terminal_liquidation": True,
                    "scored_completed_trade": False,
                }
            )

    completed_rows.sort(key=lambda row: (str(row["entry"]), str(row["symbol"])))
    block_cfg = config["reporting"]["bootstrap"]
    blocks = _assign_blocks(
        completed_rows,
        start=start,
        block_days=int(block_cfg["block_days"]),
    )
    correlations = {
        "vol_percentile_vs_mfe": _spearman(completed_rows, "mfe_bps"),
        "vol_percentile_vs_abs_mae": _spearman(completed_rows, "abs_mae_bps"),
        "vol_percentile_vs_correct_direction": _spearman(
            completed_rows,
            "correct_direction_numeric",
        ),
    }
    bootstrap = _bootstrap_correlations(
        completed_rows,
        blocks,
        replicates=int(block_cfg["replicates"]),
        seed=int(block_cfg["seed"]),
        ci=[float(value) for value in block_cfg["confidence_interval"]],
    )
    progress = _review_progress(
        completed_rows,
        start=start,
        as_of=as_of,
        symbols=symbols,
        distinct_blocks=len(blocks),
        config=config,
    )

    if as_of < start:
        status = "PRE_START"
    elif progress["ready_for_review"]:
        status = "READY_FOR_REVIEW"
    else:
        status = "ACCUMULATING"

    per_symbol = Counter(str(row["symbol"]) for row in completed_rows)
    return {
        "schema_version": 1,
        "analysis": "vol8_payoff_amplitude_forward_v1",
        "watch_id": str(config["watch_id"]),
        "status": status,
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "strategy": dict(strategy_cfg),
        "completed_trade_count": len(completed_rows),
        "open_post_start_snapshot_count": len(open_rows),
        "observed_symbol_count": len(per_symbol),
        "per_symbol_completed_trade_count": dict(sorted(per_symbol.items())),
        "distinct_7d_entry_block_count": len(blocks),
        "correlations": correlations,
        "bootstrap_correlation_ci": {
            "vol_percentile_vs_mfe": bootstrap["mfe_bps"],
            "vol_percentile_vs_abs_mae": bootstrap["abs_mae_bps"],
            "vol_percentile_vs_correct_direction": bootstrap[
                "correct_direction_numeric"
            ],
        },
        "by_pre_entry_volatility_state": [
            _state_summary(completed_rows, state)
            for state in ("LOW", "MID", "HIGH", "UNKNOWN")
        ],
        "review_progress": progress,
        "completed_trades": [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in completed_rows
        ],
        "open_terminal_snapshots_not_scored": open_rows,
        "claims": {
            **dict(config["claims"]),
            "pre_start_entries_excluded": True,
            "terminal_liquidations_excluded_from_completed_scoring": True,
            "volatility_state_does_not_gate_trade_generation": True,
            "volatility_state_does_not_change_position_size": True,
            "formal_strategy_verdict": "WITHHELD",
        },
    }

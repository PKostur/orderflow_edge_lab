"""Payoff geometry v1.1 (protocol ``universal-payoff-geometry-diagnostics-v1``).

Additive, descriptive, non-gating extension of ``payoff_geometry_v1``.  The v1
episode reconstruction, canonical MFE/MAE reconciliation and 71-cell grid are
reused unchanged; this module adds excursion ordering, giveback, a static
capture convention consistent with MFE, tail/skew statistics, effective N, a
strategy x direction split and a shared stationary calendar-day bootstrap.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import (
    _cell_definitions,
    _quantiles,
    _utc,
    _values,
    enrich_trade_geometry,
)
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    legacy_strategy,
    run_canonical_backtest,
)
from orderflow_edge_lab.universal_existing_validation import load_protocol, load_snapshot

ANALYSIS = "payoff_geometry_v1_1"
PROTOCOL_ID = "universal-payoff-geometry-diagnostics-v1"
DISTRIBUTION_FIELDS = (
    "net_bps",
    "static_gross_bps",
    "mfe_bps",
    "abs_mae_bps",
    "giveback_bps",
    "capture_ratio",
    "bars_to_mfe",
    "bars_to_mae",
    "bars_held",
)
EXCURSION_ORDERS = ("MFE_FIRST", "MAE_FIRST", "SAME_BAR", "NO_MFE", "NO_MAE", "NONE")


class PayoffGeometryV11Error(ValueError):
    pass


def _load_config(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("analysis") != ANALYSIS
        or value.get("protocol_id") != PROTOCOL_ID
    ):
        raise PayoffGeometryV11Error("invalid payoff geometry v1.1 config")
    for key, flag in (value.get("claims") or {}).items():
        if key.endswith("_authorized") and bool(flag):
            raise PayoffGeometryV11Error(f"payoff geometry v1.1 must not authorize {key}")
    return value


def _check_frozen_window(
    config: Mapping[str, Any],
    protocol: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of: str | None,
) -> None:
    window = config["frozen_window"]
    start, end = _utc(window["start"]), _utc(window["end_exclusive"])
    data = protocol["data"]
    if _utc(data["start"]) != start or _utc(data["end_exclusive"]) != end:
        raise PayoffGeometryV11Error("source protocol window differs from the frozen v1.1 window")
    for symbol, frame in frames.items():
        if len(frame) and _utc(frame.index.max()) >= end:
            raise PayoffGeometryV11Error(f"{symbol}: bar at or after frozen end_exclusive")
    if as_of is not None and _utc(as_of) > _utc(window["latest_permitted_as_of"]):
        raise PayoffGeometryV11Error("as_of is later than the latest permitted as_of")


def extend_trade_geometry(
    base: Mapping[str, Any],
    trade: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    tolerance_bps: float = 1e-6,
) -> dict[str, Any]:
    """Add v1.1 episode fields to a v1 ``enrich_trade_geometry`` row."""
    entry_loc = int(frame.index.get_loc(_utc(trade["entry"])))
    exit_loc = int(frame.index.get_loc(_utc(trade["exit"])))
    side = int(trade["side"])
    held = frame.iloc[entry_loc:exit_loc]
    opens = frame["open"].astype(float).to_numpy()
    entry_price = float(opens[entry_loc])
    exit_price = float(opens[exit_loc])

    if side > 0:
        favorable = held["high"].astype(float).to_numpy() / entry_price - 1.0
        adverse = held["low"].astype(float).to_numpy() / entry_price - 1.0
    else:
        favorable = 1.0 - held["low"].astype(float).to_numpy() / entry_price
        adverse = 1.0 - held["high"].astype(float).to_numpy() / entry_price
    favorable = np.clip(favorable * 10_000.0, 0.0, None)
    adverse = np.clip(adverse * 10_000.0, None, 0.0)
    mfe, mae = float(base["mfe_bps"]), float(base["mae_bps"])
    bars_to_mfe = (
        int(np.flatnonzero(np.isclose(favorable, mfe, rtol=0.0, atol=1e-8))[0])
        if mfe > 0.0
        else None
    )
    bars_to_mae = (
        int(np.flatnonzero(np.isclose(adverse, mae, rtol=0.0, atol=1e-8))[0])
        if mae < 0.0
        else None
    )
    if bars_to_mfe is None and bars_to_mae is None:
        order = "NONE"
    elif bars_to_mfe is None:
        order = "NO_MFE"
    elif bars_to_mae is None:
        order = "NO_MAE"
    elif bars_to_mfe < bars_to_mae:
        order = "MFE_FIRST"
    elif bars_to_mae < bars_to_mfe:
        order = "MAE_FIRST"
    else:
        order = "SAME_BAR"

    bar_returns = opens[entry_loc + 1 : exit_loc + 1] / opens[entry_loc:exit_loc] - 1.0
    path_gross = (float(np.prod(1.0 + side * bar_returns)) - 1.0) * 10_000.0
    ledger_gross = float(base["gross_bps"])
    if abs(float(trade.get("entry_position", side))) == 1.0 and abs(path_gross - ledger_gross) > tolerance_bps:
        raise PayoffGeometryV11Error(
            f"{base.get('strategy_id')}/{base.get('symbol')} {trade['entry']}: "
            f"ledger gross {ledger_gross:.6f} does not reconcile with bar path {path_gross:.6f}"
        )
    static_gross = side * (exit_price / entry_price - 1.0) * 10_000.0
    return {
        **base,
        "bars_to_mfe": bars_to_mfe,
        "bars_to_mae": bars_to_mae,
        "excursion_order": order,
        "path_gross_bps": path_gross,
        "static_gross_bps": static_gross,
        "short_rebalance_gap_bps": ledger_gross - static_gross,
        "capture_ratio": static_gross / mfe if mfe > 0.0 else None,
        "giveback_bps": mfe - static_gross,
    }


def _top_decile_profit_share(net: Sequence[float]) -> float | None:
    positive_total = sum(v for v in net if v > 0.0)
    if positive_total <= 0.0:
        return None
    k = max(1, math.ceil(0.1 * len(net)))
    top = sorted(net, reverse=True)[:k]
    return sum(v for v in top if v > 0.0) / positive_total


def _skewness(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 3:
        return None
    arr = np.asarray(values, dtype=float)
    sd = float(arr.std(ddof=0))
    if sd == 0.0:
        return None
    g1 = float(np.mean((arr - arr.mean()) ** 3)) / sd**3
    return g1 * math.sqrt(n * (n - 1)) / (n - 2)


def _effective_n(block_ids: Sequence[int]) -> float | None:
    if not block_ids:
        return None
    counts = np.bincount(np.asarray(block_ids, dtype=int) - min(block_ids))
    return float(len(block_ids) ** 2 / np.sum(counts.astype(float) ** 2))


def _stationary_bootstrap_day_weights(
    days: int,
    *,
    mean_block_days: float,
    replicates: int,
    seed: int,
) -> np.ndarray:
    """Politis-Romano circular stationary bootstrap; returns (replicates, days) counts."""
    if days <= 0 or replicates <= 0:
        return np.zeros((max(replicates, 0), max(days, 0)), dtype=np.int64)
    rng = np.random.default_rng(seed)
    p_new = 1.0 / float(mean_block_days)
    new_block = rng.random((replicates, days)) < p_new
    new_block[:, 0] = True
    starts = rng.integers(0, days, size=(replicates, days))
    current = starts[:, 0].copy()
    weights = np.zeros((replicates, days), dtype=np.int64)
    rows = np.arange(replicates)
    for t in range(days):
        if t:
            current = np.where(new_block[:, t], starts[:, t], (current + 1) % days)
        np.add.at(weights, (rows, current), 1)
    return weights


def _weighted_median_rows(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Lower weighted median of ``values`` for each row of ``weights``."""
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    cum = np.cumsum(weights[:, order], axis=1)
    total = cum[:, -1] if cum.shape[1] else np.zeros(len(weights))
    out = np.full(len(weights), np.nan)
    valid = total > 0
    idx = np.argmax(cum >= (total / 2.0)[:, None], axis=1)
    out[valid] = sorted_values[idx[valid]]
    return out


def _bootstrap_block(
    rows: Sequence[Mapping[str, Any]],
    day_weights: np.ndarray,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    boot = config["bootstrap"]
    lo, hi = (float(v) for v in boot["confidence_interval"])
    out: dict[str, Any] = {}
    if not rows or day_weights.size == 0:
        return {f: {"lower": None, "upper": None, "valid_replicates": 0} for f in boot["fields"]}

    def interval(stat: np.ndarray) -> dict[str, Any]:
        stat = stat[np.isfinite(stat)]
        return {
            "lower": float(np.quantile(stat, lo)) if len(stat) else None,
            "upper": float(np.quantile(stat, hi)) if len(stat) else None,
            "valid_replicates": int(len(stat)),
        }

    def weights_for(subset: Sequence[Mapping[str, Any]]) -> np.ndarray:
        return day_weights[:, [int(r["_day"]) for r in subset]].astype(float)

    net = np.array([float(r["net_bps"]) for r in rows])
    w = weights_for(rows)
    total = w.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["expectancy_bps"] = interval(np.where(total > 0, (w @ net) / total, np.nan))
        out["win_rate"] = interval(np.where(total > 0, (w @ (net > 0.0)) / total, np.nan))
    for name, key in (
        ("median_mfe_bps", "mfe_bps"),
        ("median_giveback_bps", "giveback_bps"),
        ("median_capture_ratio", "capture_ratio"),
    ):
        subset = [r for r in rows if r.get(key) is not None]
        if not subset:
            out[name] = {"lower": None, "upper": None, "valid_replicates": 0}
            continue
        values = np.array([float(r[key]) for r in subset])
        out[name] = interval(_weighted_median_rows(values, weights_for(subset)))
    return {f: out[f] for f in boot["fields"]}


def _point_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net = _values(rows, "net_bps")
    mfe = _values(rows, "mfe_bps")
    return {
        "win_rate": sum(v > 0.0 for v in net) / len(net) if net else None,
        "expectancy_bps": float(np.mean(net)) if net else None,
        "median_mfe_bps": float(np.median(mfe)) if mfe else None,
        "p90_mfe_bps": float(np.quantile(mfe, 0.9)) if mfe else None,
        "p10_net_bps": float(np.quantile(net, 0.1)) if net else None,
        "p50_net_bps": float(np.median(net)) if net else None,
        "p90_net_bps": float(np.quantile(net, 0.9)) if net else None,
    }


def _cell_block(
    cell_id: str,
    direction: str,
    rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    day_weights: np.ndarray,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    stats_cfg = config["cell_statistics"]
    quantiles = [float(v) for v in config["quantiles"]]
    net = _values(rows, "net_bps")
    point = _point_stats(rows)
    reference = _point_stats(reference_rows)
    order_counts = {k: 0 for k in EXCURSION_ORDERS}
    for row in rows:
        order_counts[str(row["excursion_order"])] += 1
    minimum = int(stats_cfg["minimum_sufficient_trades"])
    sufficient = len(rows) >= minimum
    effective_n = _effective_n([int(r["_block_id"]) for r in rows])
    return {
        "cell_id": cell_id,
        "direction": direction,
        "raw_n": len(rows),
        "effective_n": effective_n,
        "calendar_block_count": len({int(r["_block_id"]) for r in rows}),
        "sufficiency": "SUFFICIENT" if sufficient else str(stats_cfg["insufficient_label"]),
        "effective_n_sufficiency": (
            "SUFFICIENT"
            if effective_n is not None and effective_n >= minimum
            else str(stats_cfg["insufficient_label"])
        ),
        **point,
        "capture_defined_n": sum(r.get("capture_ratio") is not None for r in rows),
        "top_decile_profit_share": _top_decile_profit_share(net),
        "net_bps_skewness": _skewness(net),
        "excursion_order_counts": order_counts,
        "distributions": {key: _quantiles(_values(rows, key), quantiles) for key in DISTRIBUTION_FIELDS},
        "delta_vs_direction_all": {
            key: (
                point[key] - reference[key]
                if point[key] is not None and reference[key] is not None
                else None
            )
            for key in point
        },
        "bootstrap_ci": _bootstrap_block(rows, day_weights, config),
    }


def _direction_rows(rows: Sequence[Mapping[str, Any]], direction: str) -> list[Mapping[str, Any]]:
    return list(rows) if direction == "ALL" else [r for r in rows if r["side_label"] == direction]


def build_payoff_geometry_v1_1_report(
    protocol_path: str | Path,
    config_path: str | Path,
    v1_config_path: str | Path,
    data_dir: str | Path,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    config = _load_config(config_path)
    v1_config = json.loads(Path(v1_config_path).read_text(encoding="utf-8"))
    if v1_config.get("analysis") != config["extends"]["analysis"]:
        raise PayoffGeometryV11Error("v1 config does not match the extended analysis")
    protocol = load_protocol(protocol_path)
    if str(protocol["protocol_name"]) != str(config["source_protocol"]):
        raise PayoffGeometryV11Error("source protocol mismatch")
    costs = [float(v) for v in config["cost_cases_bps"]]
    if costs != [float(v) for v in protocol["costs_bps"]]:
        raise PayoffGeometryV11Error("cost cases differ from frozen historical protocol")

    frames, snapshot = load_snapshot(protocol, data_dir)
    _check_frozen_window(config, protocol, frames, as_of=as_of)
    btc = frames.get("BTC_USDT")
    cells = _cell_definitions(v1_config)
    directions = [str(d) for d in config["directions"]]
    boot = config["bootstrap"]
    tolerance = float(config["ledger_reconciliation"]["tolerance_bps"])
    block = pd.Timedelta(days=30)

    cost_reports: list[dict[str, Any]] = []
    for cost_index, cost in enumerate(costs):
        rows: list[dict[str, Any]] = []
        censored: dict[str, dict[str, int]] = {}
        for spec in protocol["strategies"]:
            audit_id = str(spec["audit_id"])
            strategy = legacy_strategy(str(spec["family"]))
            censored[audit_id] = {"LONG": 0, "SHORT": 0}
            for symbol in sorted(frames):
                canonical = run_canonical_backtest(
                    frames[symbol],
                    strategy,
                    dict(spec["parameters"]),
                    ExecutionModel(round_trip_cost_bps=cost),
                )
                for trade in canonical.get("trades_ledger") or []:
                    if trade.get("terminal_liquidation"):
                        censored[audit_id]["LONG" if int(trade["side"]) > 0 else "SHORT"] += 1
                        continue
                    base = enrich_trade_geometry(
                        trade,
                        frames[symbol],
                        strategy_id=audit_id,
                        symbol=symbol,
                        cost_bps=cost,
                        btc_frame=btc,
                        volatility_config=v1_config.get("pre_entry_volatility_state"),
                    )
                    rows.append(
                        extend_trade_geometry(base, trade, frames[symbol], tolerance_bps=tolerance)
                    )

        if rows:
            origin = min(r["_entry_timestamp"] for r in rows).normalize()
            for r in rows:
                r["_day"] = int((r["_entry_timestamp"].normalize() - origin).days)
                r["_block_id"] = int((r["_entry_timestamp"] - origin) // block)
            day_count = max(r["_day"] for r in rows) + 1
        else:
            origin, day_count = None, 0
        day_weights = _stationary_bootstrap_day_weights(
            day_count,
            mean_block_days=float(boot["mean_block_days"]),
            replicates=int(boot["replicates"]),
            seed=int(boot["seed"]) + cost_index,
        )

        strategy_reports: list[dict[str, Any]] = []
        for spec in protocol["strategies"]:
            audit_id = str(spec["audit_id"])
            strategy_rows = [r for r in rows if r["strategy_id"] == audit_id]
            gaps = [
                float(r["short_rebalance_gap_bps"]) for r in strategy_rows if r["side_label"] == "SHORT"
            ]
            direction_blocks = []
            for direction in directions:
                d_rows = _direction_rows(strategy_rows, direction)
                direction_blocks.append(
                    {
                        "direction": direction,
                        "cells": [
                            _cell_block(
                                cell_id,
                                direction,
                                [r for r in d_rows if predicate(r)],
                                d_rows,
                                day_weights,
                                config,
                            )
                            for cell_id, predicate in cells
                        ],
                    }
                )
            strategy_reports.append(
                {
                    "audit_id": audit_id,
                    "family": str(spec["family"]),
                    "completed_trade_count": len(strategy_rows),
                    "direction_mix": {
                        "LONG": sum(r["side_label"] == "LONG" for r in strategy_rows),
                        "SHORT": sum(r["side_label"] == "SHORT" for r in strategy_rows),
                    },
                    "right_censored_open_episodes": censored[audit_id],
                    "ledger_reconciliation": {
                        "episodes_checked": len(strategy_rows),
                        "max_abs_path_minus_ledger_bps": max(
                            (abs(r["path_gross_bps"] - r["gross_bps"]) for r in strategy_rows),
                            default=None,
                        ),
                        "short_rebalance_gap_bps": _quantiles(gaps, [0.1, 0.5, 0.9]),
                    },
                    "directions": direction_blocks,
                }
            )
        cost_reports.append(
            {
                "cost_bps": cost,
                "primary_cost_case": bool(np.isclose(cost, float(config["primary_cost_bps"]))),
                "calendar_origin": origin.isoformat() if origin is not None else None,
                "bootstrap_calendar_days": day_count,
                "strategies": strategy_reports,
            }
        )

    contract = {
        "v1_cell_grid": v1_config["cell_grid"],
        "directions": directions,
        "quantiles": config["quantiles"],
        "cell_statistics": config["cell_statistics"],
        "bootstrap": boot,
    }
    return {
        "schema_version": 1,
        "analysis": ANALYSIS,
        "protocol_id": PROTOCOL_ID,
        "status": "descriptive_development_only",
        "as_of": as_of,
        "source_protocol": str(protocol["protocol_name"]),
        "frozen_window": config["frozen_window"],
        "fixed_cell_count_per_strategy_direction": len(cells),
        "cell_set_sha256": sha256(
            json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "episode_fields": config["episode_fields"],
        "cost_cases": cost_reports,
        "data_snapshot": snapshot,
        "claims": dict(config["claims"]),
    }

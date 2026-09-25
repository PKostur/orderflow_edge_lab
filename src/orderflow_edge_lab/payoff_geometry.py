from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.session_metrics import DEFAULT_SESSIONS, session_regime
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    legacy_strategy,
    run_canonical_backtest,
)
from orderflow_edge_lab.universal_existing_validation import (
    load_protocol,
    load_snapshot,
)


class PayoffGeometryError(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise PayoffGeometryError(f"timestamp must be timezone-aware: {value!r}")
    return ts.tz_convert("UTC")


def _alignment(side: int, value: float | None) -> str:
    if value is None or not math.isfinite(value) or value == 0.0:
        return "NEUTRAL"
    direction = 1 if value > 0.0 else -1
    return "ALIGNED" if direction == side else "AGAINST"


def _prior_return(frame: pd.DataFrame, entry_index: int, bars: int) -> float | None:
    if bars <= 0 or entry_index < bars:
        return None
    start = entry_index - bars
    open_price = float(frame["open"].iloc[start])
    close_price = float(frame["close"].iloc[entry_index - 1])
    if not math.isfinite(open_price) or not math.isfinite(close_price) or open_price <= 0.0:
        return None
    return close_price / open_price - 1.0


def _btc_prior_return(frame: pd.DataFrame | None, entry: pd.Timestamp) -> float | None:
    if frame is None or frame.empty:
        return None
    before = frame.index < entry
    if not bool(before.any()):
        return None
    row = frame.loc[before].iloc[-1]
    open_price = float(row["open"])
    close_price = float(row["close"])
    if not math.isfinite(open_price) or not math.isfinite(close_price) or open_price <= 0.0:
        return None
    return close_price / open_price - 1.0


def _prior_volatility_state(
    frame: pd.DataFrame,
    entry_index: int,
    *,
    realized_window_bars: int,
    rank_history_bars: int,
    minimum_rank_history: int,
) -> str:
    if entry_index <= realized_window_bars:
        return "UNKNOWN"
    close = frame["close"].astype(float)
    returns = close.pct_change()
    realized = returns.rolling(
        int(realized_window_bars),
        min_periods=int(realized_window_bars),
    ).std(ddof=0)
    current_i = int(entry_index) - 1
    current = realized.iloc[current_i]
    if current is None or not math.isfinite(float(current)):
        return "UNKNOWN"
    start = max(0, current_i - int(rank_history_bars))
    history = pd.to_numeric(realized.iloc[start:current_i], errors="coerce").dropna()
    if len(history) < int(minimum_rank_history):
        return "UNKNOWN"
    q33, q67 = np.quantile(
        history.to_numpy(dtype=float),
        [1.0 / 3.0, 2.0 / 3.0],
    )
    if float(current) <= float(q33):
        return "LOW"
    if float(current) >= float(q67):
        return "HIGH"
    return "MID"


def _first_extreme_time(
    values: pd.Series,
    *,
    maximize: bool,
) -> pd.Timestamp | None:
    if values.empty:
        return None
    target = float(values.max() if maximize else values.min())
    mask = np.isclose(values.to_numpy(dtype=float), target, rtol=0.0, atol=1e-12)
    positions = np.flatnonzero(mask)
    if len(positions) == 0:
        return None
    return _utc(values.index[int(positions[0])])


def enrich_trade_geometry(
    trade: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    strategy_id: str,
    symbol: str,
    cost_bps: float,
    btc_frame: pd.DataFrame | None,
    volatility_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry = _utc(trade["entry"])
    exit_ts = _utc(trade["exit"])
    try:
        entry_loc = frame.index.get_loc(entry)
        exit_loc = frame.index.get_loc(exit_ts)
    except KeyError as exc:
        raise PayoffGeometryError(
            f"{strategy_id}/{symbol}: trade timestamp absent from source frame"
        ) from exc
    if not isinstance(entry_loc, (int, np.integer)) or not isinstance(
        exit_loc, (int, np.integer)
    ):
        raise PayoffGeometryError("trade timestamps must resolve to unique market rows")
    if int(exit_loc) <= int(entry_loc):
        raise PayoffGeometryError("trade exit must be after entry")

    side = int(trade["side"])
    if side not in (-1, 1):
        raise PayoffGeometryError("trade side must be -1 or 1")

    held = frame.iloc[int(entry_loc) : int(exit_loc)]
    entry_price = float(frame["open"].iloc[int(entry_loc)])
    if held.empty or entry_price <= 0.0:
        raise PayoffGeometryError("trade episode has no observable excursion interval")

    if side > 0:
        favorable = (held["high"].astype(float) / entry_price - 1.0) * 10_000.0
        adverse = (held["low"].astype(float) / entry_price - 1.0) * 10_000.0
    else:
        favorable = (1.0 - held["low"].astype(float) / entry_price) * 10_000.0
        adverse = (1.0 - held["high"].astype(float) / entry_price) * 10_000.0

    favorable = favorable.clip(lower=0.0)
    adverse = adverse.clip(upper=0.0)
    mfe_bps = float(favorable.max())
    mae_bps = float(adverse.min())
    canonical_mfe = float(trade["mfe_bps"])
    canonical_mae = float(trade["mae_bps"])
    if not np.isclose(mfe_bps, canonical_mfe, rtol=1e-10, atol=1e-8):
        raise PayoffGeometryError(
            f"{strategy_id}/{symbol}: reconstructed MFE does not match canonical ledger"
        )
    if not np.isclose(mae_bps, canonical_mae, rtol=1e-10, atol=1e-8):
        raise PayoffGeometryError(
            f"{strategy_id}/{symbol}: reconstructed MAE does not match canonical ledger"
        )

    mfe_time = _first_extreme_time(favorable, maximize=True)
    mae_time = _first_extreme_time(adverse, maximize=False)
    gross_bps = float(trade["gross_bps"])
    abs_mae = abs(mae_bps)
    gross_to_mfe = gross_bps / mfe_bps if mfe_bps > 0.0 else None
    mfe_to_abs_mae = mfe_bps / abs_mae if abs_mae > 0.0 else None
    prior_3 = _prior_return(frame, int(entry_loc), 3)
    btc_prior_1 = _btc_prior_return(btc_frame, entry)
    vol_cfg = dict(volatility_config or {})
    volatility_state = _prior_volatility_state(
        frame,
        int(entry_loc),
        realized_window_bars=int(vol_cfg.get("realized_window_bars", 20)),
        rank_history_bars=int(vol_cfg.get("rank_history_bars", 90)),
        minimum_rank_history=int(vol_cfg.get("minimum_rank_history", 30)),
    )

    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "cost_bps": float(cost_bps),
        "entry": entry.isoformat(),
        "exit": exit_ts.isoformat(),
        "side": side,
        "side_label": "LONG" if side > 0 else "SHORT",
        "outcome_label": "CORRECT" if gross_bps > 0.0 else "INCORRECT",
        "pre_entry_volatility_state": volatility_state,
        "terminal_liquidation": bool(trade.get("terminal_liquidation")),
        "bars_held": int(trade.get("bars_held") or 0),
        "duration_hours": (exit_ts - entry).total_seconds() / 3600.0,
        "gross_bps": gross_bps,
        "net_bps": float(trade["net_bps"]),
        "mfe_bps": mfe_bps,
        "mae_bps": mae_bps,
        "abs_mae_bps": abs_mae,
        "gross_to_mfe_ratio": gross_to_mfe,
        "winner_gross_to_mfe_ratio": (
            gross_to_mfe if gross_bps > 0.0 and gross_to_mfe is not None else None
        ),
        "mfe_to_abs_mae_ratio": mfe_to_abs_mae,
        "time_to_mfe_hours": (
            (mfe_time - entry).total_seconds() / 3600.0 if mfe_time is not None else None
        ),
        "time_to_mae_hours": (
            (mae_time - entry).total_seconds() / 3600.0 if mae_time is not None else None
        ),
        "correct_direction": gross_bps > 0.0,
        "session_regime": session_regime(entry.to_pydatetime(), DEFAULT_SESSIONS),
        "btc_prior_bar_direction": _alignment(side, btc_prior_1),
        "own_prior_3bar_direction": _alignment(side, prior_3),
        "_entry_timestamp": entry,
    }


def _quantiles(values: Sequence[float], levels: Sequence[float]) -> dict[str, float | None]:
    finite = [float(v) for v in values if math.isfinite(float(v))]
    if not finite:
        return {f"p{int(round(q * 100)):02d}": None for q in levels}
    return {
        f"p{int(round(q * 100)):02d}": float(np.quantile(finite, q))
        for q in levels
    }


def _values(rows: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _summary(
    rows: Sequence[Mapping[str, Any]],
    quantiles: Sequence[float],
) -> dict[str, Any]:
    net = _values(rows, "net_bps")
    gross = _values(rows, "gross_bps")
    mfe = _values(rows, "mfe_bps")
    abs_mae = _values(rows, "abs_mae_bps")
    winner_capture = _values(rows, "winner_gross_to_mfe_ratio")
    return {
        "observations": len(rows),
        "symbol_count": len({str(row["symbol"]) for row in rows}),
        "first_entry": min((str(row["entry"]) for row in rows), default=None),
        "last_entry": max((str(row["entry"]) for row in rows), default=None),
        "expectancy_bps": float(np.mean(net)) if net else None,
        "median_trade_bps": float(np.median(net)) if net else None,
        "win_rate": sum(value > 0.0 for value in net) / len(net) if net else None,
        "correct_direction_rate": (
            sum(bool(row.get("correct_direction")) for row in rows) / len(rows)
            if rows
            else None
        ),
        "median_mfe_bps": float(np.median(mfe)) if mfe else None,
        "median_abs_mae_bps": float(np.median(abs_mae)) if abs_mae else None,
        "median_winner_gross_to_mfe_ratio": (
            float(np.median(winner_capture)) if winner_capture else None
        ),
        "median_time_to_mfe_hours": (
            float(np.median(_values(rows, "time_to_mfe_hours")))
            if _values(rows, "time_to_mfe_hours")
            else None
        ),
        "distributions": {
            key: _quantiles(_values(rows, key), quantiles)
            for key in (
                "net_bps",
                "gross_bps",
                "mfe_bps",
                "abs_mae_bps",
                "gross_to_mfe_ratio",
                "winner_gross_to_mfe_ratio",
                "time_to_mfe_hours",
                "time_to_mae_hours",
                "duration_hours",
                "mfe_to_abs_mae_ratio",
            )
        },
    }


def _metric(summary: Mapping[str, Any], key: str) -> float | None:
    value = summary.get(key)
    return None if value is None else float(value)


def _bootstrap_samples(
    blocks: Sequence[int],
    *,
    replicates: int,
    seed: int,
) -> list[Counter[int]]:
    if not blocks or replicates <= 0:
        return []
    rng = np.random.default_rng(seed)
    arr = np.asarray(blocks, dtype=int)
    return [
        Counter(int(v) for v in rng.choice(arr, size=len(arr), replace=True))
        for _ in range(replicates)
    ]


def _bootstrap_ci(
    rows: Sequence[Mapping[str, Any]],
    quantiles: Sequence[float],
    samples: Sequence[Counter[int]],
    ci: Sequence[float],
    fields: Sequence[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        values: list[float] = []
        for weights in samples:
            sampled: list[Mapping[str, Any]] = []
            for row in rows:
                weight = int(weights.get(int(row["_block_id"]), 0))
                if weight > 0:
                    sampled.extend([row] * weight)
            if not sampled:
                continue
            value = _metric(_summary(sampled, quantiles), field)
            if value is not None and math.isfinite(value):
                values.append(value)
        result[field] = {
            "lower": float(np.quantile(values, ci[0])) if values else None,
            "upper": float(np.quantile(values, ci[1])) if values else None,
            "valid_replicates": len(values),
        }
    return result


def _cell_definitions(config: Mapping[str, Any]) -> list[tuple[str, Callable[[Mapping[str, Any]], bool]]]:
    grid = config["cell_grid"]
    regimes = [str(v) for v in grid["session_regimes"]]
    states = [str(v) for v in grid["alignment_states"]]
    volatility_states = [str(v) for v in grid.get("volatility_states", [])]
    outcome_states = [str(v) for v in grid.get("outcome_states", [])]
    side_states = [str(v) for v in grid.get("side_states", [])]
    cells: list[tuple[str, Callable[[Mapping[str, Any]], bool]]] = [
        ("ALL", lambda _row: True)
    ]
    for state in outcome_states:
        cells.append(
            (
                f"OUTCOME={state}",
                lambda row, state=state: row["outcome_label"] == state,
            )
        )
    for state in side_states:
        cells.append(
            (
                f"SIDE={state}",
                lambda row, state=state: row["side_label"] == state,
            )
        )
    for state in volatility_states:
        cells.append(
            (
                f"PRE_ENTRY_VOLATILITY={state}",
                lambda row, state=state: row["pre_entry_volatility_state"] == state,
            )
        )
    for regime in regimes:
        cells.append(
            (
                f"SESSION={regime}",
                lambda row, regime=regime: row["session_regime"] == regime,
            )
        )
    for state in states:
        cells.append(
            (
                f"BTC_PRIOR_BAR={state}",
                lambda row, state=state: row["btc_prior_bar_direction"] == state,
            )
        )
    for state in states:
        cells.append(
            (
                f"OWN_PRIOR_3BAR={state}",
                lambda row, state=state: row["own_prior_3bar_direction"] == state,
            )
        )
    for regime in regimes:
        for state in states:
            cells.append(
                (
                    f"SESSION={regime}|BTC_PRIOR_BAR={state}",
                    lambda row, regime=regime, state=state: (
                        row["session_regime"] == regime
                        and row["btc_prior_bar_direction"] == state
                    ),
                )
            )
    for regime in regimes:
        for state in states:
            cells.append(
                (
                    f"SESSION={regime}|OWN_PRIOR_3BAR={state}",
                    lambda row, regime=regime, state=state: (
                        row["session_regime"] == regime
                        and row["own_prior_3bar_direction"] == state
                    ),
                )
            )
    return cells


def _load_geometry_config(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("analysis") != "payoff_geometry_v1":
        raise PayoffGeometryError("invalid payoff geometry config")
    if not bool((value.get("cell_grid") or {}).get("emit_empty_cells")):
        raise PayoffGeometryError("payoff geometry v1 requires empty cells to be emitted")
    return value


def build_payoff_geometry_report(
    protocol_path: str | Path,
    geometry_config_path: str | Path,
    data_dir: str | Path,
) -> dict[str, Any]:
    protocol = load_protocol(protocol_path)
    geometry = _load_geometry_config(geometry_config_path)
    if str(protocol["protocol_name"]) != str(geometry["source_protocol"]):
        raise PayoffGeometryError("source protocol does not match payoff geometry preregistration")
    protocol_costs = [float(v) for v in protocol["costs_bps"]]
    geometry_costs = [float(v) for v in geometry["cost_cases_bps"]]
    if protocol_costs != geometry_costs:
        raise PayoffGeometryError("cost cases differ from frozen historical protocol")

    frames, snapshot = load_snapshot(protocol, data_dir)
    btc = frames.get("BTC_USDT")
    quantiles = [float(v) for v in geometry["quantiles"]]
    bootstrap = geometry["bootstrap"]
    block_days = int(bootstrap["block_days"])
    replicates = int(bootstrap["replicates"])
    seed = int(bootstrap["seed"])
    ci = [float(v) for v in bootstrap["confidence_interval"]]
    uncertainty_fields = [str(v) for v in geometry["uncertainty_fields"]]
    cells = _cell_definitions(geometry)

    cost_reports: list[dict[str, Any]] = []
    for cost_index, cost in enumerate(geometry_costs):
        all_rows: list[dict[str, Any]] = []
        terminal_counts: dict[str, dict[str, int]] = {}
        for spec in protocol["strategies"]:
            audit_id = str(spec["audit_id"])
            strategy = legacy_strategy(str(spec["family"]))
            params = dict(spec["parameters"])
            terminal_counts[audit_id] = {}
            for symbol in sorted(frames):
                canonical = run_canonical_backtest(
                    frames[symbol],
                    strategy,
                    params,
                    ExecutionModel(round_trip_cost_bps=cost),
                )
                count = 0
                for trade in canonical.get("trades_ledger") or []:
                    row = enrich_trade_geometry(
                        trade,
                        frames[symbol],
                        strategy_id=audit_id,
                        symbol=symbol,
                        cost_bps=cost,
                        btc_frame=btc,
                        volatility_config=geometry.get("pre_entry_volatility_state"),
                    )
                    if row["terminal_liquidation"]:
                        count += 1
                        continue
                    all_rows.append(row)
                terminal_counts[audit_id][symbol] = count

        if all_rows:
            origin = min(row["_entry_timestamp"] for row in all_rows).normalize()
            block = pd.Timedelta(days=block_days)
            for row in all_rows:
                row["_block_id"] = int((row["_entry_timestamp"] - origin) // block)
            blocks = sorted({int(row["_block_id"]) for row in all_rows})
        else:
            origin = None
            blocks = []
        samples = _bootstrap_samples(
            blocks,
            replicates=replicates,
            seed=seed + cost_index,
        )

        strategy_reports: list[dict[str, Any]] = []
        for spec in protocol["strategies"]:
            audit_id = str(spec["audit_id"])
            strategy_rows = [row for row in all_rows if row["strategy_id"] == audit_id]
            cell_rows: list[dict[str, Any]] = []
            for cell_id, predicate in cells:
                selected = [row for row in strategy_rows if predicate(row)]
                summary = _summary(selected, quantiles)
                cell_rows.append(
                    {
                        "cell_id": cell_id,
                        **summary,
                        "bootstrap_ci": _bootstrap_ci(
                            selected,
                            quantiles,
                            samples,
                            ci,
                            uncertainty_fields,
                        ),
                        "sample_warning": len(selected) < 20,
                    }
                )
            strategy_reports.append(
                {
                    "audit_id": audit_id,
                    "family": str(spec["family"]),
                    "parameters": dict(spec["parameters"]),
                    "nonterminal_trade_count": len(strategy_rows),
                    "terminal_liquidation_count": sum(terminal_counts[audit_id].values()),
                    "terminal_liquidation_count_by_symbol": terminal_counts[audit_id],
                    "cells": cell_rows,
                    "trades": [
                        {k: v for k, v in row.items() if not k.startswith("_")}
                        for row in strategy_rows
                    ],
                }
            )

        cost_reports.append(
            {
                "cost_bps": cost,
                "primary_cost_case": bool(
                    np.isclose(cost, float(geometry["primary_cost_bps"]))
                ),
                "calendar_block_origin": origin.isoformat() if origin is not None else None,
                "calendar_block_days": block_days,
                "calendar_block_count": len(blocks),
                "bootstrap_replicates": replicates,
                "shared_bootstrap_resamples_across_strategies_and_cells": True,
                "strategies": strategy_reports,
            }
        )

    return {
        "schema_version": 1,
        "analysis": "payoff_geometry_v1",
        "status": "descriptive_development_only",
        "source_protocol": str(protocol["protocol_name"]),
        "source_window": {
            "start": protocol["data"]["start"],
            "end_exclusive": protocol["data"]["end_exclusive"],
            "interval": protocol["data"]["interval"],
            "symbols": [str(v) for v in protocol["data"]["symbols"]],
        },
        "fixed_cell_count_per_strategy": len(cells),
        "cost_cases": cost_reports,
        "bootstrap": dict(bootstrap),
        "terminal_liquidation_policy": geometry["terminal_liquidation_policy"],
        "multiplicity_policy": dict(geometry["multiplicity_policy"]),
        "data_snapshot": snapshot,
        "claims": dict(geometry["claims"]),
    }

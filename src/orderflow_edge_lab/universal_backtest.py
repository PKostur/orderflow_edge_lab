from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np
import pandas as pd


class UniversalBacktestError(ValueError):
    pass


class StrategyPlugin(Protocol):
    strategy_id: str
    warmup_bars: int

    def generate_target(
        self,
        frame: pd.DataFrame,
        params: Mapping[str, Any],
        context: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.Series: ...


@dataclass(frozen=True)
class FunctionStrategy:
    strategy_id: str
    target_fn: Callable[[pd.DataFrame, Mapping[str, Any]], pd.Series]
    warmup_bars: int = 100

    def generate_target(
        self,
        frame: pd.DataFrame,
        params: Mapping[str, Any],
        context: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.Series:
        del context
        return self.target_fn(frame, params)


@dataclass(frozen=True)
class ExecutionModel:
    round_trip_cost_bps: float = 0.0
    slippage_bps_per_turnover_unit: float = 0.0
    max_abs_position: float = 1.0


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise UniversalBacktestError(f"missing market columns: {sorted(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise UniversalBacktestError("market frame index must be DatetimeIndex")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise UniversalBacktestError("market frame timestamps must be unique and increasing")
    return frame


def _profit_factor(values: Sequence[float]) -> float | str | None:
    gains = sum(v for v in values if v > 0.0)
    losses = -sum(v for v in values if v < 0.0)
    if losses > 0.0:
        return gains / losses
    return "INF" if gains > 0.0 else None


def _extract_trades(frame: pd.DataFrame, position: pd.Series, execution: ExecutionModel) -> list[dict[str, Any]]:
    opens = frame["open"].astype(float)
    pos = position.fillna(0.0).to_numpy(dtype=float)
    trades: list[dict[str, Any]] = []
    i = 0
    n = len(frame)
    while i < n - 1:
        side = float(pos[i])
        if side == 0.0:
            i += 1
            continue
        j = i
        compounded = 1.0
        while j < n - 1 and float(pos[j]) == side:
            compounded *= 1.0 + side * (float(opens.iloc[j + 1]) / float(opens.iloc[j]) - 1.0)
            j += 1
        entry_price = float(opens.iloc[i])
        held = frame.iloc[i:j]
        if side > 0:
            mfe = max(0.0, float(held["high"].max()) / entry_price - 1.0) if len(held) else 0.0
            mae = min(0.0, float(held["low"].min()) / entry_price - 1.0) if len(held) else 0.0
        else:
            mfe = max(0.0, 1.0 - float(held["low"].min()) / entry_price) if len(held) else 0.0
            mae = min(0.0, 1.0 - float(held["high"].max()) / entry_price) if len(held) else 0.0
        gross = compounded - 1.0
        cost = (float(execution.round_trip_cost_bps) + 2.0 * float(execution.slippage_bps_per_turnover_unit)) / 10_000.0
        net = gross - cost
        trades.append({
            "entry": frame.index[i].isoformat(),
            "exit": frame.index[j].isoformat(),
            "side": 1 if side > 0 else -1,
            "bars_held": int(j - i),
            "gross_bps": gross * 10_000.0,
            "net_bps": net * 10_000.0,
            "mfe_bps": mfe * 10_000.0,
            "mae_bps": mae * 10_000.0,
        })
        i = j
    return trades


def run_backtest(
    frame: pd.DataFrame,
    strategy: StrategyPlugin,
    params: Mapping[str, Any],
    execution: ExecutionModel = ExecutionModel(),
    *,
    context: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    if len(frame) < max(3, int(strategy.warmup_bars)):
        return {"strategy_id": strategy.strategy_id, "parameters": dict(params), "trades": 0}

    target = strategy.generate_target(frame, params, context).reindex(frame.index).fillna(0.0)
    if not np.isfinite(target.to_numpy(dtype=float)).all():
        raise UniversalBacktestError("strategy target contains non-finite values")
    limit = float(execution.max_abs_position)
    target = target.clip(-limit, limit)
    # Causal convention: signal is known at bar close; execution begins at next bar open.
    position = target.shift(1).fillna(0.0)

    opens = frame["open"].astype(float)
    gross = position * (opens.shift(-1) / opens - 1.0)
    turnover = (position - position.shift(1).fillna(0.0)).abs()
    side_cost = float(execution.round_trip_cost_bps) / 2.0 / 10_000.0
    slip = float(execution.slippage_bps_per_turnover_unit) / 10_000.0
    net = (gross - turnover * (side_cost + slip)).fillna(0.0)

    equity = (1.0 + net).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    trades = _extract_trades(frame, position, execution)
    values = [float(t["net_bps"]) for t in trades]
    winners = [v for v in values if v > 0.0]
    mfe = [float(t["mfe_bps"]) for t in trades]
    mae = [float(t["mae_bps"]) for t in trades]

    return {
        "strategy_id": strategy.strategy_id,
        "parameters": dict(params),
        "execution": {
            "round_trip_cost_bps": float(execution.round_trip_cost_bps),
            "slippage_bps_per_turnover_unit": float(execution.slippage_bps_per_turnover_unit),
            "max_abs_position": limit,
        },
        "bars": len(frame),
        "trades": len(trades),
        "cumulative_trade_net_bps": sum(values),
        "expectancy_bps": float(np.mean(values)) if values else None,
        "median_trade_bps": float(np.median(values)) if values else None,
        "win_rate": len(winners) / len(values) if values else None,
        "profit_factor": _profit_factor(values),
        "total_return": float(equity.iloc[-2] - 1.0) if len(equity) > 1 else 0.0,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "exposure_fraction": float((position != 0.0).mean()),
        "turnover_units": float(turnover.sum()),
        "median_mfe_bps": float(np.median(mfe)) if mfe else None,
        "median_mae_bps": float(np.median(mae)) if mae else None,
        "trades_ledger": trades,
        "claims": {"causal_next_bar_execution": True, "live_trading_authorized": False},
    }


def parameter_variants(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    if not keys:
        return [{}]
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def run_sweep(
    frames: Mapping[str, pd.DataFrame],
    strategy: StrategyPlugin,
    parameter_grid: Mapping[str, Sequence[Any]],
    cost_cases_bps: Sequence[float],
    *,
    slippage_bps_per_turnover_unit: float = 0.0,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for params in parameter_variants(parameter_grid):
        for cost in cost_cases_bps:
            symbol_rows = []
            for symbol, frame in sorted(frames.items()):
                result = run_backtest(
                    frame,
                    strategy,
                    params,
                    ExecutionModel(float(cost), float(slippage_bps_per_turnover_unit)),
                )
                symbol_rows.append({"symbol": symbol, **{k: v for k, v in result.items() if k != "trades_ledger"}})
            usable = [r for r in symbol_rows if int(r.get("trades") or 0) > 0 and r.get("expectancy_bps") is not None]
            ev = [float(r["expectancy_bps"]) for r in usable]
            pf = []
            for r in usable:
                value = r.get("profit_factor")
                if value == "INF":
                    pf.append(999.0)
                elif value is not None and math.isfinite(float(value)):
                    pf.append(float(value))
            rows.append({
                "strategy_id": strategy.strategy_id,
                "parameters": dict(params),
                "round_trip_cost_bps": float(cost),
                "symbols": len(usable),
                "total_trades": sum(int(r["trades"]) for r in usable),
                "median_symbol_expectancy_bps": float(np.median(ev)) if ev else None,
                "positive_symbol_fraction": sum(v > 0 for v in ev) / len(ev) if ev else None,
                "median_symbol_profit_factor": float(np.median(pf)) if pf else None,
                "per_symbol": symbol_rows,
            })
    return {
        "schema_version": 1,
        "engine": "universal_backtest_framework_v1",
        "strategy_id": strategy.strategy_id,
        "trial_count": len(rows),
        "results": rows,
        "claims": {"development_only": True, "profitable_edge_established": False},
    }


def legacy_strategy(family: str) -> FunctionStrategy:
    # Import lazily to avoid coupling the universal engine to the legacy module.
    from .strategy_tournament import generate_target_position
    return FunctionStrategy(
        strategy_id=str(family),
        target_fn=lambda frame, params: generate_target_position(frame, family, params),
        warmup_bars=100,
    )

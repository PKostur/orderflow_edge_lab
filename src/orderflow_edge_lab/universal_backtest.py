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


def _canonical_trade_ledger(
    frame: pd.DataFrame,
    position: pd.Series,
    price_returns: pd.Series,
    turnover: pd.Series,
    per_turnover_cost: float,
) -> list[dict[str, Any]]:
    """Build a turnover-aware ledger through the last observable open.

    Positions are allowed to change magnitude.  A trade is a contiguous
    same-sign position episode.  At a direct reversal, the old episode gets
    the exit notional and the new episode gets the entry notional, so the two
    records sum to the full turnover cost.
    """

    opens = frame["open"].astype(float)
    highs = frame["high"].astype(float)
    lows = frame["low"].astype(float)
    pos = position.to_numpy(dtype=float)
    returns = price_returns.to_numpy(dtype=float)
    changes = turnover.to_numpy(dtype=float)
    m = len(pos)
    trades: list[dict[str, Any]] = []
    i = 0
    while i < m:
        if pos[i] == 0.0:
            i += 1
            continue
        side = 1 if pos[i] > 0.0 else -1
        j = i + 1
        while j < m and ((pos[j] > 0.0) if side > 0 else (pos[j] < 0.0)):
            j += 1

        entry_amount = abs(pos[i])
        entry_cost = entry_amount * per_turnover_cost
        trade_equity = 1.0
        gross_equity = 1.0
        cost_units = entry_amount
        for t in range(i, j):
            gross = float(pos[t] * returns[t])
            gross_equity *= 1.0 + gross
            cost = entry_cost if t == i else float(changes[t]) * per_turnover_cost
            if t > i:
                cost_units += float(changes[t])
            trade_equity *= (1.0 - cost) * (1.0 + gross)

        exit_amount = abs(pos[j - 1])
        cost_units += exit_amount
        exit_cost = exit_amount * per_turnover_cost
        trade_equity *= 1.0 - exit_cost

        entry_price = float(opens.iloc[i])
        if side > 0:
            mfe = max(0.0, float(highs.iloc[i:j].max()) / entry_price - 1.0)
            mae = min(0.0, float(lows.iloc[i:j].min()) / entry_price - 1.0)
        else:
            mfe = max(0.0, 1.0 - float(lows.iloc[i:j].min()) / entry_price)
            mae = min(0.0, 1.0 - float(highs.iloc[i:j].max()) / entry_price)
        exit_index = j if j < len(frame) else len(frame) - 1
        trades.append(
            {
                "entry": frame.index[i].isoformat(),
                "exit": frame.index[exit_index].isoformat(),
                "side": side,
                "entry_position": float(pos[i]),
                "terminal_liquidation": bool(j == m),
                "bars_held": int(j - i),
                "gross_bps": (gross_equity - 1.0) * 10_000.0,
                "net_bps": (trade_equity - 1.0) * 10_000.0,
                "cost_bps": cost_units * per_turnover_cost * 10_000.0,
                "mfe_bps": mfe * 10_000.0,
                "mae_bps": mae * 10_000.0,
            }
        )
        i = j
    return trades


def run_canonical_backtest(
    frame: pd.DataFrame,
    strategy: StrategyPlugin,
    params: Mapping[str, Any],
    execution: ExecutionModel = ExecutionModel(),
    *,
    context: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Run the explicit canonical economic accounting path.

    Signals are generated at bar close and executed at the next bar open.  The
    last observable open is treated as a terminal liquidation boundary.  The
    target that would execute at that final open is not included because it has
    no observable next-bar return.  Costs are charged on actual absolute
    turnover, including the terminal liquidation, which makes fractional
    positions and open-ended final trades explicit.

    This function is intentionally separate from ``run_backtest``.  The latter
    remains the legacy-compatible path used for frozen parity checks.
    """

    frame = _validate_frame(frame)
    if len(frame) < max(3, int(strategy.warmup_bars)):
        return {
            "strategy_id": strategy.strategy_id,
            "parameters": dict(params),
            "accounting": {
                "mode": "canonical_turnover_path",
                "version": 2,
                "terminal_policy": "liquidate_last_observable_open",
            },
            "trades": 0,
        }
    if not all(
        np.isfinite(float(value)) and float(value) >= 0.0
        for value in (execution.round_trip_cost_bps, execution.slippage_bps_per_turnover_unit)
    ):
        raise UniversalBacktestError("execution costs must be finite and non-negative")
    limit = float(execution.max_abs_position)
    if not np.isfinite(limit) or limit <= 0.0:
        raise UniversalBacktestError("max_abs_position must be finite and positive")

    target = strategy.generate_target(frame, params, context).reindex(frame.index).fillna(0.0)
    if not np.isfinite(target.to_numpy(dtype=float)).all():
        raise UniversalBacktestError("strategy target contains non-finite values")
    target = target.clip(-limit, limit)
    position = target.shift(1).fillna(0.0)
    # Only intervals with a known next open are evaluated.  The last target
    # would execute at the terminal open and therefore has no return horizon.
    effective_position = position.iloc[:-1].copy()
    opens = frame["open"].astype(float)
    price_returns = (opens.shift(-1) / opens - 1.0).iloc[:-1]
    previous = effective_position.shift(1).fillna(0.0)
    turnover = (effective_position - previous).abs()
    per_turnover_cost = (
        float(execution.round_trip_cost_bps) / 2.0
        + float(execution.slippage_bps_per_turnover_unit)
    ) / 10_000.0
    if limit * per_turnover_cost >= 1.0:
        raise UniversalBacktestError("turnover cost would make equity non-positive")
    terminal_position = float(effective_position.iloc[-1])
    terminal_turnover = abs(terminal_position)
    if (terminal_turnover * per_turnover_cost) >= 1.0:
        raise UniversalBacktestError("terminal liquidation cost would make equity non-positive")
    market = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(market).all() or (market <= 0).any():
        raise UniversalBacktestError("canonical market prices must be finite and positive")
    gross = effective_position * price_returns
    # Close the old episode before sizing the new one on remaining equity.
    changed_side = np.sign(effective_position) != np.sign(previous)
    exit_units = previous.abs().where(changed_side, 0.0)
    entry_or_resize_units = turnover - exit_units
    exit_factor = 1.0 - exit_units * per_turnover_cost
    entry_factor = 1.0 - entry_or_resize_units * per_turnover_cost
    market_factor = 1.0 + gross
    if (exit_factor <= 0).any() or (entry_factor <= 0).any() or (market_factor <= 0).any():
        raise UniversalBacktestError("canonical path reaches non-positive equity; bankruptcy model required")
    factors = exit_factor * entry_factor * market_factor
    equity = factors.cumprod()
    terminal_cost = terminal_turnover * per_turnover_cost
    terminal_equity = float(equity.iloc[-1]) * (1.0 - terminal_cost)
    equity_with_terminal = pd.concat(
        [equity, pd.Series([terminal_equity], index=[frame.index[-1]])]
    )
    drawdown = equity_with_terminal / equity_with_terminal.cummax() - 1.0
    trades = _canonical_trade_ledger(
        frame,
        effective_position,
        price_returns,
        turnover,
        per_turnover_cost,
    )
    ledger_equity = float(np.prod([1.0 + float(t["net_bps"]) / 10_000.0 for t in trades]))
    reconciled = bool(np.isclose(ledger_equity, terminal_equity, rtol=1e-10, atol=1e-12))
    if not reconciled:
        raise UniversalBacktestError("canonical trade ledger does not reconcile with equity")
    values = [float(trade["net_bps"]) for trade in trades]
    winners = [value for value in values if value > 0.0]
    mfe = [float(trade["mfe_bps"]) for trade in trades]
    mae = [float(trade["mae_bps"]) for trade in trades]
    return {
        "strategy_id": strategy.strategy_id,
        "parameters": dict(params),
        "execution": {
            "round_trip_cost_bps": float(execution.round_trip_cost_bps),
            "slippage_bps_per_turnover_unit": float(execution.slippage_bps_per_turnover_unit),
            "max_abs_position": limit,
        },
        "accounting": {
            "mode": "canonical_turnover_path",
            "version": 2,
            "terminal_policy": "liquidate_last_observable_open",
            "event_order": "exit_then_entry_or_resize_then_market_return",
            "ledger_equity_reconciled": reconciled,
            "ledger_compounded_return": ledger_equity - 1.0,
            "evaluated_intervals": len(effective_position),
            "terminal_liquidation_turnover_units": terminal_turnover,
            "terminal_liquidation_cost_bps": terminal_cost * 10_000.0,
        },
        "bars": len(frame),
        "trades": len(trades),
        "cumulative_trade_net_bps": sum(values),
        "expectancy_bps": float(np.mean(values)) if values else None,
        "median_trade_bps": float(np.median(values)) if values else None,
        "win_rate": len(winners) / len(values) if values else None,
        "profit_factor": _profit_factor(values),
        "total_return": terminal_equity - 1.0,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "exposure_fraction": float((effective_position != 0.0).mean()),
        "turnover_units": float(turnover.sum() + terminal_turnover),
        "median_mfe_bps": float(np.median(mfe)) if mfe else None,
        "median_mae_bps": float(np.median(mae)) if mae else None,
        "trades_ledger": trades,
        "claims": {
            "causal_next_bar_execution": True,
            "canonical_turnover_cost_accounting": True,
            "terminal_liquidation_included": True,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
        },
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


def walk_forward_report(
    frame: pd.DataFrame,
    strategy: StrategyPlugin,
    params: Mapping[str, Any],
    execution: ExecutionModel = ExecutionModel(),
    *,
    fold_days: int = 30,
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    if fold_days <= 0:
        raise UniversalBacktestError("fold_days must be positive")
    if len(frame) == 0:
        return {"folds": [], "fold_count": 0}
    start = frame.index.min().normalize()
    end = frame.index.max()
    delta = pd.Timedelta(days=int(fold_days))
    folds = []
    cursor = start
    while cursor <= end:
        nxt = cursor + delta
        window = frame[(frame.index >= cursor) & (frame.index < nxt)]
        if len(window) >= max(3, int(strategy.warmup_bars)):
            r = run_backtest(window, strategy, params, execution)
            folds.append({
                "start": cursor.isoformat(),
                "end": nxt.isoformat(),
                **{k:v for k,v in r.items() if k not in {"trades_ledger","parameters","execution","claims"}},
            })
        cursor = nxt
    usable=[x for x in folds if int(x.get("trades") or 0)>0 and x.get("expectancy_bps") is not None]
    ev=[float(x["expectancy_bps"]) for x in usable]
    return {
        "fold_days": int(fold_days),
        "fold_count": len(usable),
        "positive_fold_fraction": sum(v>0 for v in ev)/len(ev) if ev else None,
        "median_fold_expectancy_bps": float(np.median(ev)) if ev else None,
        "folds": folds,
    }


def regime_report(
    frame: pd.DataFrame,
    strategy: StrategyPlugin,
    params: Mapping[str, Any],
    regime: pd.Series,
    execution: ExecutionModel = ExecutionModel(),
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    labels=regime.reindex(frame.index)
    rows=[]
    for label in sorted(str(x) for x in labels.dropna().unique()):
        mask=labels.astype("string")==label
        # Preserve the full timeline and suppress exposure outside the regime.
        target=strategy.generate_target(frame,params,None).reindex(frame.index).fillna(0.0)
        gated=target.where(mask,0.0)
        gated_strategy=FunctionStrategy(f"{strategy.strategy_id}@{label}",lambda _f,_p,g=gated:g,warmup_bars=strategy.warmup_bars)
        r=run_backtest(frame,gated_strategy,params,execution)
        rows.append({"regime":label,**{k:v for k,v in r.items() if k not in {"trades_ledger","parameters","execution","claims"}}})
    return {"strategy_id":strategy.strategy_id,"regimes":rows,"claims":{"descriptive_conditioning":True,"candidate_promoted":False}}

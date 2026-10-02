"""Canonical accounting version 3: fixed quantity between target changes.

Version 2 (``universal_backtest.run_canonical_backtest``) is a bar-weight model:
exposure is reset to the target weight at every bar, which makes a +/-1 short a
constant-notional short rebalanced each bar with the rebalancing turnover
uncharged.  Version 3 holds the traded quantity until the strategy target
changes, so exposure weight drifts with price.  For a +/-1 long this is
identical to v2; for a +/-1 short the episode gross is ``1 - exit/entry``, which
is how a fixed-contract futures short settles.

Everything else follows v2: next-open execution, terminal liquidation at the
last observable open, exit-before-entry event order, proportional turnover
costs, unweighted MFE/MAE, exact ledger/equity reconciliation and rejection of
non-positive equity.  v2 is unchanged and frozen protocols remain bound to it.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    StrategyPlugin,
    UniversalBacktestError,
    _profit_factor,
    _validate_frame,
)

ACCOUNTING = {
    "mode": "canonical_turnover_path",
    "version": 3,
    "position_model": "fixed_quantity_between_target_changes",
    "terminal_policy": "liquidate_last_observable_open",
    "event_order": "exit_then_entry_or_resize_then_market_return",
}


def align_funding(raw: pd.Series, index: pd.DatetimeIndex) -> tuple[pd.Series, float]:
    """Sum settlement rates into bar opens: rates in (index[t-1], index[t]] land on index[t].

    Returns the aligned series (missing = 0) and the fraction of bar intervals
    after the first settlement that received at least one settlement.
    """
    out = pd.Series(0.0, index=index)
    if raw is None or len(raw) == 0:
        return out, 0.0
    raw = raw.copy()
    raw.index = pd.to_datetime(raw.index, utc=True)
    raw = raw.sort_index()
    raw = raw[(raw.index > index[0]) & (raw.index <= index[-1])]
    if len(raw) == 0:
        return out, 0.0
    slot = index.searchsorted(raw.index, side="left")
    sums = pd.Series(raw.to_numpy(dtype=float)).groupby(slot).sum()
    out.iloc[sums.index.to_numpy()] = sums.to_numpy()
    first = int(slot.min())
    covered = len(set(slot.tolist()))
    return out, covered / max(1, len(index) - first)


def _sign(value: float) -> int:
    return 1 if value > 0.0 else (-1 if value < 0.0 else 0)


def run_canonical_backtest_v3(
    frame: pd.DataFrame,
    strategy: StrategyPlugin,
    params: Mapping[str, Any],
    execution: ExecutionModel = ExecutionModel(),
    *,
    context: Mapping[str, pd.DataFrame] | None = None,
    return_equity: bool = False,
    funding: pd.Series | None = None,
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    if len(frame) < max(3, int(strategy.warmup_bars)):
        return {"strategy_id": strategy.strategy_id, "parameters": dict(params),
                "accounting": dict(ACCOUNTING), "trades": 0}
    if not all(
        np.isfinite(float(v)) and float(v) >= 0.0
        for v in (execution.round_trip_cost_bps, execution.slippage_bps_per_turnover_unit)
    ):
        raise UniversalBacktestError("execution costs must be finite and non-negative")
    limit = float(execution.max_abs_position)
    if not np.isfinite(limit) or limit <= 0.0:
        raise UniversalBacktestError("max_abs_position must be finite and positive")
    market = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(market).all() or (market <= 0).any():
        raise UniversalBacktestError("canonical market prices must be finite and positive")

    target = strategy.generate_target(frame, params, context).reindex(frame.index).fillna(0.0)
    if not np.isfinite(target.to_numpy(dtype=float)).all():
        raise UniversalBacktestError("strategy target contains non-finite values")
    pos = target.clip(-limit, limit).shift(1).fillna(0.0).to_numpy(dtype=float)[:-1]
    opens = frame["open"].astype(float).to_numpy()
    highs = frame["high"].astype(float).to_numpy()
    lows = frame["low"].astype(float).to_numpy()
    returns = opens[1:] / opens[:-1] - 1.0
    c = (float(execution.round_trip_cost_bps) / 2.0
         + float(execution.slippage_bps_per_turnover_unit)) / 10_000.0
    m = len(pos)
    if funding is not None:
        funding_rates, funding_coverage = align_funding(funding, frame.index)
        fund = funding_rates.to_numpy(dtype=float)
        if not np.isfinite(fund).all():
            raise UniversalBacktestError("funding rates must be finite")
    else:
        fund = np.zeros(len(frame))
        funding_coverage = None

    equity = np.empty(m)
    level = 1.0
    current = 0.0  # held exposure weight entering the bar, after drift
    previous_target = 0.0
    turnover_units = 0.0
    trades: list[dict[str, Any]] = []
    episode: dict[str, Any] | None = None

    def close_episode(end_index: int, exit_weight: float) -> None:
        nonlocal episode
        assert episode is not None
        exit_factor = 1.0 - abs(exit_weight) * c
        if exit_factor <= 0.0:
            raise UniversalBacktestError("canonical path reaches non-positive equity; bankruptcy model required")
        i, j, side = episode["start"], end_index, episode["side"]
        entry_price = opens[i]
        if side > 0:
            mfe = max(0.0, highs[i:j].max() / entry_price - 1.0)
            mae = min(0.0, lows[i:j].min() / entry_price - 1.0)
        else:
            mfe = max(0.0, 1.0 - lows[i:j].min() / entry_price)
            mae = min(0.0, 1.0 - highs[i:j].max() / entry_price)
        trades.append({
            "entry": frame.index[i].isoformat(),
            "exit": frame.index[min(j, len(frame) - 1)].isoformat(),
            "side": side,
            "entry_position": episode["entry_position"],
            "terminal_liquidation": bool(j == m),
            "bars_held": int(j - i),
            "gross_bps": (episode["gross"] - 1.0) * 10_000.0,
            "net_bps": (episode["net"] * exit_factor - 1.0) * 10_000.0,
            "cost_bps": (episode["cost_units"] + abs(exit_weight)) * c * 10_000.0,
            "funding_bps": episode["funding"] * 10_000.0,
            "mfe_bps": mfe * 10_000.0,
            "mae_bps": mae * 10_000.0,
        })
        episode = None

    def settle_funding(t: int) -> None:
        # The position held into open t pays weight x rate before any trade at t.
        nonlocal level
        if current == 0.0 or fund[t] == 0.0:
            return
        flow = -current * float(fund[t])
        factor = 1.0 + flow
        if factor <= 0.0:
            raise UniversalBacktestError("funding drives equity non-positive; bankruptcy model required")
        level *= factor
        if episode is not None:
            episode["net"] *= factor
            episode["funding"] += flow

    for t in range(m):
        settle_funding(t)
        tgt = float(pos[t])
        exit_units = 0.0
        if _sign(tgt) != _sign(current):
            exit_units = abs(current)
            if episode is not None:
                close_episode(t, current)
            new = tgt
            entry_units = abs(tgt)
        elif tgt != previous_target:
            new = tgt
            entry_units = abs(tgt - current)
        else:
            new = current
            entry_units = 0.0
        exit_factor = 1.0 - exit_units * c
        entry_factor = 1.0 - entry_units * c
        market_factor = 1.0 + new * float(returns[t])
        if exit_factor <= 0.0 or entry_factor <= 0.0 or market_factor <= 0.0:
            raise UniversalBacktestError("canonical path reaches non-positive equity; bankruptcy model required")
        level *= exit_factor * entry_factor * market_factor
        equity[t] = level
        turnover_units += exit_units + entry_units
        if new != 0.0:
            if episode is None:
                episode = {"start": t, "side": _sign(new), "entry_position": new,
                           "gross": 1.0, "net": 1.0, "cost_units": 0.0, "funding": 0.0}
            episode["gross"] *= market_factor
            episode["net"] *= entry_factor * market_factor
            episode["cost_units"] += entry_units
        current = new * (1.0 + float(returns[t])) / market_factor if new != 0.0 else 0.0
        previous_target = tgt

    settle_funding(m)
    terminal_turnover = abs(current)
    if episode is not None:
        close_episode(m, current)
    terminal_equity = level * (1.0 - terminal_turnover * c)
    turnover_units += terminal_turnover

    ledger_equity = float(np.prod([1.0 + t["net_bps"] / 10_000.0 for t in trades]))
    if not np.isclose(ledger_equity, terminal_equity, rtol=1e-10, atol=1e-12):
        raise UniversalBacktestError("canonical v3 trade ledger does not reconcile with equity")
    path = np.concatenate([equity, [terminal_equity]])
    drawdown = path / np.maximum.accumulate(path) - 1.0
    values = [t["net_bps"] for t in trades]
    return {
        "strategy_id": strategy.strategy_id,
        "parameters": dict(params),
        "execution": {
            "round_trip_cost_bps": float(execution.round_trip_cost_bps),
            "slippage_bps_per_turnover_unit": float(execution.slippage_bps_per_turnover_unit),
            "max_abs_position": limit,
        },
        "accounting": {
            **ACCOUNTING,
            **(
                {"version": "3.1", "funding": "position held into each open pays weight x summed settlement rates",
                 "funding_coverage": funding_coverage}
                if funding is not None
                else {}
            ),
            "ledger_equity_reconciled": True,
            "ledger_compounded_return": ledger_equity - 1.0,
            "evaluated_intervals": m,
            "terminal_liquidation_turnover_units": terminal_turnover,
        },
        "bars": len(frame),
        "trades": len(trades),
        "cumulative_trade_net_bps": float(sum(values)),
        "expectancy_bps": float(np.mean(values)) if values else None,
        "median_trade_bps": float(np.median(values)) if values else None,
        "win_rate": sum(v > 0.0 for v in values) / len(values) if values else None,
        "profit_factor": _profit_factor(values),
        "total_return": terminal_equity - 1.0,
        "max_drawdown": float(drawdown.min()),
        "exposure_fraction": float((pos != 0.0).mean()),
        "turnover_units": turnover_units,
        "trades_ledger": trades,
        **(
            {
                # Equity after each evaluated interval, stamped at the interval's
                # closing open (bar t+1); the terminal liquidation is the last point.
                "equity_path": pd.Series(
                    np.concatenate([equity[:-1], [terminal_equity]]),
                    index=frame.index[1 : m + 1],
                )
            }
            if return_equity
            else {}
        ),
        "claims": {
            "causal_next_bar_execution": True,
            "canonical_turnover_cost_accounting": True,
            "terminal_liquidation_included": True,
            "supersedes_v2_for_frozen_protocols": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
        },
    }

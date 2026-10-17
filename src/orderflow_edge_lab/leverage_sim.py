"""Isolated-margin leverage simulation with mark-price liquidation and a block-bootstrap ruin probability.

Generic: works on any book of fixed-horizon positions (strategy-search-v3 ``leverage_assessment``).  Simulation only: no
orders, no keys.  Leverage scales an edge, it cannot create one.

Inputs
------
``positions`` frame, one row per position of a period, with columns

* ``entry_time``, ``exit_time``: UTC timestamps; the mark-price bars that count are those ending in
  ``(entry_time, exit_time]``;
* ``mark_key``: key into ``mark`` (falls back to ``symbol`` when the column is absent);
* ``weight``: signed notional as a fraction of account equity at 1x (the margin put up at leverage ``L`` is
  ``|weight|`` of equity and the notional ``L * |weight|``);
* ``entry_price``: fill price the adverse mark move is measured from;
* ``unit_return``: return of one unit of LONG notional over the period including carry/funding (a short earns
  ``-unit_return``).

``mark``: mapping key -> frame indexed by bar END time with ``high`` and ``low`` columns.
``period_costs``: Series indexed by the period ``entry_time`` with the 1x cost (fraction of equity) of that period's
rebalance; it scales with ``L`` like the notional it is charged on.

Rules (registered in ``config/strategy_search_v3_leveraged.json``)
-------------------------------------------------------------------
* A position is liquidated when its adverse mark move within the holding window reaches ``1/L - maintenance``
  (long: ``(entry - min low)/entry``; short: ``(max high - entry)/entry``; the comparison is ``>=`` with a 1e-12
  tolerance).  A liquidated position loses its margin ``|w|`` plus the liquidation fee on its notional,
  ``fee * L * |w|``, of period-start equity; otherwise it earns ``L * w * unit_return``.
* Period return = sum of position results minus ``L * period cost``, floored at -100%.  Equity compounds period by period.
* Ruin: equity below ``ruin_fraction`` (50%) of its starting value at any period end.
* ``bootstrap_ruin_probability``: stationary block bootstrap (Politis-Romano, geometric blocks with mean
  ``mean_block`` days, wrap-around) of the daily account returns; ruin = the compounded path dipping below the
  ruin fraction within ``horizon`` days.  One index matrix (fixed seed) is shared by every leverage level.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

LEVERAGE_LEVELS = (1, 2, 3, 5, 10, 20)
MAINTENANCE_MARGIN_RATE = 0.005
LIQUIDATION_FEE_RATE = 0.005
RUIN_EQUITY_FRACTION = 0.5
BOOTSTRAP_PATHS = 5000
BOOTSTRAP_MEAN_BLOCK_DAYS = 10
BOOTSTRAP_HORIZON_DAYS = 365
BOOTSTRAP_SEED = 20261012
MAX_SAFE_RUIN_PROBABILITY = 0.05
_TOLERANCE = 1e-12


class LeverageError(ValueError):
    pass


@dataclass(frozen=True)
class LeverageConfig:
    levels: tuple[int, ...] = LEVERAGE_LEVELS
    maintenance_margin_rate: float = MAINTENANCE_MARGIN_RATE
    liquidation_fee_rate: float = LIQUIDATION_FEE_RATE
    ruin_fraction: float = RUIN_EQUITY_FRACTION
    paths: int = BOOTSTRAP_PATHS
    mean_block_days: float = BOOTSTRAP_MEAN_BLOCK_DAYS
    horizon_days: int = BOOTSTRAP_HORIZON_DAYS
    seed: int = BOOTSTRAP_SEED
    max_ruin_probability: float = MAX_SAFE_RUIN_PROBABILITY


def liquidation_threshold(leverage: float, maintenance_margin_rate: float = MAINTENANCE_MARGIN_RATE) -> float:
    """Adverse price move (fraction of the entry price) that liquidates an isolated position."""
    if leverage <= 0:
        raise LeverageError("leverage must be positive")
    return 1.0 / float(leverage) - maintenance_margin_rate


def adverse_excursion(side: float, entry_price: float, low: float, high: float) -> float:
    """Worst adverse move against a position, as a fraction of the entry price (>= 0).  ``side`` is the sign."""
    if not entry_price > 0:
        raise LeverageError("entry price must be positive")
    if side > 0:
        return max(0.0, (entry_price - low) / entry_price)
    if side < 0:
        return max(0.0, (high - entry_price) / entry_price)
    return 0.0


def is_liquidated(adverse: np.ndarray | float, leverage: float,
                  maintenance_margin_rate: float = MAINTENANCE_MARGIN_RATE) -> np.ndarray | bool:
    """Liquidation when the adverse move has reached ``1/L - maintenance`` (``>=``, 1e-12 tolerance)."""
    thr = liquidation_threshold(leverage, maintenance_margin_rate)
    return np.asarray(adverse) >= thr - _TOLERANCE


def position_adverse_excursions(positions: pd.DataFrame, mark: Mapping[str, pd.DataFrame]) -> tuple[np.ndarray, int]:
    """Worst adverse mark-price move of every position within its window.

    Returns (excursions, number of positions with no mark bar in the window: those get 0, i.e. cannot liquidate).
    """
    keys = positions["mark_key"] if "mark_key" in positions else positions["symbol"]
    entry_ns = pd.DatetimeIndex(positions["entry_time"]).as_unit("ns").asi8
    exit_ns = pd.DatetimeIndex(positions["exit_time"]).as_unit("ns").asi8
    weight = positions["weight"].to_numpy(dtype=float)
    price = positions["entry_price"].to_numpy(dtype=float)
    out = np.zeros(len(positions))
    missing = 0
    cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for i, key in enumerate(keys):
        if key not in cache:
            frame = mark.get(key)
            if frame is None or len(frame) == 0:
                cache[key] = (np.empty(0, dtype=np.int64), np.empty(0), np.empty(0))
            else:
                cache[key] = (pd.DatetimeIndex(frame.index).as_unit("ns").asi8, frame["low"].to_numpy(dtype=float),
                              frame["high"].to_numpy(dtype=float))
        ts, low, high = cache[key]
        a, b = np.searchsorted(ts, entry_ns[i], side="right"), np.searchsorted(ts, exit_ns[i], side="right")
        if b <= a:
            missing += 1
            continue
        out[i] = adverse_excursion(weight[i], price[i], float(np.nanmin(low[a:b])), float(np.nanmax(high[a:b])))
    return out, missing


def simulate_leverage(positions: pd.DataFrame, adverse: np.ndarray, period_costs: pd.Series, leverage: float, *,
                      config: LeverageConfig = LeverageConfig()) -> dict[str, Any]:
    """Historical equity path at one leverage level.

    Returns period and daily account returns, the equity path, the number of liquidations and ruin flags.
    """
    thr_hit = np.asarray(is_liquidated(adverse, leverage, config.maintenance_margin_rate), dtype=bool)
    w = positions["weight"].to_numpy(dtype=float)
    unit = positions["unit_return"].to_numpy(dtype=float)
    pnl = np.where(thr_hit, -np.abs(w) * (1.0 + config.liquidation_fee_rate * leverage), leverage * w * unit)
    entry = pd.DatetimeIndex(positions["entry_time"])
    by_period = pd.Series(pnl, index=entry).groupby(level=0).sum() if len(positions) else pd.Series(dtype=float)
    costs = period_costs.groupby(level=0).sum() * leverage
    period_ret = by_period.reindex(by_period.index.union(costs.index)).fillna(0.0) - costs.reindex(
        by_period.index.union(costs.index)).fillna(0.0)
    period_ret = period_ret.sort_index().clip(lower=-1.0)
    equity = (1.0 + period_ret).cumprod()
    days = period_ret.index.normalize()
    daily = (1.0 + period_ret).groupby(days).prod() - 1.0
    if len(daily):
        daily = daily.reindex(pd.date_range(daily.index[0], daily.index[-1], freq="D", tz="UTC")).fillna(0.0)
    min_equity = float(equity.min()) if len(equity) else 1.0
    return {
        "leverage": leverage,
        "n_positions": int(len(positions)),
        "n_liquidations": int(thr_hit.sum()),
        "liquidation_threshold": liquidation_threshold(leverage, config.maintenance_margin_rate),
        "period_returns": period_ret,
        "daily_returns": daily,
        "equity": equity,
        "final_equity": float(equity.iloc[-1]) if len(equity) else 1.0,
        "min_equity": min_equity,
        "max_drawdown": float((equity / equity.cummax() - 1.0).min()) if len(equity) else 0.0,
        "historical_ruin": bool(min_equity < config.ruin_fraction),
    }


def stationary_bootstrap_indices(n: int, paths: int, horizon: int, mean_block: float, seed: int) -> np.ndarray:
    """(paths, horizon) integer indices of a stationary bootstrap: continue the block with probability
    ``1 - 1/mean_block`` else restart at a uniformly random position; indices wrap around the sample."""
    if n < 1:
        raise LeverageError("empty sample")
    rng = np.random.default_rng(seed)
    idx = np.empty((paths, horizon), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, size=paths)
    restart_p = 1.0 / float(mean_block)
    for t in range(1, horizon):
        restart = rng.random(paths) < restart_p
        fresh = rng.integers(0, n, size=paths)
        idx[:, t] = np.where(restart, fresh, (idx[:, t - 1] + 1) % n)
    return idx


def bootstrap_ruin_probability(daily_returns: np.ndarray | pd.Series, *, indices: np.ndarray | None = None,
                               config: LeverageConfig = LeverageConfig()) -> dict[str, Any]:
    """P(equity < ruin fraction of its start at any day within the horizon) over bootstrap paths."""
    r = np.asarray(daily_returns, dtype=float)
    if len(r) == 0:
        raise LeverageError("no daily returns to bootstrap")
    if indices is None:
        indices = stationary_bootstrap_indices(len(r), config.paths, config.horizon_days, config.mean_block_days,
                                               config.seed)
    growth = np.clip(1.0 + r[indices], 0.0, None)
    equity = np.cumprod(growth, axis=1)
    ruined = equity.min(axis=1) < config.ruin_fraction
    return {"ruin_probability": float(ruined.mean()), "paths": int(indices.shape[0]),
            "horizon_days": int(indices.shape[1]), "median_final_equity": float(np.median(equity[:, -1])),
            "p05_final_equity": float(np.percentile(equity[:, -1], 5))}


def max_safe_leverage(report: Mapping[str, Mapping[str, Any]], max_ruin: float = MAX_SAFE_RUIN_PROBABILITY) -> int | None:
    """Largest tested level with ruin probability <= ``max_ruin`` AND no liquidation in the historical path."""
    safe = [int(level) for level, row in report.items()
            if row["ruin_probability"] <= max_ruin and row["n_liquidations"] == 0]
    return max(safe) if safe else None


def assess_leverage(positions: pd.DataFrame, mark: Mapping[str, pd.DataFrame], period_costs: pd.Series, *,
                    config: LeverageConfig = LeverageConfig(), levels: Sequence[int] | None = None) -> dict[str, Any]:
    """Run the registered leverage assessment on a book.  Returns {"levels": {L: {...}}, "max_safe_leverage": L|None}."""
    adverse, missing = position_adverse_excursions(positions, mark)
    levels = tuple(levels if levels is not None else config.levels)
    report: dict[str, dict[str, Any]] = {}
    indices: np.ndarray | None = None
    for level in levels:
        sim = simulate_leverage(positions, adverse, period_costs, level, config=config)
        daily = sim["daily_returns"]
        if indices is None and len(daily):
            indices = stationary_bootstrap_indices(len(daily), config.paths, config.horizon_days,
                                                   config.mean_block_days, config.seed)
        boot = bootstrap_ruin_probability(daily, indices=indices, config=config)
        report[str(level)] = {
            "ruin_probability": boot["ruin_probability"],
            "median_final_equity_365d": boot["median_final_equity"],
            "p05_final_equity_365d": boot["p05_final_equity"],
            "n_liquidations": sim["n_liquidations"],
            "n_positions": sim["n_positions"],
            "liquidation_threshold": sim["liquidation_threshold"],
            "historical_final_equity": sim["final_equity"],
            "historical_min_equity": sim["min_equity"],
            "historical_max_drawdown": sim["max_drawdown"],
            "historical_ruin": sim["historical_ruin"],
            "daily_mean": float(daily.mean()) if len(daily) else None,
            "daily_std": float(daily.std(ddof=1)) if len(daily) > 1 else None,
        }
    return {
        "levels": report,
        "max_safe_leverage": max_safe_leverage(report, config.max_ruin_probability),
        "positions_without_mark_bars": int(missing),
        "max_adverse_excursion": float(adverse.max()) if len(adverse) else 0.0,
        "config": {"maintenance_margin_rate": config.maintenance_margin_rate,
                   "liquidation_fee_rate": config.liquidation_fee_rate, "ruin_fraction": config.ruin_fraction,
                   "paths": config.paths, "mean_block_days": config.mean_block_days,
                   "horizon_days": config.horizon_days, "seed": config.seed,
                   "liquidation_fee_basis": "fraction of notional (L*|w|) on top of the lost margin |w|"},
    }

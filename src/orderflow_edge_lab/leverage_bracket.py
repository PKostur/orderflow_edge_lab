"""Take-profit bracket engine for leverage-bracket-study-v1 (descriptive mechanics study; paper only, no orders).

Spec: ``config/leverage_bracket_study_v1.json`` (frozen before any price data was loaded).  All P&L is expressed in
units of the position's MARGIN (``0.10`` = +10% of margin); a position of leverage ``L`` has notional ``L`` margins.

Mechanics (per symbol, sequential, one position at a time)
* open at the close of bar ``i`` (entry price = close ``i``); levels are checked from bar ``i + 1`` on that bar's
  high / low:  take-profit at ``entry * (1 + side * tp / L)``;  adverse level at ``entry * (1 - side * a)`` with
  ``a = 0.5 / L`` (S2, half-margin stop, code 1) or ``a = 1 / L - 0.005`` (S1, liquidation, code 2, maintenance 0.5%).
* same bar touching both a favourable and the adverse level: the adverse one is assumed first (conservative); such
  trades are flagged (``ambiguous``) and counted.  Fills are at the level price.
* time stop (code 3): the first valid bar at or after ``i + 1440`` minutes closes at its close (levels are checked on
  that bar first).  The position closing on bar ``j`` is replaced at once by a new one at the close of ``j`` (when the
  entry rule has a direction there).  A trade that cannot finish inside the data is dropped.
* costs: 14 bps round trip on notional (= ``0.0014 * L`` margins) on every non-liquidated trade; a liquidation loses the
  margin plus 0.5% of notional plus the entry half of the cost (7 bps x L, paid from the wallet) plus funding settled
  while open: ``-(1 + 0.005 L) - 0.0007 L - funding``.  Funding: for every settlement
  ``s`` with ``i < s <= j`` the position pays ``side * L * rate`` margins (longs pay positive rates).
* account: one account from 1.0; each new position commits ``2%`` of current equity as margin; P&L settles into
  equity at close; at one minute closes are settled before opens.

Indexing: arrays live on the dense minute grid of ``leverage_bracket_data`` (index = bar END minute, NaN = no bar).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np

from orderflow_edge_lab import leverage_bracket_data as bdata
from orderflow_edge_lab import leverage_sim
from orderflow_edge_lab import review_methods

SEED = 20261013
LEVERAGES = (10, 20, 50, 75)
TAKE_PROFITS = (0.10, 0.15, 0.20)
STOPS = ("S1", "S2")
ENTRIES = ("E0", "E1", "E2")
FEE_ROUND_TRIP = 0.0014  # 5 bps taker + 2 bps slippage per side, on notional
MAINTENANCE = 0.005
LIQUIDATION_FEE = 0.005
STOP_FRACTION = 0.5  # S2: stop at a loss of 50% of margin
MARGIN_FRACTION = 0.02
LOOKBACK = 1440
MAX_HOLD = 1440
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_BLOCK = 10
RUIN_PATHS = 5000
RUIN_HORIZON = 365
MAX_RUIN = 0.05
BH_Q = 0.10
HALF_1_END = "2025-05-15"
CODE_TP, CODE_STOP, CODE_LIQ, CODE_TIME = 0, 1, 2, 3


@dataclass(frozen=True)
class Cell:
    entry: str
    leverage: int
    tp: float
    stop: str

    @property
    def name(self) -> str:
        return f"{self.entry}_L{self.leverage}_TP{int(round(self.tp * 100))}_{self.stop}"


def all_cells() -> list[Cell]:
    return [Cell(e, lv, tp, s) for e in ENTRIES for lv in LEVERAGES for tp in TAKE_PROFITS for s in STOPS]


def adverse_distance(leverage: float, stop: str) -> float:
    """Adverse price move (fraction of entry) that ends the position: S2 stop 0.5/L, S1 liquidation 1/L - 0.005."""
    return STOP_FRACTION / leverage if stop == "S2" else 1.0 / leverage - MAINTENANCE


# ------------------------------------------------------------------------------------------------- entries


def entry_directions(entry: str, close: np.ndarray, *, symbol_index: int, seed: int = SEED,
                     lookback: int = LOOKBACK) -> np.ndarray:
    """int8 direction (+1 long, -1 short, 0 none) that the entry rule gives for an entry at the close of each bar.

    E0 random, deterministic in ``(seed, symbol_index)`` (the same draws are used by every cell); E1 sign of
    ``close_t / close_{t-1440 bars} - 1`` where the bar 24 hours earlier must exist (otherwise 0 = no trade); E2 the
    opposite of E1.
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    if entry == "E0":
        bits = np.random.default_rng([seed, symbol_index]).integers(0, 2, size=n)
        return (bits * 2 - 1).astype(np.int8)
    if entry not in ("E1", "E2"):
        raise ValueError(f"unknown entry {entry}")
    prev = np.full(n, np.nan)
    if n > lookback:
        prev[lookback:] = close[:-lookback]
    with np.errstate(invalid="ignore"):
        sign = np.sign(close - prev)
    sign = np.nan_to_num(sign, nan=0.0).astype(np.int8)
    return sign if entry == "E1" else (-sign).astype(np.int8)


# ------------------------------------------------------------------------------------------------- the walk


@dataclass
class Trades:
    open_idx: np.ndarray
    close_idx: np.ndarray
    side: np.ndarray
    code: np.ndarray
    ambiguous: np.ndarray

    def __len__(self) -> int:
        return len(self.open_idx)


def walk_bracket(high: Any, low: Any, close: Any, direction: np.ndarray, leverage: float, tp: float, stop: str, *,
                 start_idx: int, last_idx: int | None = None, max_hold: int = MAX_HOLD) -> Trades:
    """Sequential trades of one symbol for one bracket (see module docstring).  ``high/low/close`` are sequences."""
    H = high.tolist() if isinstance(high, np.ndarray) else list(high)
    L = low.tolist() if isinstance(low, np.ndarray) else list(low)
    C = close.tolist() if isinstance(close, np.ndarray) else list(close)
    n = len(C)
    last = n - 1 if last_idx is None else min(last_idx, n - 1)
    direction = np.asarray(direction)
    valid = (direction != 0) & ~np.isnan(np.asarray(close, dtype=float))
    cand = np.flatnonzero(valid)
    cand = cand[cand >= start_idx].tolist()
    tp_d = tp / leverage
    adv_d = adverse_distance(leverage, stop)
    adv_code = CODE_STOP if stop == "S2" else CODE_LIQ
    dirs = direction.tolist()
    o_i: list[int] = []
    o_j: list[int] = []
    o_s: list[int] = []
    o_c: list[int] = []
    o_a: list[int] = []
    k = 0
    m = len(cand)
    while k < m:
        i = cand[k]
        end = i + max_hold
        if end > last:
            break
        side = dirs[i]
        entry = C[i]
        code = -1
        amb = 0
        if side > 0:
            tpp = entry * (1.0 + tp_d)
            advp = entry * (1.0 - adv_d)
            for j in range(i + 1, end + 1):
                if L[j] <= advp:
                    code = adv_code
                    amb = 1 if H[j] >= tpp else 0
                    break
                if H[j] >= tpp:
                    code = CODE_TP
                    break
        else:
            tpp = entry * (1.0 - tp_d)
            advp = entry * (1.0 + adv_d)
            for j in range(i + 1, end + 1):
                if H[j] >= advp:
                    code = adv_code
                    amb = 1 if L[j] <= tpp else 0
                    break
                if L[j] <= tpp:
                    code = CODE_TP
                    break
        if code < 0:
            j = end
            while j <= last and C[j] != C[j]:  # no bar at the time stop: first valid close after it
                j += 1
            if j > last:
                break
            if j > end:  # bar j was not covered by the loop above: same adverse-first level check on it
                if side > 0:
                    if L[j] <= advp:
                        code, amb = adv_code, int(H[j] >= tpp)
                    elif H[j] >= tpp:
                        code = CODE_TP
                else:
                    if H[j] >= advp:
                        code, amb = adv_code, int(L[j] <= tpp)
                    elif L[j] <= tpp:
                        code = CODE_TP
            if code < 0:
                code = CODE_TIME
        o_i.append(i)
        o_j.append(j)
        o_s.append(side)
        o_c.append(code)
        o_a.append(amb)
        k = bisect_left(cand, j, k + 1)
    return Trades(np.asarray(o_i, dtype=np.int64), np.asarray(o_j, dtype=np.int64), np.asarray(o_s, dtype=np.int8),
                  np.asarray(o_c, dtype=np.int8), np.asarray(o_a, dtype=np.int8))


# ------------------------------------------------------------------------------------------------ economics


def trade_economics(trades: Trades, close: np.ndarray, leverage: float, tp: float, funding_idx: np.ndarray,
                    funding_rate: np.ndarray, stop: str | None = None) -> dict[str, np.ndarray]:
    """Per-trade gross, fee, funding and net P&L in margin units.  With ``stop`` given, asserts that every
    time-stop gross lies within [-adverse level, take-profit] (a time stop must not hide a level touch)."""
    n = len(trades)
    if n == 0:
        z = np.zeros(0)
        return {"gross": z, "fee": z, "funding": z, "net": z}
    close = np.asarray(close, dtype=float)
    code = trades.code
    side = trades.side.astype(float)
    gross = np.empty(n)
    gross[code == CODE_TP] = tp
    gross[code == CODE_STOP] = -STOP_FRACTION
    gross[code == CODE_LIQ] = -1.0
    tm = code == CODE_TIME
    gross[tm] = side[tm] * (close[trades.close_idx[tm]] / close[trades.open_idx[tm]] - 1.0) * leverage
    if stop is not None and tm.any():
        lim = adverse_distance(leverage, stop) * leverage
        if not ((gross[tm] >= -lim - 1e-9) & (gross[tm] <= tp + 1e-9)).all():
            raise AssertionError("time-stop gross outside [-adverse, take-profit]")
    liq = code == CODE_LIQ
    # liquidation: 0.5% liquidation fee on notional plus the ENTRY half of the taker/slippage cost (paid from the wallet
    # at open); every other exit pays the full round trip
    fee = np.where(liq, (LIQUIDATION_FEE + FEE_ROUND_TRIP / 2) * leverage, FEE_ROUND_TRIP * leverage)
    funding = np.zeros(n)
    if len(funding_idx):
        cum = np.concatenate([[0.0], np.cumsum(funding_rate)])
        a = np.searchsorted(funding_idx, trades.open_idx, side="right")
        b = np.searchsorted(funding_idx, trades.close_idx, side="right")
        funding = side * leverage * (cum[b] - cum[a])
    net = gross - fee - funding
    return {"gross": gross, "fee": fee, "funding": funding, "net": net}


def break_even_win_rate(leverage: float, tp: float, stop: str) -> float:
    """Win rate at which a TP-or-loss bracket breaks even after costs (time stops ignored; win = tp - cost,
    loss = 50% of margin + cost for S2, margin + liquidation fee + entry half-fee for S1)."""
    cost = FEE_ROUND_TRIP * leverage
    win = tp - cost
    loss = STOP_FRACTION + cost if stop == "S2" else 1.0 + (LIQUIDATION_FEE + FEE_ROUND_TRIP / 2) * leverage
    return loss / (win + loss)


def driftless_fair_win_rate(leverage: float, tp: float, stop: str) -> float:
    """P(take-profit before the adverse level) for a driftless price: a / (a + b), costs ignored."""
    a = adverse_distance(leverage, stop)
    b = tp / leverage
    return a / (a + b)


# ------------------------------------------------------------------------------------------------ account


def simulate_account(open_idx: np.ndarray, close_idx: np.ndarray, net: np.ndarray, *, n_days: int,
                     sample_start_idx: int = bdata.SAMPLE_START_IDX, minutes_per_day: int = bdata.MINUTES_PER_DAY,
                     margin_fraction: float = MARGIN_FRACTION) -> dict[str, Any]:
    """Merge the trades of all symbols in time order; margin = ``margin_fraction`` x equity at the open, P&L settles at
    the close; closes are settled before opens at the same minute.  Returns daily equity and event-level summaries."""
    n = len(open_idx)
    if n == 0:
        daily = np.ones(n_days)
        return {"daily_equity": daily, "final_equity": 1.0, "max_drawdown": 0.0, "min_equity": 1.0,
                "first_below_half_day": None, "trades": 0}
    keys = np.concatenate([close_idx * 2, open_idx * 2 + 1])
    order = np.argsort(keys, kind="stable")
    equity = 1.0
    margins: dict[int, float] = {}
    eq_after: list[float] = []
    chunk = 1 << 20
    for a in range(0, 2 * n, chunk):
        part = order[a:a + chunk]
        is_open = part >= n
        tid = np.where(is_open, part - n, part)
        val = np.where(is_open, 0.0, net[tid])
        for o, t, v in zip(is_open.tolist(), tid.tolist(), val.tolist(), strict=True):
            if o:
                margins[t] = margin_fraction * equity
            else:
                equity += margins.pop(t) * v
                eq_after.append(equity)
    eq = np.asarray(eq_after)
    close_sorted = np.sort(close_idx)
    ends = sample_start_idx + (np.arange(n_days) + 1) * minutes_per_day
    pos = np.searchsorted(close_sorted, ends, side="right")
    daily = np.concatenate([[1.0], eq])[pos]
    full = np.concatenate([[1.0], eq])
    drawdown = float((full / np.maximum.accumulate(full) - 1.0).min())
    below = np.flatnonzero(eq < leverage_sim.RUIN_EQUITY_FRACTION)
    first_day = None
    if len(below):
        first_day = int((close_sorted[below[0]] - sample_start_idx - 1) // minutes_per_day)
    return {"daily_equity": daily, "final_equity": float(eq[-1]), "max_drawdown": drawdown,
            "min_equity": float(full.min()), "first_below_half_day": first_day, "trades": int(n)}


def daily_returns(daily_equity: np.ndarray) -> np.ndarray:
    full = np.concatenate([[1.0], np.asarray(daily_equity, dtype=float)])
    return full[1:] / full[:-1] - 1.0


def ruin_summary(returns: np.ndarray, *, indices: np.ndarray | None = None, seed: int = SEED, paths: int = RUIN_PATHS,
                 horizon: int = RUIN_HORIZON, mean_block: float = BOOTSTRAP_BLOCK) -> dict[str, Any]:
    """P(ruin within the horizon) via ``leverage_sim`` (reuses its stationary bootstrap) plus first-passage times."""
    cfg = leverage_sim.LeverageConfig(paths=paths, mean_block_days=mean_block, horizon_days=horizon, seed=seed)
    if indices is None:
        indices = leverage_sim.stationary_bootstrap_indices(len(returns), paths, horizon, mean_block, seed)
    out = leverage_sim.bootstrap_ruin_probability(returns, indices=indices, config=cfg)
    equity = np.cumprod(np.clip(1.0 + np.asarray(returns)[indices], 0.0, None), axis=1)
    below = equity < cfg.ruin_fraction
    ruined = below.any(axis=1)
    first = np.argmax(below, axis=1) + 1
    times = first[ruined]
    out.update(
        median_days_to_ruin=float(np.median(times)) if len(times) else None,
        ruin_by_day={str(d): float((ruined & (first <= d)).mean()) for d in (30, 90, 180, 365) if d <= horizon},
    )
    return out


# ------------------------------------------------------------------------------------------------ statistics


def bootstrap_ev(day_sum: np.ndarray, day_count: np.ndarray, *, draws: int = BOOTSTRAP_DRAWS,
                 mean_block: float = BOOTSTRAP_BLOCK, seed: int = SEED) -> dict[str, Any]:
    """Day-block (stationary) bootstrap of the mean net P&L per trade.  ``p_one_sided`` = (1 + #draws <= 0)/(draws+1),
    the one-sided p-value for H0: EV <= 0."""
    n = len(day_sum)
    total = float(day_count.sum())
    if n == 0 or total == 0:
        return {"ev": None, "lo": None, "hi": None, "p_one_sided": 1.0, "trades": 0}
    idx = leverage_sim.stationary_bootstrap_indices(n, draws, n, mean_block, seed)
    cnt = day_count[idx].sum(axis=1)
    ev = np.where(cnt > 0, day_sum[idx].sum(axis=1) / np.maximum(cnt, 1), np.nan)
    ev = ev[~np.isnan(ev)]
    return {"ev": float(day_sum.sum() / total), "lo": float(np.percentile(ev, 2.5)),
            "hi": float(np.percentile(ev, 97.5)), "p_one_sided": float((1 + (ev <= 0).sum()) / (len(ev) + 1)),
            "trades": int(total)}


def half_split_day(sample_start: str = "2024-01-01", half_end: str = HALF_1_END) -> int:
    """Number of days in the first half (sample start .. half end inclusive)."""
    import pandas as pd
    return (pd.Timestamp(half_end) - pd.Timestamp(sample_start)).days + 1


def cell_statistics(cell: Cell, econ: dict[str, np.ndarray], code: np.ndarray, ambiguous: np.ndarray,
                    exit_day: np.ndarray, n_days: int, *, split_day: int, seed: int = SEED) -> dict[str, Any]:
    net = econ["net"]
    n = len(net)
    out: dict[str, Any] = {
        "cell": cell.name, "entry": cell.entry, "leverage": cell.leverage, "take_profit": cell.tp, "stop": cell.stop,
        "trades": int(n),
        "break_even_win_rate": break_even_win_rate(cell.leverage, cell.tp, cell.stop),
        "driftless_fair_win_rate": driftless_fair_win_rate(cell.leverage, cell.tp, cell.stop),
    }
    if n == 0:
        return out
    win = net > 0
    out.update(
        win_rate=float(win.mean()),
        mean_win_pct_margin=float(net[win].mean() * 100) if win.any() else None,
        mean_loss_pct_margin=float(net[~win].mean() * 100) if (~win).any() else None,
        liquidation_rate=float((code == CODE_LIQ).mean()),
        stop_rate=float((code == CODE_STOP).mean()),
        time_stop_rate=float((code == CODE_TIME).mean()),
        take_profit_rate=float((code == CODE_TP).mean()),
        same_bar_ambiguous=int(ambiguous.sum()),
        fees_pct_margin_per_trade=float(econ["fee"].mean() * 100),
        funding_pct_margin_per_trade=float(econ["funding"].mean() * 100),
        gross_pct_margin_per_trade=float(econ["gross"].mean() * 100),
        net_ev_pct_margin_per_trade=float(net.mean() * 100),
    )
    day_sum = np.bincount(exit_day, weights=net, minlength=n_days)
    day_cnt = np.bincount(exit_day, minlength=n_days).astype(float)
    full = bootstrap_ev(day_sum, day_cnt, seed=seed)
    h1 = bootstrap_ev(day_sum[:split_day], day_cnt[:split_day], seed=seed)
    h2 = bootstrap_ev(day_sum[split_day:], day_cnt[split_day:], seed=seed)
    out["ev_bootstrap"] = {"full": full, "half1": h1, "half2": h2}
    return out


def viability_reading(cells: list[dict[str, Any]], q: float = BH_Q, max_ruin: float = MAX_RUIN) -> dict[str, Any]:
    """BH (reusing ``review_methods.bh_family``) over the one-sided full-sample p of every cell; a cell is
    'worth a separately registered trial' only if BH rejects, both halves have a 95% lower bound above 0 and
    P(ruin within 365 days) <= ``max_ruin``."""
    pvals = {c["cell"]: (c["ev_bootstrap"]["full"]["p_one_sided"] if "ev_bootstrap" in c else 1.0) for c in cells}
    bh = review_methods.bh_family(pvals, q=q)
    rows = {}
    for c in cells:
        name = c["cell"]
        eb = c.get("ev_bootstrap")
        lo1 = eb["half1"]["lo"] if eb else None
        lo2 = eb["half2"]["lo"] if eb else None
        ruin = c.get("account", {}).get("ruin", {}).get("ruin_probability")
        halves_ok = lo1 is not None and lo2 is not None and lo1 > 0 and lo2 > 0
        ruin_ok = ruin is not None and ruin <= max_ruin
        rows[name] = {"p": bh[name]["p"], "q_value": bh[name]["q_value"], "bh_reject": bh[name]["reject"],
                      "half1_lower_bound_positive": bool(lo1 is not None and lo1 > 0),
                      "half2_lower_bound_positive": bool(lo2 is not None and lo2 > 0),
                      "ruin_ok": bool(ruin_ok),
                      "worth_separate_trial": bool(bh[name]["reject"] and halves_ok and ruin_ok)}
    return {"q": q, "max_ruin": max_ruin, "cells": rows,
            "viable_cells": sorted(k for k, v in rows.items() if v["worth_separate_trial"])}


# ------------------------------------------------------------------------------------------------ study


def run_cell(cell: Cell, data_dir: Path | str, symbols: list[str], *, seed: int = SEED, n_days: int | None = None,
             start_idx: int = bdata.SAMPLE_START_IDX, ruin_indices: np.ndarray | None = None,
             do_account: bool = True) -> dict[str, Any]:
    """All symbols x one cell: trades, per-cell statistics and the account."""
    data_dir = Path(data_dir)
    parts: list[tuple[Trades, dict[str, np.ndarray]]] = []
    for sym_i, sym in enumerate(symbols):
        high, low, close, f_idx, f_rate = bdata.load_symbol(sym, data_dir)
        close = np.asarray(close)
        direction = entry_directions(cell.entry, close, symbol_index=sym_i, seed=seed)
        trades = walk_bracket(np.asarray(high), np.asarray(low), close, direction, cell.leverage, cell.tp, cell.stop,
                              start_idx=start_idx)
        parts.append((trades, trade_economics(trades, close, cell.leverage, cell.tp, f_idx, f_rate, cell.stop)))
    return summarize_cell(cell, parts, n_days=n_days, start_idx=start_idx, seed=seed, ruin_indices=ruin_indices,
                          do_account=do_account)


def summarize_cell(cell: Cell, parts: list[tuple[Trades, dict[str, np.ndarray]]], *, n_days: int | None,
                   start_idx: int, seed: int = SEED, ruin_indices: np.ndarray | None = None,
                   do_account: bool = True, split_day: int | None = None) -> dict[str, Any]:
    if n_days is None:
        n_days = (bdata.GRID_LEN - 1 - start_idx) // bdata.MINUTES_PER_DAY
    if split_day is None:
        split_day = half_split_day()
    cat = lambda f: np.concatenate([f(p) for p in parts]) if parts else np.zeros(0)  # noqa: E731
    open_idx = cat(lambda p: p[0].open_idx).astype(np.int64)
    close_idx = cat(lambda p: p[0].close_idx).astype(np.int64)
    code = cat(lambda p: p[0].code).astype(np.int8)
    amb = cat(lambda p: p[0].ambiguous).astype(np.int8)
    econ = {key: cat(lambda p, key=key: p[1][key]) for key in ("gross", "fee", "funding", "net")}
    exit_day = ((close_idx - start_idx - 1) // bdata.MINUTES_PER_DAY).astype(np.int64)
    stats = cell_statistics(cell, econ, code, amb, exit_day, n_days, split_day=split_day, seed=seed)
    if do_account and len(open_idx):
        acct = simulate_account(open_idx, close_idx, econ["net"], n_days=n_days, sample_start_idx=start_idx)
        returns = daily_returns(acct["daily_equity"])
        ruin = ruin_summary(returns, indices=ruin_indices, seed=seed)
        stats["account"] = {
            "final_equity": acct["final_equity"], "max_drawdown": acct["max_drawdown"],
            "min_equity": acct["min_equity"], "first_below_half_day": acct["first_below_half_day"],
            "daily_equity": [round(float(x), 8) for x in acct["daily_equity"]], "ruin": ruin,
        }
    return stats


def _run_cell_star(args: tuple) -> dict[str, Any]:
    cell, data_dir, symbols, seed = args
    n_days = (bdata.GRID_LEN - 1 - bdata.SAMPLE_START_IDX) // bdata.MINUTES_PER_DAY
    ruin_idx = leverage_sim.stationary_bootstrap_indices(n_days, RUIN_PATHS, RUIN_HORIZON, BOOTSTRAP_BLOCK, seed)
    return run_cell(cell, data_dir, symbols, seed=seed, n_days=n_days, ruin_indices=ruin_idx)


def run_study(data_dir: Path | str, symbols: list[str], *, workers: int = 8, seed: int = SEED,
              cells: list[Cell] | None = None) -> dict[str, Any]:
    """Every cell, parallel over cells (each worker reads the symbols' arrays via memory maps)."""
    cells = cells if cells is not None else all_cells()
    jobs = [(c, str(data_dir), list(symbols), seed) for c in sorted(cells, key=lambda c: -c.leverage)]
    with Pool(max(1, workers)) as pool:
        results = list(pool.imap_unordered(_run_cell_star, jobs))
    order = {c.name: i for i, c in enumerate(cells)}
    results.sort(key=lambda r: order[r["cell"]])
    return {"cells": results, "viability": viability_reading(results)}


def write_result_once(path: Path | str, payload: dict[str, Any]) -> None:
    """Write ``payload`` as json; raises ``FileExistsError`` if the result already exists (single-run study)."""
    import json
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:  # 'x' fails if the file exists
        json.dump(payload, fh, indent=1)


def is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)

"""Engine for leverage-bracket-study-v2 (descriptive mechanics study; paper only, no orders).

Spec: ``config/leverage_bracket_study_v2.json`` (frozen before any 2021-2023 price data was loaded), inheriting
``leverage_bracket_study_v1`` + amendment 1.  This module imports the v1 engine unchanged and adds only what v2 changes:

* grid: leverage 2/3/5/10 x take-profit 10/15/20% x stop S1/S2 x time stop 24h/168h x fee model F1/F2 x 3 entries = 288;
* F2 (maker take-profit): entry taker 7 bps; the TP exit is a resting limit order that fills at the TP price only if the bar
  trades THROUGH it by 0.01% (long: ``high >= tp * 1.0001``; short: ``low <= tp * 0.9999``), maker fee 2 bps, no
  slippage; a touch-only bar does not fill and the position stays open; stop, liquidation and time-stop exits are taker
  7 bps.  The adverse-first same-bar rule is unchanged (a bar that reaches the adverse level and would also have filled
  the take-profit is counted as ambiguous and closes at the adverse level).  F1 is v1's taker model (``through = 0``);
* ruin: if the realized account equity reaches <= 0 at any point, P(ruin) = 1 and the day is reported; otherwise the
  v1 / ``leverage_sim`` stationary bootstrap is used; daily returns never divide by zero or a negative number;
* viability reading: BH over the 288 primary cells, both primary halves with a lower bound > 0, P(ruin) <= 5%, and a
  consistency-sample EV > 0.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import numpy as np

from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_data as bdata
from orderflow_edge_lab import leverage_sim
from orderflow_edge_lab import review_methods

SEED = lb.SEED
ENTRIES = lb.ENTRIES
LEVERAGES = (2, 3, 5, 10)
TAKE_PROFITS = lb.TAKE_PROFITS
STOPS = lb.STOPS
TIME_STOP_HOURS = (24, 168)
FEE_MODELS = ("F1", "F2")
THROUGH = 0.0001  # F2: the bar must trade through the take-profit price by 0.01%
TAKER_SIDE = 0.0007  # 5 bps taker + 2 bps slippage, per side, on notional
MAKER_SIDE = 0.0002  # F2 take-profit exit: 2 bps maker, no slippage
BH_Q = lb.BH_Q
MAX_RUIN = lb.MAX_RUIN
CODE_TP, CODE_STOP, CODE_LIQ, CODE_TIME = lb.CODE_TP, lb.CODE_STOP, lb.CODE_LIQ, lb.CODE_TIME


@dataclass(frozen=True)
class Cell2:
    entry: str
    leverage: int
    tp: float
    stop: str
    time_hours: int
    fee: str

    @property
    def name(self) -> str:
        return f"{self.entry}_L{self.leverage}_TP{int(round(self.tp * 100))}_{self.stop}_T{self.time_hours}_{self.fee}"

    @property
    def max_hold(self) -> int:
        return self.time_hours * 60

    @property
    def through(self) -> float:
        return THROUGH if self.fee == "F2" else 0.0


def all_cells() -> list[Cell2]:
    return [Cell2(e, lv, tp, s, th, f) for e in ENTRIES for lv in LEVERAGES for tp in TAKE_PROFITS for s in STOPS
            for th in TIME_STOP_HOURS for f in FEE_MODELS]


# ------------------------------------------------------------------------------------------------- the walk


@dataclass
class Trades2(lb.Trades):
    touch_only: np.ndarray = None  # type: ignore[assignment]  # 1 if a take-profit touch without through-fill occurred


def walk_bracket_v2(high: Any, low: Any, close: Any, direction: np.ndarray, leverage: float, tp: float, stop: str, *,
                    start_idx: int, last_idx: int | None = None, max_hold: int = lb.MAX_HOLD,
                    through: float = 0.0) -> Trades2:
    """Same walk as ``leverage_bracket.walk_bracket`` with a take-profit fill threshold: long ``high >= tpp * (1 +
    through)``, short ``low <= tpp * (1 - through)``.  ``through = 0`` reproduces v1 exactly; ``through = 0.0001`` is
    the F2 through-fill rule (a bar that only touches the take-profit price leaves the position open).  The landing bar
    of a time stop after a gap gets the same level check."""
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
    adv_d = lb.adverse_distance(leverage, stop)
    adv_code = CODE_STOP if stop == "S2" else CODE_LIQ
    up, dn = 1.0 + through, 1.0 - through
    dirs = direction.tolist()
    o_i: list[int] = []
    o_j: list[int] = []
    o_s: list[int] = []
    o_c: list[int] = []
    o_a: list[int] = []
    o_t: list[int] = []
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
        touch = 0
        if side > 0:
            tpp = entry * (1.0 + tp_d)
            thr = tpp * up
            advp = entry * (1.0 - adv_d)
            for j in range(i + 1, end + 1):
                if L[j] <= advp:
                    code = adv_code
                    amb = 1 if H[j] >= thr else 0
                    break
                if H[j] >= thr:
                    code = CODE_TP
                    break
                if H[j] >= tpp:
                    touch = 1
        else:
            tpp = entry * (1.0 - tp_d)
            thr = tpp * dn
            advp = entry * (1.0 + adv_d)
            for j in range(i + 1, end + 1):
                if H[j] >= advp:
                    code = adv_code
                    amb = 1 if L[j] <= thr else 0
                    break
                if L[j] <= thr:
                    code = CODE_TP
                    break
                if L[j] <= tpp:
                    touch = 1
        if code < 0:
            j = end
            while j <= last and C[j] != C[j]:  # no bar at the time stop: first valid close after it
                j += 1
            if j > last:
                break
            if j > end:  # bar j was not covered by the loop above: same adverse-first level check on it
                if side > 0:
                    if L[j] <= advp:
                        code, amb = adv_code, int(H[j] >= thr)
                    elif H[j] >= thr:
                        code = CODE_TP
                    elif H[j] >= tpp:
                        touch = 1
                else:
                    if H[j] >= advp:
                        code, amb = adv_code, int(L[j] <= thr)
                    elif L[j] <= thr:
                        code = CODE_TP
                    elif L[j] <= tpp:
                        touch = 1
            if code < 0:
                code = CODE_TIME
        o_i.append(i)
        o_j.append(j)
        o_s.append(side)
        o_c.append(code)
        o_a.append(amb)
        o_t.append(touch)
        k = bisect_left(cand, j, k + 1)
    return Trades2(np.asarray(o_i, dtype=np.int64), np.asarray(o_j, dtype=np.int64), np.asarray(o_s, dtype=np.int8),
                   np.asarray(o_c, dtype=np.int8), np.asarray(o_a, dtype=np.int8), np.asarray(o_t, dtype=np.int8))


# ------------------------------------------------------------------------------------------------ economics


def trade_economics_v2(trades: lb.Trades, close: np.ndarray, leverage: float, tp: float, funding_idx: np.ndarray,
                       funding_rate: np.ndarray, stop: str | None = None, fee_model: str = "F1") -> dict[str, np.ndarray]:
    """Per-trade gross / fee / funding / net in margin units.  F1 is exactly ``leverage_bracket.trade_economics``.  F2
    charges a take-profit exit entry-taker + maker (9 bps of notional) instead of the 14 bps round trip; liquidation,
    stop and time-stop trades are priced as in F1 (liquidation: liquidation fee + entry half of the cost)."""
    if fee_model == "F1":
        return lb.trade_economics(trades, close, leverage, tp, funding_idx, funding_rate, stop)
    if fee_model != "F2":
        raise ValueError(f"unknown fee model {fee_model}")
    e = lb.trade_economics(trades, close, leverage, tp, funding_idx, funding_rate, None)
    if len(trades) == 0:
        return e
    code = trades.code
    tm = code == CODE_TIME
    if stop is not None and tm.any():
        # a touch-only bar can leave the close up to 0.01% (of price) above the take-profit price
        lim = lb.adverse_distance(leverage, stop) * leverage
        slack = THROUGH * (leverage + tp)
        if not ((e["gross"][tm] >= -lim - 1e-9) & (e["gross"][tm] <= tp + slack + 1e-9)).all():
            raise AssertionError("time-stop gross outside [-adverse, take-profit + through slack]")
    fee = np.where(code == CODE_TP, (TAKER_SIDE + MAKER_SIDE) * leverage, e["fee"])
    return {"gross": e["gross"], "fee": fee, "funding": e["funding"], "net": e["gross"] - fee - e["funding"]}


def break_even_win_rate(leverage: float, tp: float, stop: str, fee_model: str = "F1") -> float:
    """Win rate at which a TP-or-loss bracket breaks even after costs (time stops ignored, as in v1)."""
    if fee_model == "F1":
        return lb.break_even_win_rate(leverage, tp, stop)
    cost = lb.FEE_ROUND_TRIP * leverage
    win = tp - (TAKER_SIDE + MAKER_SIDE) * leverage
    loss = lb.STOP_FRACTION + cost if stop == "S2" else 1.0 + (lb.LIQUIDATION_FEE + lb.FEE_ROUND_TRIP / 2) * leverage
    return loss / (win + loss)


# ------------------------------------------------------------------------------------------------ account / ruin


def simulate_account_v2(open_idx: np.ndarray, close_idx: np.ndarray, net: np.ndarray, *, n_days: int,
                        sample_start_idx: int, minutes_per_day: int = bdata.MINUTES_PER_DAY,
                        margin_fraction: float = lb.MARGIN_FRACTION) -> dict[str, Any]:
    """``leverage_bracket.simulate_account`` plus the zero rule: the first close that takes realized equity to <= 0
    ends the simulation (``ruined`` = True, ``ruin_day`` = UTC exit day of that close, 0-based from the sample start);
    later days stay at 0.  Without a ruin the numbers equal v1's."""
    n = len(open_idx)
    if n == 0:
        return {"daily_equity": np.ones(n_days), "final_equity": 1.0, "max_drawdown": 0.0, "min_equity": 1.0,
                "first_below_half_day": None, "trades": 0, "ruined": False, "ruin_day": None}
    keys = np.concatenate([close_idx * 2, open_idx * 2 + 1])
    order = np.argsort(keys, kind="stable")
    equity = 1.0
    margins: dict[int, float] = {}
    eq_after: list[float] = []
    ruin_close: int | None = None
    chunk = 1 << 20
    done = False
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
                if equity <= 0.0:
                    ruin_close = int(close_idx[t])
                    done = True
                    break
        if done:
            break
    eq = np.asarray(eq_after)
    close_sorted = np.sort(close_idx)
    ends = sample_start_idx + (np.arange(n_days) + 1) * minutes_per_day
    pos = np.minimum(np.searchsorted(close_sorted, ends, side="right"), len(eq))
    full = np.concatenate([[1.0], eq])
    daily = np.maximum(full[pos], 0.0)
    drawdown = float((full / np.maximum.accumulate(full) - 1.0).min())
    below = np.flatnonzero(eq < leverage_sim.RUIN_EQUITY_FRACTION)
    first_day = None
    if len(below):
        first_day = int((close_sorted[below[0]] - sample_start_idx - 1) // minutes_per_day)
    ruin_day = None if ruin_close is None else int((ruin_close - sample_start_idx - 1) // minutes_per_day)
    return {"daily_equity": daily, "final_equity": float(max(eq[-1], 0.0)), "max_drawdown": drawdown,
            "min_equity": float(full.min()), "first_below_half_day": first_day, "trades": int(n),
            "ruined": ruin_close is not None, "ruin_day": ruin_day}


def daily_returns_v2(daily_equity: np.ndarray) -> np.ndarray:
    """Daily returns of the equity path with a unit start.  Equity is clipped at 0 and a return is 0 whenever the
    previous equity is not strictly positive, so there is never a division by zero or by a negative number."""
    full = np.concatenate([[1.0], np.maximum(np.asarray(daily_equity, dtype=float), 0.0)])
    prev, cur = full[:-1], full[1:]
    out = np.zeros(len(cur))
    ok = prev > 0.0
    out[ok] = cur[ok] / prev[ok] - 1.0
    return out


def ruin_statistic(acct: dict[str, Any], *, ruin_indices: np.ndarray | None, seed: int = SEED) -> dict[str, Any]:
    """P(ruin) per the v2 rule: 1 by definition if the realized path reached <= 0 (with the day), otherwise the v1
    stationary-bootstrap value."""
    if acct.get("ruined"):
        return {"ruin_probability": 1.0, "historical_ruin": True, "ruin_day": acct["ruin_day"],
                "method": "realized account equity reached <= 0"}
    out = lb.ruin_summary(daily_returns_v2(acct["daily_equity"]), indices=ruin_indices, seed=seed)
    out.update(historical_ruin=False, ruin_day=None, method="leverage_sim stationary bootstrap")
    return out


# ------------------------------------------------------------------------------------------------ cell / study


def summarize_cell_v2(cell: Cell2, parts: list[tuple[lb.Trades, dict[str, np.ndarray]]], *, n_days: int,
                      start_idx: int, split_day: int, seed: int = SEED, ruin_indices: np.ndarray | None = None,
                      do_account: bool = True) -> dict[str, Any]:
    cat = lambda f: np.concatenate([f(p) for p in parts]) if parts else np.zeros(0)  # noqa: E731
    open_idx = cat(lambda p: p[0].open_idx).astype(np.int64)
    close_idx = cat(lambda p: p[0].close_idx).astype(np.int64)
    code = cat(lambda p: p[0].code).astype(np.int8)
    amb = cat(lambda p: p[0].ambiguous).astype(np.int8)
    econ = {key: cat(lambda p, key=key: p[1][key]) for key in ("gross", "fee", "funding", "net")}
    exit_day = ((close_idx - start_idx - 1) // bdata.MINUTES_PER_DAY).astype(np.int64)
    stats = lb.cell_statistics(cell, econ, code, amb, exit_day, n_days, split_day=split_day, seed=seed)
    stats.update(cell=cell.name, time_stop_hours=cell.time_hours, fee_model=cell.fee,
                 break_even_win_rate=break_even_win_rate(cell.leverage, cell.tp, cell.stop, cell.fee))
    if len(open_idx):
        touch = cat(lambda p: getattr(p[0], "touch_only", np.zeros(len(p[0]))))
        stats["trades_with_touch_only_bar"] = int(touch.sum())
    if do_account and len(open_idx):
        acct = simulate_account_v2(open_idx, close_idx, econ["net"], n_days=n_days, sample_start_idx=start_idx)
        ruin = ruin_statistic(acct, ruin_indices=ruin_indices, seed=seed)
        stats["account"] = {
            "final_equity": acct["final_equity"], "max_drawdown": acct["max_drawdown"],
            "min_equity": acct["min_equity"], "first_below_half_day": acct["first_below_half_day"],
            "ruined": acct["ruined"], "ruin_day": acct["ruin_day"],
            "daily_equity": [round(float(x), 8) for x in acct["daily_equity"]], "ruin": ruin,
        }
    return stats


def run_cell_v2(cell: Cell2, data_dir: Path | str, symbols: list[str], sample: dict[str, int], *, seed: int = SEED,
                ruin_indices: np.ndarray | None = None, do_account: bool = True) -> dict[str, Any]:
    """All symbols x one cell on one sample (``sample`` = start_idx, n_days, split_day)."""
    data_dir = Path(data_dir)
    parts = []
    for sym_i, sym in enumerate(symbols):
        high, low, close, f_idx, f_rate = bdata.load_symbol(sym, data_dir)
        close = np.asarray(close, dtype=np.float64)
        direction = lb.entry_directions(cell.entry, close, symbol_index=sym_i, seed=seed)
        trades = walk_bracket_v2(np.asarray(high, dtype=np.float64), np.asarray(low, dtype=np.float64), close,
                                 direction, cell.leverage, cell.tp, cell.stop, start_idx=sample["start_idx"],
                                 max_hold=cell.max_hold, through=cell.through)
        parts.append((trades, trade_economics_v2(trades, close, cell.leverage, cell.tp, f_idx, f_rate, cell.stop,
                                                 cell.fee)))
    return summarize_cell_v2(cell, parts, n_days=sample["n_days"], start_idx=sample["start_idx"],
                             split_day=sample["split_day"], seed=seed, ruin_indices=ruin_indices,
                             do_account=do_account)


@lru_cache(maxsize=4)
def _ruin_indices(n_days: int, seed: int) -> np.ndarray:
    return leverage_sim.stationary_bootstrap_indices(n_days, lb.RUIN_PATHS, lb.RUIN_HORIZON, lb.BOOTSTRAP_BLOCK, seed)


def _run_job(args: tuple) -> tuple[str, dict[str, Any]]:
    label, cell, data_dir, symbols, sample, seed = args
    return label, run_cell_v2(cell, data_dir, symbols, sample, seed=seed,
                              ruin_indices=_ruin_indices(sample["n_days"], seed))


def run_study_v2(samples: dict[str, tuple[Path | str, dict[str, int]]], symbols: list[str], *, workers: int = 8,
                 seed: int = SEED, cells: list[Cell2] | None = None) -> dict[str, Any]:
    """``samples``: label -> (data dir, sample dict); must contain ``primary`` and ``consistency``.  Parallel over
    (sample, cell); returns separate result lists and the v2 viability reading."""
    cells = cells if cells is not None else all_cells()
    jobs = [(label, c, str(d), list(symbols), s, seed) for label, (d, s) in samples.items()
            for c in sorted(cells, key=lambda c: (-c.leverage, c.name))]
    with Pool(max(1, workers)) as pool:
        done = list(pool.imap_unordered(_run_job, jobs))
    order = {c.name: i for i, c in enumerate(cells)}
    out: dict[str, Any] = {}
    for label in samples:
        res = sorted((r for lab, r in done if lab == label), key=lambda r: order[r["cell"]])
        out[label] = {"cells": res}
    out["viability"] = viability_reading_v2(out["primary"]["cells"], out["consistency"]["cells"])
    return out


# ------------------------------------------------------------------------------------------------ reading


def viability_reading_v2(primary: list[dict[str, Any]], consistency: list[dict[str, Any]], q: float = BH_Q,
                         max_ruin: float = MAX_RUIN) -> dict[str, Any]:
    """BH (``review_methods.bh_family``) over the primary one-sided p of every cell; a cell is viable only if BH
    rejects, both primary halves have a 95% lower bound > 0, primary P(ruin 365d) <= ``max_ruin`` and the
    consistency-sample net EV per trade is > 0 (point estimate)."""
    pvals = {c["cell"]: (c["ev_bootstrap"]["full"]["p_one_sided"] if "ev_bootstrap" in c else 1.0) for c in primary}
    bh = review_methods.bh_family(pvals, q=q)
    cons = {c["cell"]: c for c in consistency}
    rows = {}
    for c in primary:
        name = c["cell"]
        eb = c.get("ev_bootstrap")
        lo1 = eb["half1"]["lo"] if eb else None
        lo2 = eb["half2"]["lo"] if eb else None
        ruin = c.get("account", {}).get("ruin", {}).get("ruin_probability")
        cev = cons.get(name, {}).get("net_ev_pct_margin_per_trade")
        halves_ok = lo1 is not None and lo2 is not None and lo1 > 0 and lo2 > 0
        ruin_ok = ruin is not None and ruin <= max_ruin
        cons_ok = cev is not None and cev > 0
        rows[name] = {"p": bh[name]["p"], "q_value": bh[name]["q_value"], "bh_reject": bh[name]["reject"],
                      "half1_lower_bound_positive": bool(lo1 is not None and lo1 > 0),
                      "half2_lower_bound_positive": bool(lo2 is not None and lo2 > 0),
                      "ruin_ok": bool(ruin_ok), "consistency_ev_positive": bool(cons_ok),
                      "viable": bool(bh[name]["reject"] and halves_ok and ruin_ok and cons_ok)}
    return {"q": q, "max_ruin": max_ruin, "cells": rows, "n_cells": len(rows),
            "viable_cells": sorted(k for k, v in rows.items() if v["viable"])}

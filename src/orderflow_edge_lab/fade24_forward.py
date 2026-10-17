"""Fade-24h bracket paper forward watch (``fade24-forward-v1``, ``config/fade24_forward_v1.json``).

Descriptive only: no promotion, no orders, no keys.  The rule is exactly cell ``E2_L2_TP15_S2_T168`` of
leverage-bracket-study-v2 and the reviewed v2 engine is reused unchanged:

* entries ``leverage_bracket.entry_directions`` (E2 = fade the previous 1440 one-minute bars; E0 = seeded random
  direction for the control book), the walk ``leverage_bracket_v2.walk_bracket_v2``, the F1 / F2 economics
  ``leverage_bracket_v2.trade_economics_v2`` and the account ``leverage_bracket_v2.simulate_account_v2``;
* data: ``data.binance.vision`` daily futures 1m klines (parsed by ``leverage_bracket_v2_data``, stored as float32, the
  stale-tail rule of ``leverage_bracket_data``) and the monthly fundingRate files.

Forward conventions (``near_miss_forward`` pattern)
* grid: index ``i`` = bar END in minutes since ``start - 2 days`` (00:00 UTC), the v2 convention.  The scored
  positions open at a bar close strictly after the start (grid index > the start's index).
* the walk runs on arrays padded with NaN bars after the last published bar, so a position that has already hit a
  level inside the published bars is closed (and scored) as soon as its bars are published; a position whose
  outcome needs unpublished bars stays open and is listed separately with its unrealized P&L (never scored).
* per-symbol freshness: a symbol whose last bar is before the data end by at most ``LAG_WINDOW_DAYS`` is lagging;
  scoring stops at the start of the UTC day of the earliest lagging last bar (the books are pending beyond).  A
  longer gap is a stopped / delisted contract (stale-tail rule): no trades, not pending.
* funding: ``fundingRate`` is published monthly.  Settlements of an unpublished month are applied as zero and the
  trade carries ``funding_pending``; the history is replayed on every run, so a later published file replaces the
  zeros.  A settlement missing inside a published month is flagged ``funding_gap_zero_filled``.
* daily account returns are stamped at 00:00 UTC of the day AFTER the realized day, so every stamp is strictly after
  the start.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from orderflow_edge_lab import binance_spot_archive as bsa
from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_data as bdata
from orderflow_edge_lab import leverage_bracket_v2 as v2
from orderflow_edge_lab import leverage_bracket_v2_data as v2data
from orderflow_edge_lab import leverage_sim
from orderflow_edge_lab.near_miss_forward import CountingFetch, funding_hole_intervals, month_after_last
from orderflow_edge_lab.trend_portfolio_forward import summarize

WATCH_ID = "fade24-forward-v1"
DEFAULT_CONFIG = "config/fade24_forward_v1.json"
DEFAULT_UNIVERSE = "research/strategy_search_v3/round2_universe.json"

SEED = 20261017                 # bootstrap seed and the E0 seed (symbol index is the second key)
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_BLOCK = 10
NW_LAGS = 5
LAG_WINDOW_DAYS = 3             # last bar up to this long before the data end: lagging (pending), else stopped
HOLE_MIN_MINUTES = 720          # a run of missing bars this long inside a symbol's span is a hole (a missing daily file)
MINUTES_PER_DAY = 1440
WARMUP_DAYS = 2                 # klines are loaded from start - 2 days (24h lookback plus margin)
PROBE_DAYS_BACK = 10
REFERENCE_EV_PCT_MARGIN = 0.66  # the 2021-23 estimate (F1) quoted by the config
BOOKS = ("fade24_F1", "fade24_F2", "random_F1")
CODE_NAMES = {lb.CODE_TP: "take_profit", lb.CODE_STOP: "stop", lb.CODE_LIQ: "liquidation", lb.CODE_TIME: "time_stop"}
KLINE_CACHE_DIRNAME = "fade24_klines_1m"


class Fade24Error(RuntimeError):
    pass


@dataclass(frozen=True)
class BookSpec:
    name: str
    entry: str     # E2 = fade the previous 24h move, E0 = random direction
    fee: str       # F1 / F2

    @property
    def cell(self) -> v2.Cell2:
        return v2.Cell2(self.entry, 2, 0.15, "S2", 168, self.fee)


BOOK_SPECS = {"fade24_F1": BookSpec("fade24_F1", "E2", "F1"), "fade24_F2": BookSpec("fade24_F2", "E2", "F2"),
              "random_F1": BookSpec("random_F1", "E0", "F1")}


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _log(message: str) -> None:
    print(f"[fade24 {time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------------------------------ grid


@dataclass(frozen=True)
class Grid:
    """Minute grid from ``start - 2 days``: index = bar END minutes since ``origin``."""
    origin: pd.Timestamp
    length: int
    ref_idx: int       # index of the prospective start instant
    first_idx: int     # first index that may open a scored position (bar end strictly after the start)

    @property
    def origin_min(self) -> int:
        return int(self.origin.timestamp() // 60)

    def stamp(self, idx: int) -> pd.Timestamp:
        return self.origin + pd.Timedelta(minutes=int(idx))


def make_grid(start: pd.Timestamp, data_end: pd.Timestamp) -> Grid:
    origin = start - pd.Timedelta(days=WARMUP_DAYS)
    ref = WARMUP_DAYS * MINUTES_PER_DAY
    last = int((data_end - origin) / pd.Timedelta(minutes=1))
    return Grid(origin, max(last, 0) + 1, ref, ref + 1)


# ------------------------------------------------------------------------------------------------------ data


def kline_key(symbol: str, day: str) -> str:
    return bdata.KLINE_1M[1].format(s=symbol) + f"{symbol}-1m-{day}.zip"


def probe_key(day: str) -> str:
    return kline_key("BTCUSDT", day)


def _published(key: str, fetch: bsa.Fetcher) -> bool:
    try:
        fetch(bsa.data_url(key) + ".CHECKSUM")
        return True
    except bsa.ArchiveHTTPError as exc:
        if exc.status in (403, 404):
            return False
        raise


def latest_published_day(as_of: pd.Timestamp, fetch: bsa.Fetcher = bsa.http_fetch,
                         max_back: int = PROBE_DAYS_BACK) -> pd.Timestamp:
    """Latest UTC day ``d <= as_of`` whose BTCUSDT daily 1m file is published (walks back)."""
    top = _utc(as_of).normalize()
    for back in range(max_back + 1):
        day = top - pd.Timedelta(days=back)
        if _published(probe_key(day.strftime("%Y-%m-%d")), fetch):
            return day
    raise Fade24Error(f"no published 1m archive day within {max_back} days before {as_of}")


@dataclass
class SymbolData:
    name: str
    index: int                      # position in the universe (second key of the E0 seed)
    hlc: np.ndarray                 # (3, length) float64 [high, low, close] after float32 storage and the stale-tail rule
    f_idx: np.ndarray
    f_rate: np.ndarray
    cover: pd.Timestamp             # funding published for everything before this instant
    holes: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    days_missing: list[str] = field(default_factory=list)
    files: int = 0
    stale_tail_from: str | None = None

    @property
    def last_valid(self) -> int | None:
        valid = np.flatnonzero(~np.isnan(self.hlc[2]))
        return int(valid[-1]) if len(valid) else None

    def interior_holes(self) -> list[tuple[int, int]]:
        """Inclusive index ranges of runs of at least ``HOLE_MIN_MINUTES`` missing bars between the first and the last
        published bar (a missing daily file).  Shorter gaps are archive gaps the engine already handles."""
        valid = np.flatnonzero(~np.isnan(self.hlc[2]))
        if len(valid) < 2:
            return []
        gaps = np.flatnonzero(np.diff(valid) - 1 >= HOLE_MIN_MINUTES)
        return [(int(valid[g]) + 1, int(valid[g + 1]) - 1) for g in gaps]


def to_hlc(frames: Sequence[pd.DataFrame], length: int) -> np.ndarray:
    """1m frames (grid-indexed) -> ``(3, length)`` [high, low, close] stored as float32, returned as float64."""
    hlc = np.full((3, length), np.nan)
    frames = [f for f in frames if len(f)]
    if frames:
        frame = pd.concat(frames)
        frame = frame[~frame.index.duplicated(keep="first")]
        frame = frame[(frame.index >= 0) & (frame.index < length)]
        pos = frame.index.to_numpy()
        for k, col in enumerate(("high", "low", "close")):
            hlc[k, pos] = frame[col].to_numpy()
    return hlc.astype(np.float32).astype(np.float64)


def trim_stale(hlc: np.ndarray) -> tuple[np.ndarray, int | None]:
    """Stale-tail rule of ``leverage_bracket_data.load_symbol``: the trailing run of frozen placeholder bars is NaN."""
    start = bdata.stale_tail_start(hlc[0], hlc[1], hlc[2])
    if start is None:
        return hlc, None
    out = hlc.copy()
    out[:, start:] = np.nan
    return out, start


def load_symbol(symbol: str, index: int, grid: Grid, days: Sequence[str], end_day: str, *,
                fetch: bsa.Fetcher, base: Path) -> SymbolData:
    """Daily 1m files of ``days`` (those published) and the monthly funding of ``symbol``."""
    _, keys = bsa.list_all(bdata.KLINE_1M[1].format(s=symbol), fetch=fetch)
    by_day = {m.group(1): k for k in keys if k.endswith(".zip") and (m := re.search(r"(\d{4}-\d{2}-\d{2})\.zip$", k))}
    shift = v2data.GRID_START_MIN - grid.origin_min
    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for day in days:
        key = by_day.get(day)
        if key is None:
            missing.append(day)
            continue
        target = base / KLINE_CACHE_DIRNAME / bsa.safe_name(symbol) / bsa.safe_name(Path(key).name)
        frame = v2data.parse_minute_zip(bsa.download_verified(bsa.data_url(key), target, fetch=fetch))
        frame.index = frame.index + shift
        frames.append(frame)
    hlc, stale = trim_stale(to_hlc(frames, grid.length))
    fund = fa.load_dataset("funding", symbol, start=grid.origin.strftime("%Y-%m-%d"), end=end_day, fetch=fetch,
                           directory=base)
    if len(fund):
        minutes = np.asarray((fund.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(minutes=1), dtype=np.int64)
        idx = minutes - grid.origin_min
        keep = (idx >= 0) & (idx < grid.length)
        f_idx, f_rate = idx[keep].astype(np.int64), fund["rate"].to_numpy(dtype=float)[keep]
    else:
        f_idx, f_rate = np.zeros(0, dtype=np.int64), np.zeros(0)
    return SymbolData(symbol, index, hlc, f_idx, f_rate, month_after_last(pd.DatetimeIndex(fund.index)),
                      funding_hole_intervals(fund), missing, len(frames),
                      None if stale is None else str(grid.stamp(stale)))


def load_panel(symbols: Sequence[str], grid: Grid, day: pd.Timestamp, *, fetch: bsa.Fetcher, base: Path,
               workers: int = 24) -> dict[str, SymbolData]:
    first = grid.origin.normalize()
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(first, day, freq="D")] if day >= first else []
    end_day = day.strftime("%Y-%m-%d")
    if not days:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        loaded = list(pool.map(lambda it: load_symbol(it[1], it[0], grid, days, end_day, fetch=fetch, base=base),
                               enumerate(symbols)))
    return {sd.name: sd for sd in loaded}


# ------------------------------------------------------------------------------------------------- freshness


def freshness(panel: Mapping[str, SymbolData], end_idx: int, grid: Grid) -> dict[str, Any]:
    """Scoring end (a whole UTC day) and per-symbol freshness.  Lagging = last bar before the data end by at most
    ``LAG_WINDOW_DAYS``: scoring stops at the start of that bar's UTC day.  Older gaps are stopped / delisted."""
    lag = LAG_WINDOW_DAYS * MINUTES_PER_DAY
    cap = end_idx
    last_bar: dict[str, str | None] = {}
    lagging: list[str] = []
    stalled: list[str] = []
    hole_pending: list[str] = []
    holes_report: dict[str, list[dict[str, Any]]] = {}
    for name, sd in panel.items():
        last = sd.last_valid
        last_bar[name] = None if last is None else str(grid.stamp(last))
        # a hole inside the published span: recent ones are pending exactly like a lag (the effective last bar of
        # the symbol is the bar before the hole); older ones are permanent (trades over them are flagged)
        recent = False
        for a, b in sd.interior_holes():
            is_recent = end_idx - a <= lag
            holes_report.setdefault(name, []).append(
                {"start": str(grid.stamp(a)), "minutes": b - a + 1, "status": "pending" if is_recent else "permanent"})
            if is_recent and not recent:
                recent = True
                cap = min(cap, a - 1)
        if recent:
            hole_pending.append(name)
        if last is None or last >= end_idx:
            continue
        if end_idx - last <= lag:
            lagging.append(name)
            cap = min(cap, last)
        else:
            stalled.append(name)
    eff = (cap // MINUTES_PER_DAY) * MINUTES_PER_DAY
    return {"effective_end_idx": int(eff), "effective_end": str(grid.stamp(eff)), "last_bar_end": last_bar,
            "lagging_symbols": sorted(lagging), "stalled_or_delisted_symbols": sorted(stalled),
            "hole_pending_symbols": sorted(hole_pending), "holes": holes_report,
            "no_bars": sorted(n for n, sd in panel.items() if sd.last_valid is None)}


# ------------------------------------------------------------------------------------------------ the engine


@dataclass
class SymbolRun:
    trades: lb.Trades
    touch_only: np.ndarray
    econ: dict[str, np.ndarray]
    open_position: dict[str, Any] | None


def run_symbol(spec: BookSpec, sd: SymbolData, grid: Grid, *, seed: int = SEED) -> SymbolRun:
    """The v2 engine on one symbol.  Arrays are padded with ``max_hold + 1`` NaN bars so that a position resolved
    inside the published bars closes at once; one that needs unpublished bars is left open (``open_position``)."""
    cell = spec.cell
    high, low, close = sd.hlc
    pad = np.full(cell.max_hold + 1, np.nan)
    direction = lb.entry_directions(cell.entry, close, symbol_index=sd.index, seed=seed)
    direction_p = np.concatenate([direction, np.zeros(len(pad), dtype=np.int8)])
    trades = v2.walk_bracket_v2(np.concatenate([high, pad]), np.concatenate([low, pad]), np.concatenate([close, pad]),
                                direction_p, cell.leverage, cell.tp, cell.stop, start_idx=grid.first_idx,
                                max_hold=cell.max_hold, through=cell.through)
    econ = v2.trade_economics_v2(trades, close, cell.leverage, cell.tp, sd.f_idx, sd.f_rate, cell.stop, cell.fee)
    touch = np.asarray(getattr(trades, "touch_only", np.zeros(len(trades))), dtype=np.int8)
    # the open position: the first candidate at or after the last close (or the first allowed index)
    after = grid.first_idx if len(trades) == 0 else int(trades.close_idx[-1])
    cand = np.flatnonzero((direction != 0) & ~np.isnan(close))
    cand = cand[cand >= after]
    open_pos = None
    last = sd.last_valid
    if len(cand) and last is not None:
        i = int(cand[0])
        side = int(direction[i])
        entry = float(close[i])
        unreal = side * (float(close[last]) / entry - 1.0) * cell.leverage
        tp_d, adv_d = cell.tp / cell.leverage, lb.adverse_distance(cell.leverage, cell.stop)
        open_pos = {"symbol": sd.name, "side": side, "entry_time": grid.stamp(i).isoformat(), "entry_price": entry,
                    "take_profit_price": entry * (1.0 + side * tp_d), "stop_price": entry * (1.0 - side * adv_d),
                    "time_stop_time": grid.stamp(i + cell.max_hold).isoformat(),
                    "last_bar_end": grid.stamp(last).isoformat(), "last_close": float(close[last]),
                    "unrealized_gross_pct_margin": float(unreal * 100.0),
                    "entry_idx": i, "symbol_stalled": bool(last < len(close) - 1 - LAG_WINDOW_DAYS * MINUTES_PER_DAY)}
    return SymbolRun(trades, touch, econ, open_pos)


# ------------------------------------------------------------------------------------------------ statistics


def day_block_ev(day_sum: np.ndarray, day_cnt: np.ndarray, *, seed: int = SEED) -> dict[str, Any]:
    """Mean net per trade (% of margin) with the day-block (stationary) bootstrap 95% interval of the v1 engine."""
    out = lb.bootstrap_ev(day_sum, day_cnt, draws=BOOTSTRAP_DRAWS, mean_block=BOOTSTRAP_BLOCK, seed=seed)
    return {k: (None if v is None else (v * 100.0 if k in ("ev", "lo", "hi") else v)) for k, v in out.items()}


def day_block_diff(sum_a: np.ndarray, cnt_a: np.ndarray, sum_b: np.ndarray, cnt_b: np.ndarray, *,
                   seed: int = SEED) -> dict[str, Any]:
    """Mean per trade of A minus B (% of margin); the same resampled day blocks are applied to both books."""
    n = len(sum_a)
    ta, tb = float(cnt_a.sum()), float(cnt_b.sum())
    if n == 0 or ta == 0 or tb == 0:
        return {"diff": None, "lo": None, "hi": None, "draws_used": 0, "trades_a": int(ta), "trades_b": int(tb)}
    idx = leverage_sim.stationary_bootstrap_indices(n, BOOTSTRAP_DRAWS, n, BOOTSTRAP_BLOCK, seed)
    ca, cb = cnt_a[idx].sum(axis=1), cnt_b[idx].sum(axis=1)
    ok = (ca > 0) & (cb > 0)
    d = sum_a[idx].sum(axis=1)[ok] / ca[ok] - sum_b[idx].sum(axis=1)[ok] / cb[ok]
    return {"diff": float((sum_a.sum() / ta - sum_b.sum() / tb) * 100.0), "lo": float(np.percentile(d, 2.5) * 100.0),
            "hi": float(np.percentile(d, 97.5) * 100.0), "draws_used": int(ok.sum()), "trades_a": int(ta),
            "trades_b": int(tb)}


def review_reading(lo: float | None, hi: float | None, reference: float = REFERENCE_EV_PCT_MARGIN) -> str | None:
    """Review-time reading: the 2021-23 estimate is 'not contradicted' if it lies inside the forward 95% interval of
    the fade24_F1 mean net per trade, 'contradicted' otherwise.  No interval (no trades): ``None``."""
    if lo is None or hi is None:
        return None
    return "not contradicted" if lo <= reference <= hi else "contradicted"


@dataclass
class BookResult:
    spec: BookSpec
    daily: pd.Series
    trades: list[dict[str, Any]]
    day_sum: np.ndarray
    day_cnt: np.ndarray
    open_positions: list[dict[str, Any]]
    forward: dict[str, Any]
    unscored_rows: list[dict[str, Any]] = field(default_factory=list)


def cell_hold(spec: BookSpec) -> int:
    return spec.cell.max_hold


def run_book(spec: BookSpec, panel: Mapping[str, SymbolData], grid: Grid, fresh: Mapping[str, Any], *,
             seed: int = SEED) -> BookResult:
    eff = int(fresh["effective_end_idx"])
    n_days = max(0, (eff - grid.ref_idx) // MINUTES_PER_DAY)
    cols: dict[str, list] = {k: [] for k in ("open", "close", "side", "code", "amb", "touch", "gross", "fee", "funding",
                                              "net", "sym", "fpend", "fgap", "miss", "ent", "chain")}
    open_positions: list[dict[str, Any]] = []
    for sd in panel.values():
        r = run_symbol(spec, sd, grid, seed=seed)
        if r.open_position is not None:
            open_positions.append(r.open_position)
        holes = sd.interior_holes()
        permanent = [h for h in holes if grid.length - 1 - h[0] > LAG_WINDOW_DAYS * MINUTES_PER_DAY]
        t = r.trades
        n = len(t)
        if n == 0:
            continue
        close_t = [grid.stamp(int(j)) for j in t.close_idx]
        cols["fpend"].append(np.asarray([c >= sd.cover for c in close_t], dtype=bool))
        cols["fgap"].append(np.asarray([any(a < ct and b > grid.stamp(int(oi)) for a, b in sd.holes)
                                        for ct, oi in zip(close_t, t.open_idx)], dtype=bool))
        first_perm = permanent[0][0] if permanent else None
        cols["chain"].append(np.asarray([first_perm is not None and oi > first_perm for oi in t.open_idx.tolist()],
                                        dtype=bool))
        cols["ent"].append(np.asarray([any(a - cell_hold(spec) <= oi <= b + MINUTES_PER_DAY for a, b in holes)
                                       for oi in t.open_idx.tolist()], dtype=bool))
        cols["miss"].append(np.asarray([any(a <= cj and b >= oi - lb.LOOKBACK for a, b in holes)
                                        for cj, oi in zip(t.close_idx.tolist(), t.open_idx.tolist())], dtype=bool))
        for key, arr in (("open", t.open_idx), ("close", t.close_idx), ("side", t.side), ("code", t.code),
                         ("amb", t.ambiguous), ("touch", r.touch_only), ("gross", r.econ["gross"]),
                         ("fee", r.econ["fee"]), ("funding", r.econ["funding"]), ("net", r.econ["net"]),
                         ("sym", np.full(n, sd.index))):
            cols[key].append(np.asarray(arr))
    cat = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
    order = np.lexsort((cat["sym"], cat["open"], cat["close"])) if len(cat["close"]) else np.zeros(0, dtype=int)
    cat = {k: v[order] for k, v in cat.items()}
    scored = cat["close"] <= eff if len(cat["close"]) else np.zeros(0, dtype=bool)
    s = {k: v[scored] for k, v in cat.items()}
    n_scored = int(scored.sum())
    names = {sd.index: sd.name for sd in panel.values()}
    def rows(d: Mapping[str, np.ndarray], count: int) -> list[dict[str, Any]]:
        return [{"symbol": names[int(d["sym"][k])], "open_time": grid.stamp(int(d["open"][k])).isoformat(),
                 "close_time": grid.stamp(int(d["close"][k])).isoformat(), "side": int(d["side"][k]),
                 "exit": CODE_NAMES[int(d["code"][k])], "net_pct_margin": float(d["net"][k] * 100.0),
                 "funding_pending": bool(d["fpend"][k]), "funding_gap_zero_filled": bool(d["fgap"][k]),
                 "bars_missing_in_window": bool(d["miss"][k]),
                 "chain_after_permanent_hole": bool(d["chain"][k])} for k in range(count)]

    trade_rows = rows(s, n_scored)
    unscored_open = cat["open"][~scored] if len(scored) else np.zeros(0)
    n_unscored = int((~scored).sum()) if len(scored) else 0
    unscored_rows = rows({k: v[~scored] for k, v in cat.items()} if len(scored) else cat, n_unscored)
    stamps = pd.DatetimeIndex([grid.stamp(grid.ref_idx + (k + 1) * MINUTES_PER_DAY) for k in range(n_days)])
    exit_day = ((s["close"].astype(np.int64) - grid.ref_idx - 1) // MINUTES_PER_DAY) if n_scored else np.zeros(0, int)
    day_sum = np.bincount(exit_day, weights=s["net"], minlength=n_days).astype(float) if n_days else np.zeros(0)
    day_cnt = np.bincount(exit_day, minlength=n_days).astype(float) if n_days else np.zeros(0)
    if n_days and n_scored:
        acct = v2.simulate_account_v2(s["open"].astype(np.int64), s["close"].astype(np.int64), s["net"],
                                      n_days=n_days, sample_start_idx=grid.ref_idx)
        daily = v2.daily_returns_v2(acct["daily_equity"])
    else:
        acct = {"final_equity": 1.0, "max_drawdown": 0.0, "min_equity": 1.0, "ruined": False, "ruin_day": None}
        daily = np.zeros(n_days)
    series = pd.Series(daily, index=stamps, dtype=float)
    code = s["code"].astype(int)
    share = lambda c: float((code == c).mean()) if n_scored else None  # noqa: E731
    out = summarize(series, nw_lags=NW_LAGS)
    ev = day_block_ev(day_sum, day_cnt, seed=SEED)
    clean = ~s["fpend"].astype(bool)
    # descriptive interim fields (they do not change the scored series): the entry cohort that has had its full window
    horizon = eff - spec.cell.max_hold
    mature = ((s["open"] <= horizon) & ~s["ent"].astype(bool)) if n_scored else np.zeros(0, bool)
    late_closing = int(((unscored_open <= horizon)).sum()) if len(unscored_open) else 0
    open_old = sum(1 for p in open_positions if p["entry_idx"] <= horizon)
    m_sum = np.bincount(exit_day[mature], weights=s["net"][mature], minlength=n_days).astype(float) if n_days else np.zeros(0)
    m_cnt = np.bincount(exit_day[mature], minlength=n_days).astype(float) if n_days else np.zeros(0)
    m_ev = day_block_ev(m_sum, m_cnt, seed=SEED)
    round_trip_pct = lb.FEE_ROUND_TRIP * spec.cell.leverage * 100.0
    for p in open_positions:
        p["unrealized_net_of_round_trip_fee_pct_margin"] = p["unrealized_gross_pct_margin"] - round_trip_pct
    unreal = np.asarray([p["unrealized_net_of_round_trip_fee_pct_margin"] for p in open_positions])
    out.update(
        matured_entry_cohort={
            "definition": "scored trades opened at least max_hold (10080 min) before the scoring end, excluding "
                          "entries opened in [hole_start - 10080 min, hole_end + 1440 min] of any hole of their symbol "
                          "(entry time only).  It omits (and counts below) entries on stalled symbols that never "
                          "closed and entries of that age whose time stop landed on a short gap and closed after the "
                          "scoring end",
            "n": int(mature.sum()), "mean_net_pct_margin": m_ev["ev"], "ev_ci95_pct_margin": [m_ev["lo"], m_ev["hi"]],
            "omitted_matured_age_entries_still_open_or_stalled": open_old,
            "omitted_matured_age_entries_closed_after_scoring_end": late_closing},
        trades_chain_after_permanent_hole=int(s["chain"].sum()) if n_scored else 0,
        open_positions_mark_to_market={
            "n": len(open_positions), "sum_unrealized_net_pct_margin": float(unreal.sum()),
            "mean_unrealized_net_pct_margin": float(unreal.mean()) if len(unreal) else None,
            "round_trip_fee_pct_margin": round_trip_pct,
            "note": "last close vs entry, minus the taker round trip; funding not included"},
        trades_bars_missing_in_window=int(s["miss"].sum()) if n_scored else 0)
    out.update(
        trades=n_scored,
        mean_net_pct_margin_per_trade=ev["ev"], ev_ci95_pct_margin=[ev["lo"], ev["hi"]],
        take_profit_share=share(lb.CODE_TP), stop_share=share(lb.CODE_STOP), time_stop_share=share(lb.CODE_TIME),
        liquidation_share=share(lb.CODE_LIQ),
        same_bar_ambiguous=int(s["amb"].sum()) if n_scored else 0,
        trades_with_touch_only_bar=int(s["touch"].sum()) if n_scored else 0,
        mean_gross_pct_margin_per_trade=float(s["gross"].mean() * 100.0) if n_scored else None,
        mean_fee_pct_margin_per_trade=float(s["fee"].mean() * 100.0) if n_scored else None,
        mean_funding_pct_margin_per_trade=float(s["funding"].mean() * 100.0) if n_scored else None,
        funding_pending_trades=int(s["fpend"].sum()) if n_scored else 0,
        funding_gap_zero_filled_trades=int(s["fgap"].sum()) if n_scored else 0,
        mean_net_pct_margin_excluding_funding_pending=(float(s["net"][clean].mean() * 100.0)
                                                       if n_scored and clean.any() else None),
        closed_trades_not_yet_scored=int((~scored).sum()) if len(scored) else 0,
        open_positions=len(open_positions),
        account_final_equity=float(acct["final_equity"]), account_max_drawdown_event_level=float(acct["max_drawdown"]),
        account_min_equity=float(acct["min_equity"]), account_ruined=bool(acct["ruined"]),
        account_ruin_day=acct["ruin_day"])
    return BookResult(spec, series, trade_rows, day_sum, day_cnt, open_positions, out, unscored_rows)


# ------------------------------------------------------------------------------------------------- assembly


def _series_dict(series: pd.Series) -> dict[str, float]:
    return {ts.isoformat(): float(v) for ts, v in series.dropna().items()}


def scored_day_digests(rows: Sequence[Mapping[str, Any]], daily: pd.Series) -> dict[str, str]:
    """Stamp (00:00 UTC of the day after the realized day) -> sha256 of that day's scored trades and daily return.
    A later change of any scored trade or return shows up as a changed digest (a revision)."""
    by_stamp: dict[str, list[Mapping[str, Any]]] = {}
    for t in rows:
        stamp = (pd.Timestamp(t["close_time"]) - pd.Timedelta(minutes=1)).normalize() + pd.Timedelta(days=1)
        by_stamp.setdefault(stamp.isoformat(), []).append(t)
    out = {}
    for ts, value in daily.items():
        key = ts.isoformat()
        payload = json.dumps({"trades": sorted(by_stamp.get(key, []), key=lambda t: (t["open_time"], t["symbol"])),
                              "daily_return": round(float(value), 12)}, sort_keys=True)
        out[key] = sha256(payload.encode("utf-8")).hexdigest()
    return out


def compare_digests(previous: Mapping[str, Mapping[str, str]] | None,
                    current: Mapping[str, Mapping[str, str]]) -> dict[str, list[str]]:
    """Per book, the stamps present in both digests whose digest changed (days that are new are not revisions)."""
    if not previous:
        return {book: [] for book in current}
    return {book: sorted(k for k, v in days.items() if k in previous.get(book, {}) and previous[book][k] != v)
            for book, days in current.items()}


def build_report(config: Mapping[str, Any], books: Mapping[str, BookResult], fresh: Mapping[str, Any], *,
                 as_of: Any, data_end: pd.Timestamp, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise Fade24Error("wrong watch config")
    as_of_ts = _utc(as_of)
    start = _utc(config["prospective_start_utc"])
    series = {n: books[n].daily for n in BOOKS}
    if any((len(s) and s.index.min() <= start) for s in series.values()):
        raise Fade24Error("a scored daily stamp is not strictly after the prospective start")
    days = max((len(s) for s in series.values()), default=0)
    for n in BOOKS:  # guard: every scored trade opens strictly after the start
        if any(pd.Timestamp(t["open_time"]) <= start for t in books[n].trades):
            raise Fade24Error("a scored trade opened at or before the prospective start")
    review_days = int(config["reporting"]["review_after_days"])
    window_open = bool((as_of_ts - start).days >= review_days)
    scored_days = len(series["fade24_F1"])
    f1 = books["fade24_F1"].forward
    diff = day_block_diff(books["fade24_F1"].day_sum, books["fade24_F1"].day_cnt, books["random_F1"].day_sum,
                          books["random_F1"].day_cnt, seed=SEED)
    lo, hi = f1["ev_ci95_pct_margin"]
    review = {"reference_ev_pct_margin_per_trade_F1": REFERENCE_EV_PCT_MARGIN, "review_after_days": review_days,
              "window_open": window_open, "as_of_days_since_start": int((as_of_ts - start).days),
              "scored_days": scored_days,
              "reading": review_reading(lo, hi) if (window_open and scored_days >= review_days) else None,
              "note": "descriptive only; a selected cell, one sample; no claim of an edge"}
    report: dict[str, Any] = {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "data_end_utc": data_end.isoformat(),
        "review_window_open": window_open,
        "forward": {n: books[n].forward for n in BOOKS},
        "comparison_fade24_F1_minus_random_F1": diff,
        "review": review,
        "daily_returns": {n: _series_dict(series[n]) for n in BOOKS},
        "open_positions": {n: books[n].open_positions for n in BOOKS},
        "scored_day_digests": {n: scored_day_digests(books[n].trades, series[n]) for n in BOOKS},
        "closed_not_yet_scored": {n: books[n].unscored_rows for n in BOOKS},
        "interim_biased_until": (start + pd.Timedelta(days=7 + LAG_WINDOW_DAYS)).isoformat(),
        "interim_censoring_note": "until the 7-day time stop of the first entries has passed (plus the lag window), "
                                  "closed trades over-represent fast take-profits and the scored mean is biased "
                                  "upward; matured_entry_cohort (per book) is the view that is not biased by this at any date, and "
                                  "open_positions_mark_to_market shows the open side",
        "trades": {n: books[n].trades for n in BOOKS},
        "pending": {"effective_end_utc": fresh["effective_end"], "lagging_symbols": fresh["lagging_symbols"],
                    "hole_pending_symbols": fresh["hole_pending_symbols"], "holes": fresh["holes"],
                    "stalled_or_delisted_symbols": fresh["stalled_or_delisted_symbols"],
                    "closed_trades_not_yet_scored": {n: books[n].forward["closed_trades_not_yet_scored"] for n in BOOKS}},
        "freshness": dict(fresh),
        "stamp_convention": "daily realized account return of UTC day d is stamped at 00:00 UTC of day d+1",
        "claims": dict(config["claims"]),
    }
    if extra:
        report.update(dict(extra))
    return report


def evaluate(config: Mapping[str, Any], panel: Mapping[str, SymbolData], grid: Grid, data_end: pd.Timestamp, *,
             as_of: Any, seed: int = SEED, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The three books on an in-memory panel; ``random_F1`` draws its directions from ``[seed, symbol index]``."""
    end_idx = grid.length - 1
    fresh = freshness(panel, end_idx, grid)
    books = {n: run_book(BOOK_SPECS[n], panel, grid, fresh, seed=seed) for n in BOOKS}
    return build_report(config, books, fresh, as_of=as_of, data_end=data_end, extra=extra)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value)}")


def run(config: Mapping[str, Any], *, as_of: Any, fetch: bsa.Fetcher, symbols: Sequence[str],
        cache_root: Path | None = None, workers: int = 24) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of_ts = _utc(as_of)
    t0 = time.time()
    day = latest_published_day(as_of_ts, fetch)
    data_end = day + pd.Timedelta(days=1)
    _log(f"latest published archive day {day.date()}")
    base = fa.cache_dir() if cache_root is None else cache_root / fa.CACHE_DIRNAME
    grid = make_grid(start, data_end)
    panel = load_panel(symbols, grid, day, fetch=fetch, base=base, workers=workers)
    _log(f"loaded {len(panel)} symbols after {time.time() - t0:.0f}s")
    coverage = {n: {"files": sd.files, "bars": int((~np.isnan(sd.hlc[2])).sum()), "days_missing": sd.days_missing,
                    "stale_tail_from": sd.stale_tail_from, "funding_rows": int(len(sd.f_idx)),
                    "funding_covered_through": sd.cover.isoformat()} for n, sd in panel.items()}
    report = evaluate(config, panel, grid, data_end, as_of=as_of_ts,
                      extra={"data": {"latest_published_day": day.strftime("%Y-%m-%d"), "probe": probe_key("<day>"),
                                      "grid_origin_utc": grid.origin.isoformat(), "symbols_requested": len(symbols),
                                      "symbols_loaded": len(panel), "coverage": coverage}})
    report["data"]["elapsed_seconds"] = round(time.time() - t0, 1)
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the fade-24h bracket paper forward watch (descriptive only).")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None, help="UTC timestamp (default: now): the latest archive day probed is "
                        "the UTC day of this instant; it does not hide later data from a published day")
    parser.add_argument("--cache-root", default=None, help="directory holding the archive cache (default: the "
                        "futures archive's own cache)")
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    universe = json.loads(Path(args.universe).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    fetch = CountingFetch(bsa.http_fetch)
    report = run(config, as_of=as_of, fetch=fetch, symbols=[str(s) for s in universe["symbols"]],
                 cache_root=None if args.cache_root is None else Path(args.cache_root), workers=args.workers)
    report["data"]["http_requests"] = fetch.requests
    report["data"]["http_megabytes"] = round(fetch.bytes / 1e6, 2)
    report["provenance"] = {"config_sha256": sha256(Path(args.config).read_bytes()).hexdigest(),
                            "universe_sha256": sha256(Path(args.universe).read_bytes()).hexdigest(),
                            "cell": BOOK_SPECS["fade24_F1"].cell.name, "seed": SEED}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False, default=_json_default) + "\n",
                   encoding="utf-8")
    cov = report["data"]["coverage"]
    print(json.dumps({"status": report["status"], "data_end_utc": report["data_end_utc"],
                      "days": {k: v["days"] for k, v in report["forward"].items()},
                      "symbols_loaded": report["data"]["symbols_loaded"],
                      "symbols_with_bars": sum(1 for v in cov.values() if v["bars"]),
                      "lagging": report["pending"]["lagging_symbols"],
                      "elapsed_seconds": report["data"]["elapsed_seconds"],
                      "http_requests": fetch.requests, "http_megabytes": report["data"]["http_megabytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

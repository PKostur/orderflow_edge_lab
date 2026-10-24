"""Near-miss paper forward watch (``near-miss-forward-v1``, ``config/near_miss_forward_v1.json``).

Descriptive only: no promotion, no orders, no keys.  Three sleeves, each reusing the existing tested code path so the
forward rule is the backtested rule:

* ``cascade`` (1x, 2x): ``liquidation_cascade.cascade_weights`` / ``make_inputs`` / ``build_trades`` with the round-2
  parameters (``lc.candidate_spec`` of ``config/strategy_search_v3_round2.json``, amendment 1), the leverage model of
  ``leverage_sim`` (mark-price liquidation with the perp high / low fallback of ``mark_with_perp_fallback``).
* ``ctrend`` (1x): ``ctrend.ctrend_weights`` + ``strategy_search_round2.buy_and_hold_detail`` at 20 bps round trip
  (10 bps per side), the Binance spot USDT universe of ``binance_spot_archive``.
* ``trend_core`` (1x, 2x): ``trend_core_leverage.run_sleeves_detailed`` / ``simulate_level`` (crypto-trend-core-v1 on
  Binance perps, 8h bars, 20 bps, Binance funding).

Data come only from data.binance.vision (no REST).  The archive lags about a day: the data end is the latest UTC day for
which every required file family is published; anything that needs later bars is listed as pending, never scored.
``fundingRate`` is published monthly: settlements of an unpublished month are applied as zero and the affected trades or
episodes carry ``funding_pending``; the history is replayed on every run, so a later published file replaces the zeros.

Only trades / episodes / weeks that start strictly after ``prospective_start_utc`` are scored; earlier history is
replayed only to form signals.  Each sleeve replays from a fixed warm-up start (not from the start of the data):
``scripts/near_miss_forward_reference.py`` checks that these truncated replays reproduce the full-history rule.

Bands: the forward cumulative return's percentile among stationary-bootstrap paths (``leverage_sim``) of the sleeve's
already-seen daily returns (``research/near_miss_forward/reference_daily_v1.json``), as backtested and demeaned.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from orderflow_edge_lab import binance_futures_metrics as bfm
from orderflow_edge_lab import binance_spot_archive as bsa
from orderflow_edge_lab import ctrend
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import strategy_search_round2 as r2
from orderflow_edge_lab import trend_core_leverage as tcl
from orderflow_edge_lab.trend_portfolio_forward import summarize

WATCH_ID = "near-miss-forward-v1"
DEFAULT_CONFIG = "config/near_miss_forward_v1.json"
DEFAULT_REFERENCE = "research/near_miss_forward/reference_daily_v1.json"
DEFAULT_UNIVERSE = "research/strategy_search_v3/round2_universe.json"
DEFAULT_ROUND2_CONFIG = "config/strategy_search_v3_round2.json"
DEFAULT_CORE_CONFIG = "config/crypto_trend_core_v1.json"

NW_LAGS = 5
BAND_PATHS = 5000
BAND_MEAN_BLOCK = 10
BAND_SEED = 20261013
BAND_QUANTILES = (5, 25, 50, 75, 95)
BOOKS = ("cascade_1x", "cascade_2x", "ctrend_1x", "trend_core_1x", "trend_core_2x")
CASCADE_LEVELS = (1, 2)
TREND_LEVELS = (1, 2)
CASCADE_WARMUP_DAYS = 7           # replay start = start - 7 days (open positions and the 10-slot limit settle)
CTREND_HISTORY_START = "2024-01-01"  # verified: weights equal the full-history weights (2025-01-01 was too short by ~6 weeks)
TREND_HISTORY_START = "2026-01-01"   # >> 180-bar vol window, 96-bar slow EMA, 55-bar channel
WARMUP_STEPS_DAYS = (7, 14, 21, 28, 35, 42, 49, 56, 60)  # replay-start search (flat-window proof), fails beyond 60
LAG_WINDOW_DAYS = 3    # a symbol whose last bar is up to this long before the data end is lagging (not delisted)
OI_TOLERANCE = pd.Timedelta(minutes=5 + int(lc.STALE_EVENT_OI_MINUTES))  # OI usable to last record + 5 min + 30 min
PROBE_DAYS_BACK = 10
LAGGING_SHARE = 0.10
CTREND_COST_BPS_ROUND_TRIP = r2.CRYPTO_COST_BPS_ROUND_TRIP


class NearMissError(RuntimeError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _log(message: str) -> None:
    print(f"[near-miss {time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------------------------- archive probes


class CountingFetch:
    """Wraps a fetcher and counts requests and bytes (reported in the run's ``data`` block)."""

    def __init__(self, inner: bsa.Fetcher) -> None:
        self.inner = inner
        self.requests = 0
        self.bytes = 0
        self._lock = threading.Lock()

    def __call__(self, url: str) -> bytes:
        body = self.inner(url)
        with self._lock:
            self.requests += 1
            self.bytes += len(body)
        return body


def _published(key: str, fetch: bsa.Fetcher) -> bool:
    try:
        fetch(bsa.data_url(key) + ".CHECKSUM")
        return True
    except bsa.ArchiveHTTPError as exc:
        if exc.status in (403, 404):
            return False
        raise


def probe_keys(day: str) -> dict[str, str]:
    """One representative daily file per required family (BTCUSDT) for UTC ``day``."""
    return {
        "spot": f"data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-{day}.zip",
        "perp": f"data/futures/um/daily/klines/BTCUSDT/1h/BTCUSDT-1h-{day}.zip",
        "mark": f"data/futures/um/daily/markPriceKlines/BTCUSDT/1h/BTCUSDT-1h-{day}.zip",
        "metrics": bfm.metrics_key("BTCUSDT", day),
    }


def latest_published_day(as_of: pd.Timestamp, fetch: bsa.Fetcher = bsa.http_fetch,
                         max_back: int = PROBE_DAYS_BACK) -> pd.Timestamp:
    """Latest UTC day ``d <= as_of`` whose daily files are published in every required family (walks back)."""
    top = _utc(as_of).normalize()
    for back in range(max_back + 1):
        day = top - pd.Timedelta(days=back)
        keys = probe_keys(day.strftime("%Y-%m-%d"))
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            ok = list(pool.map(lambda k: _published(k, fetch), keys.values()))
        if all(ok):
            return day
    raise NearMissError(f"no published archive day within {max_back} days before {as_of}")


# ----------------------------------------------------------------------------------------------- funding pending


EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def month_after_last(index: pd.DatetimeIndex) -> pd.Timestamp:
    """First instant after the calendar month of the last settlement: funding is published monthly, so everything
    before it is covered by a published file (everything at or after it is not).  No settlements: nothing is covered."""
    if len(index) == 0:
        return EPOCH
    last = pd.Timestamp(index[-1]).tz_convert("UTC")
    return pd.Timestamp(year=last.year, month=last.month, day=1, tz="UTC") + pd.offsets.MonthBegin(1)


def covered_through(funding: Mapping[str, pd.DataFrame]) -> dict[str, pd.Timestamp]:
    return {s: month_after_last(pd.DatetimeIndex(f.index)) for s, f in funding.items()}


# ----------------------------------------------------------------------------------------------- cascade sleeve


def load_cascade_data(symbols: Sequence[str], *, replay_start: pd.Timestamp, end: str,
                      fetch: bsa.Fetcher = bsa.http_fetch, futures_dir: Path | None = None,
                      metrics_dir: Path | None = None, workers: int = 24) -> dict[str, Any]:
    """Perp (close, volume), funding, mark and 5-minute OI of the universe from ``replay_start`` (monthly zips of the
    start month on, daily files for the months after the last monthly one).  Contracts without perp data are listed in
    ``unlisted`` and simply produce no events."""
    start = replay_start.strftime("%Y-%m-%d")
    trim = replay_start - pd.Timedelta(days=1)
    base = futures_dir if futures_dir is not None else fa.cache_dir()

    def work(sym: str) -> tuple[str, dict[str, pd.DataFrame]]:
        return sym, {ds: fa.load_dataset(ds, sym, end=end, start=start, fetch=fetch, directory=base)
                     for ds in ("perp", "funding", "mark")}

    perp: dict[str, pd.DataFrame] = {}
    perp_hl: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    mark: dict[str, pd.DataFrame] = {}
    unlisted: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, parts in pool.map(work, list(symbols)):
            p = parts["perp"]
            p = p.loc[p.index >= trim]
            if len(p) == 0:
                unlisted.append(sym)
                continue
            perp[sym] = p[list(fa.PERP_KEEP)]
            perp_hl[sym] = p[list(fa.MARK_KEEP)]
            funding[sym] = parts["funding"]
            m = parts["mark"]
            m = m.loc[m.index >= trim]
            if len(m):
                mark[sym] = m[list(fa.MARK_KEEP)]
    metrics = bfm.load_metrics_universe(list(perp), start=(replay_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                                        end=end, workers=workers, fetch=fetch, directory=metrics_dir)
    return {"perp": perp, "oi": metrics["oi"], "funding": funding, "mark": mark, "perp_hl": perp_hl,
            "unlisted": unlisted, "oi_provenance": metrics["provenance"]}


def cascade_params(round_cfg: Mapping[str, Any], replay_start: pd.Timestamp) -> dict[str, Any]:
    """The round-2 parameters (``candidate_spec``: thresholds, hold, lookback) with the entry gate moved to the replay start."""
    spec = lc.candidate_spec(round_cfg)
    return {**spec["params"], "trade_start": replay_start.isoformat()}


@dataclass
class CascadeReplay:
    trades: pd.DataFrame          # every taken trade of the replay (entry >= replay start)
    weights: pd.DataFrame
    inputs: lc.CascadeInputs
    grid_end: pd.Timestamp
    params: dict[str, Any]


def cascade_replay(universe: Mapping[str, Any], params: Mapping[str, Any]) -> CascadeReplay:
    inputs = lc.make_inputs(universe, max_exit=None)
    weights = lc.cascade_weights(inputs.data, params)
    trades = lc.build_trades(weights, inputs, None, lc.COST_BPS_ROUND_TRIP)
    return CascadeReplay(trades, weights, inputs, inputs.data["close"].index[-1], dict(weights.attrs["params"]))


def cascade_pending(replay: CascadeReplay, start: pd.Timestamp, data_end: pd.Timestamp) -> list[dict[str, Any]]:
    """Entries after the start whose 24h exit is not yet scorable: decided but the exit bar (or the end of the exit's
    UTC day) is not published, or the exit price is unusable."""
    w = replay.weights
    values = w.fillna(0.0).to_numpy(dtype=float)
    rows, cols = np.nonzero(values)
    taken = set(zip(replay.trades["row"].tolist(), replay.trades["col"].tolist()))
    hold = pd.Timedelta(hours=int(replay.params["hold_hours"]))
    close_idx = replay.inputs.data["close"].index
    out = []
    for r, c in zip(rows.tolist(), cols.tolist()):
        entry = close_idx[r]
        if entry <= start:
            continue
        due = entry + hold
        if (r, c) in taken and due < data_end:
            continue
        reason = "exit not yet published" if due >= data_end else "exit price unusable"
        out.append({"symbol": str(w.columns[c]), "entry_time": entry.isoformat(), "side": int(np.sign(values[r, c])),
                    "exit_due": due.isoformat(), "reason": reason})
    return out


def funding_hole_intervals(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(previous, next) settlement pairs of a published funding frame whose gap exceeds 1.5 x the median gap (a missing
    settlement inside published months)."""
    idx = pd.DatetimeIndex(frame.index)
    if len(idx) < 3:
        return []
    gaps = np.diff(idx.as_unit("ns").asi8)
    limit = 1.5 * float(np.median(gaps))
    return [(idx[i], idx[i + 1]) for i in np.flatnonzero(gaps > limit)]


class WarmupNotFlat(NearMissError):
    """No 24h window without a tradable raw event inside [replay_start + 4h, start]."""


def warmup_window(event_times: Sequence[pd.Timestamp], replay_start: pd.Timestamp, start: pd.Timestamp
                  ) -> dict[str, str] | None:
    """A 24h window inside ``[replay_start + 4h, start]`` with no tradable raw event after its first instant.

    After such a window every position opened before it has exited (24h hold) and none was opened inside it, so the
    replay from ``replay_start`` and any longer replay are both flat there and identical afterwards.  Returns the
    first such window or ``None``."""
    lo = replay_start + pd.Timedelta(hours=int(lc.DEFAULT_PARAMS["lookback_hours"]))
    marks = [lo] + sorted(t for t in event_times if lo < t <= start) + [start]
    day = pd.Timedelta(hours=24)
    for a, b in zip(marks[:-1], marks[1:]):
        if b - a >= day:
            return {"window_start": a.isoformat(), "window_end": (a + day).isoformat(),
                    "flat_from": (a + day).isoformat()}
    return None


def tradable_event_times(inputs: lc.CascadeInputs, params: Mapping[str, Any]) -> list[pd.Timestamp]:
    ev = lc.event_matrices(inputs.data, params)
    any_ev = (ev["long"] | ev["short"]).any(axis=1)
    return list(inputs.data["close"].index[any_ev])


def effective_end(universe: Mapping[str, Any], data_end: pd.Timestamp) -> tuple[pd.Timestamp, dict[str, Any]]:
    """Scoring end and per-symbol freshness.  A day is scored only when every lagging symbol is complete for it:
    the end is the data end capped by the earliest last perp bar of a lagging symbol and by the earliest
    ``OI evaluable through + 24h`` (an entry after it cannot be evaluated, and it would exit 24h later), floored to a day."""
    lag = pd.Timedelta(days=LAG_WINDOW_DAYS)
    cap = data_end
    perp_last, oi_last, oi_through, lagging_perp, lagging_oi = {}, {}, {}, [], []
    for sym, frame in universe["perp"].items():
        last = frame.index[-1]
        perp_last[sym] = last.isoformat()
        if last < data_end and data_end - last <= lag:
            lagging_perp.append(sym)
            cap = min(cap, last)
        oi = universe["oi"].get(sym)
        o = None if oi is None or len(oi) == 0 else oi.index[-1]
        oi_last[sym] = None if o is None else o.isoformat()
        if o is None:
            continue
        through = o + OI_TOLERANCE
        oi_through[sym] = through.isoformat()
        if through < data_end and data_end - through <= lag:
            lagging_oi.append(sym)
            cap = min(cap, through + pd.Timedelta(hours=24))
    eff = cap.floor("D")
    return eff, {"effective_end": eff.isoformat(), "data_end": data_end.isoformat(), "perp_last_bar": perp_last,
                 "oi_last_record": oi_last, "oi_evaluable_through": oi_through,
                 "lagging_perp_symbols": sorted(lagging_perp), "lagging_oi_symbols": sorted(lagging_oi)}


def scored_cascade_trades(replay: CascadeReplay, start: pd.Timestamp, data_end: pd.Timestamp,
                          funding_cover: Mapping[str, pd.Timestamp],
                          holes: Mapping[str, Sequence[tuple[pd.Timestamp, pd.Timestamp]]] | None = None
                          ) -> pd.DataFrame:
    """Taken trades with entry strictly after the start and the exit day complete (exit before the effective end), with
    ``funding_pending`` (a settlement in (entry, exit] falls into an unpublished funding month) and
    ``funding_gap_zero_filled`` (the interval overlaps a missing settlement inside a published month)."""
    t = replay.trades
    keep = (t["entry_time"] > start) & (t["exit_time"] < data_end)
    sel = t.loc[keep].copy().reset_index(drop=True)
    if sel.empty:
        sel["funding_pending"] = pd.Series(dtype=bool)
        sel["funding_gap_zero_filled"] = pd.Series(dtype=bool)
        return sel
    cover = pd.DatetimeIndex([funding_cover.get(k, EPOCH) for k in sel["mark_key"]])
    sel["funding_pending"] = np.asarray(pd.DatetimeIndex(sel["exit_time"]) >= cover, dtype=bool)
    holes = holes or {}
    sel["funding_gap_zero_filled"] = [
        any(a < r.exit_time and b > r.entry_time for a, b in holes.get(r.mark_key, ())) for r in sel.itertuples()]
    return sel


def cascade_book(scored: pd.DataFrame, frames: Mapping[str, pd.DataFrame], level: int, first_stamp: pd.Timestamp,
                 last_stamp: pd.Timestamp) -> tuple[pd.Series, int, list[dict[str, Any]]]:
    """Daily account returns (stamped by exit day, zero-filled over the scored days) at ``level`` with mark-price
    liquidation: ``leverage_sim.simulate_leverage`` on the trade book, as ``assess_trade_book`` does."""
    days = pd.date_range(first_stamp, last_stamp, freq="D", tz="UTC") if last_stamp >= first_stamp else \
        pd.DatetimeIndex([], tz="UTC")
    if scored.empty:
        return pd.Series(0.0, index=days), 0, []
    positions = scored[["entry_time", "exit_time", "symbol", "mark_key", "weight", "entry_price", "unit_return"]
                       ].reset_index(drop=True)
    costs = pd.Series(scored["cost"].to_numpy(), index=pd.DatetimeIndex(scored["exit_time"]))
    adverse, _ = lev.position_adverse_excursions(positions, frames)
    stamped = positions.assign(entry_time=positions["exit_time"])
    sim = lev.simulate_leverage(stamped, adverse, costs, level)
    daily = sim["daily_returns"].reindex(days).fillna(0.0)
    hit = np.asarray(lev.is_liquidated(adverse, level), dtype=bool)
    liquidated = [{"symbol": str(positions["symbol"].iloc[i]), "entry_time": positions["entry_time"].iloc[i].isoformat(),
                   "exit_time": positions["exit_time"].iloc[i].isoformat()} for i in np.flatnonzero(hit)]
    return daily, int(hit.sum()), liquidated


@dataclass
class BookResult:
    daily: pd.Series
    daily_no_pending: pd.Series
    trades: int
    liquidations: int
    funding_pending: int
    detail: dict[str, Any] = field(default_factory=dict)
    funding_gap_zero_filled: int = 0


def cascade_sleeve(universe: Mapping[str, Any], round_cfg: Mapping[str, Any], start: pd.Timestamp,
                   data_end: pd.Timestamp, *, warmup_days: int = CASCADE_WARMUP_DAYS
                   ) -> tuple[dict[str, BookResult], dict[str, Any]]:
    replay_start = start - pd.Timedelta(days=warmup_days)
    params = cascade_params(round_cfg, replay_start)
    replay = cascade_replay(universe, params)
    window = warmup_window(tradable_event_times(replay.inputs, params), replay_start, start)
    if window is None:
        raise WarmupNotFlat(f"no 24h window without a tradable event in [{replay_start} + 4h, {start}]")
    eff_end, freshness = effective_end(universe, data_end)
    cover = covered_through(universe["funding"])
    holes = {k: funding_hole_intervals(f) for k, f in universe["funding"].items()}
    scored = scored_cascade_trades(replay, start, eff_end, cover, holes)
    pending = cascade_pending(replay, start, eff_end)
    frames = lc.mark_with_perp_fallback(replay.inputs.mark, replay.inputs.perp_hl)
    first_stamp = start.normalize() + pd.Timedelta(days=1)
    last_stamp = eff_end - pd.Timedelta(days=1)
    clean_mask = ~scored["funding_pending"]
    books: dict[str, BookResult] = {}
    for level in CASCADE_LEVELS:
        daily, n_liq, liquidated = cascade_book(scored, frames, level, first_stamp, last_stamp)
        nopend, _, _ = cascade_book(scored.loc[clean_mask], frames, level, first_stamp, last_stamp)
        books[f"cascade_{level}x"] = BookResult(
            daily, nopend, int(len(scored)), n_liq, int(scored["funding_pending"].sum()),
            {"liquidated_positions": liquidated, "open_or_pending_entries": len(pending),
             "mean_trade_net_bps_1x": (float((scored["trade_gross"] - lc.COST_BPS_ROUND_TRIP / 1e4).mean() * 1e4)
                                       if len(scored) else None)},
            int(scored["funding_gap_zero_filled"].sum()))
    info = {"replay_start": replay_start.isoformat(), "warmup_days": int(warmup_days), "warmup_flat_window": window,
            "params": {k: v for k, v in replay.params.items()},
            "symbols_in_universe": len(universe["perp"]), "unlisted": list(universe.get("unlisted", [])),
            "freshness": freshness,
            "grid_end": replay.grid_end.isoformat(), "replay_trades": int(len(replay.trades)),
            "build_diagnostics": replay.trades.attrs.get("diagnostics", {}),
            "pending_entries": pending, "trades_scored": int(len(scored)),
            "trades": [{"symbol": r.symbol, "entry_time": r.entry_time.isoformat(), "exit_time": r.exit_time.isoformat(),
                        "side": int(r.side), "weight": float(r.weight), "unit_return": float(r.unit_return),
                        "funding_pending": bool(r.funding_pending),
                        "funding_gap_zero_filled": bool(r.funding_gap_zero_filled)} for r in scored.itertuples()],
            "funding_covered_through": {k: v.isoformat() for k, v in sorted(cover.items())}}
    return books, info


def cascade_sleeve_auto(load: Callable[[pd.Timestamp], Mapping[str, Any]], round_cfg: Mapping[str, Any],
                        start: pd.Timestamp, data_end: pd.Timestamp
                        ) -> tuple[dict[str, BookResult], dict[str, Any]]:
    """``cascade_sleeve`` with the replay start moved back in 7-day steps (up to 60 days) until a flat 24h window
    exists; ``load(replay_start)`` returns the universe.  Fails loudly when none exists within 60 days."""
    last: Exception | None = None
    for days in WARMUP_STEPS_DAYS:
        try:
            return cascade_sleeve(load(start - pd.Timedelta(days=days)), round_cfg, start, data_end, warmup_days=days)
        except WarmupNotFlat as exc:
            _log(f"warm-up {days} d is not flat: {exc}")
            last = exc
    raise NearMissError(f"no flat warm-up window within {WARMUP_STEPS_DAYS[-1]} days of the start: {last}")


# ------------------------------------------------------------------------------------------------ CTREND sleeve


def load_symbol_daily_from(symbol: str, *, start: str, end: str, fetch: bsa.Fetcher = bsa.http_fetch,
                           directory: Path | None = None) -> pd.DataFrame:
    """``binance_spot_archive.load_symbol_daily`` for months from ``start`` on (same files, same parser)."""
    base = directory if directory is not None else bsa.cache_dir()
    end_ts = pd.Timestamp(end, tz="UTC")
    end_month = end_ts.strftime("%Y-%m")
    start_month = pd.Timestamp(start, tz="UTC").strftime("%Y-%m")
    _, keys = bsa.list_all(f"{bsa.MONTHLY_PREFIX}{symbol}/1d/", fetch=fetch)
    months = {k: bsa._month_of(k, "monthly") for k in keys if k.endswith(".zip")}
    all_monthly = sorted(m for m in months.values() if m is not None)
    monthly = sorted(k for k, m in months.items() if m is not None and start_month <= m <= end_month)
    frames: list[pd.DataFrame] = []
    for key in monthly:
        data = bsa.download_verified(bsa.data_url(key), base / "monthly" / bsa.safe_name(symbol) /
                                     bsa.safe_name(Path(key).name), fetch=fetch)
        frames.append(bsa.parse_kline_zip(data))
    last_month = all_monthly[-1] if all_monthly else None
    if last_month is not None and last_month <= end_month and 1 <= bsa._month_gap(last_month, end_month) <= 2:
        _, dkeys = bsa.list_all(f"{bsa.DAILY_PREFIX}{symbol}/1d/", fetch=fetch)
        for key in sorted(k for k in dkeys if k.endswith(".zip")):
            month = bsa._month_of(key, "daily")
            if month is not None and last_month < month <= end_month and month >= start_month:
                data = bsa.download_verified(bsa.data_url(key), base / "daily" / bsa.safe_name(symbol) /
                                             bsa.safe_name(Path(key).name), fetch=fetch)
                frames.append(bsa.parse_kline_zip(data))
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_volume", "trades"],
                            index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out.loc[out.index <= end_ts]


def load_spot_panel(*, start: str, end: str, fetch: bsa.Fetcher = bsa.http_fetch, directory: Path | None = None,
                    workers: int = 24, symbols: Sequence[str] | None = None) -> dict[str, Any]:
    """Dates x symbols panels (close, high, low, quote_volume) of the Binance spot USDT universe from ``start``
    (same exclusions and relisting split as ``binance_spot_archive.load_universe``)."""
    listed = list(symbols) if symbols is not None else bsa.list_usdt_symbols(fetch=fetch, directory=directory)
    kept, excluded = bsa.filter_symbols(listed)
    results: dict[str, pd.DataFrame] = {}

    def work(sym: str) -> tuple[str, pd.DataFrame]:
        return sym, load_symbol_daily_from(sym, start=start, end=end, fetch=fetch, directory=directory)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, frame in pool.map(work, kept):
            for n, part in enumerate(bsa.split_on_gaps(frame), start=1):
                results[sym if n == 1 else f"{sym}#{n}"] = part
    names = sorted(results)
    if not names:
        raise NearMissError("no spot symbol data loaded")
    union = pd.DatetimeIndex(sorted(set().union(*[set(results[s].index) for s in names])))
    panel = {fld: pd.DataFrame({s: results[s][fld] for s in names}).reindex(union)
             for fld in ("open", "high", "low", "close", "quote_volume")}
    return {"close": panel["close"], "high": panel["high"], "low": panel["low"],
            "dollar_volume": panel["quote_volume"],
            "provenance": {"symbols_listed": len(listed), "symbols_excluded": len(excluded), "symbols_used": len(names),
                           "start": start, "end": end}}


def trim_incomplete_tail(panel: Mapping[str, Any], max_missing_share: float = LAGGING_SHARE) -> dict[str, Any]:
    """Drop trailing days on which markedly fewer symbols have a bar than in the preceding two weeks (a half-published
    day would otherwise read as a flat price for the missing coins).  Returns the panel and the dropped dates."""
    close = panel["close"]
    counts = close.notna().sum(axis=1)
    dropped: list[str] = []
    n = len(close)
    while n > 15:
        ref = float(counts.iloc[n - 15:n - 1].median())
        if counts.iloc[n - 1] < (1.0 - max_missing_share) * ref:
            dropped.append(str(close.index[n - 1].date()))
            n -= 1
        else:
            break
    out = {k: (v.iloc[:n] if isinstance(v, pd.DataFrame) else v) for k, v in panel.items()}
    out["dropped_incomplete_days"] = dropped
    return out


@dataclass
class CtrendReplay:
    weights: pd.DataFrame
    detail: pd.DataFrame
    first_book: pd.Timestamp | None


def first_rebalance_after(start: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp | None:
    """First Sunday (rebalance date) strictly after the start's UTC day."""
    candidates = index[(index.dayofweek == 6) & (index > start.normalize())]
    return candidates[0] if len(candidates) else None


def ctrend_replay(panel: Mapping[str, Any], start: pd.Timestamp) -> CtrendReplay:
    data = {k: panel[k] for k in ("close", "high", "low", "dollar_volume")}
    weights = ctrend.ctrend_weights(data, r2.DEFAULT_PARAMS[r2.CTREND_ID])
    detail = r2.buy_and_hold_detail(weights, panel["close"], CTREND_COST_BPS_ROUND_TRIP)
    return CtrendReplay(weights, detail, first_rebalance_after(start, pd.DatetimeIndex(weights.index)))


def ctrend_sleeve(panel: Mapping[str, Any], start: pd.Timestamp) -> tuple[dict[str, BookResult], dict[str, Any]]:
    replay = ctrend_replay(panel, start)
    detail = replay.detail
    first = replay.first_book
    book_formed = False
    if first is not None and len(detail):
        net = detail["net"].loc[detail.index > first]
        gross = detail["gross"].loc[detail.index > first]
        formed = bool(first in replay.weights.index and replay.weights.loc[first].notna().any())
        book_formed = formed and len(net) > 0
    else:
        net = pd.Series(dtype=float)
        gross = pd.Series(dtype=float)
    net = net.astype(float)
    last_date = pd.DatetimeIndex(panel["close"].index)[-1]
    next_sunday = last_date + pd.Timedelta(days=(6 - last_date.dayofweek) % 7 or 7)
    info: dict[str, Any] = {
        "history_start": str(panel["close"].index[0].date()), "last_bar_date": str(last_date.date()),
        "first_scored_rebalance": None if first is None else first.isoformat(),
        "book_formed": book_formed,
        "next_rebalance_date": next_sunday.isoformat(),
        "next_rebalance_pending": "the Sunday close is not yet published",
        "dropped_incomplete_days": list(panel.get("dropped_incomplete_days", [])),
        "symbols": int(panel["close"].shape[1]),
        "note": "turnover of the first scored week is charged against the previous week's book, as in the backtest",
    }
    if first is not None and first in replay.weights.index and replay.weights.loc[first].notna().any():
        w = replay.weights.loc[first].fillna(0.0)
        info["first_scored_book"] = {
            "long": {k: float(v) for k, v in w[w > 0].sort_values(ascending=False).head(12).items()},
            "short": {k: float(v) for k, v in w[w < 0].sort_values().head(12).items()},
            "n_long": int((w > 0).sum()), "n_short": int((w < 0).sum())}
    # a "book" counts only once it has at least one scored day: the Sunday that precedes each scored return day
    sundays = {d - pd.Timedelta(days=(d.dayofweek + 1) % 7) for d in net.index}
    spells = len(sundays)
    info["rebalances_after_start"] = spells
    book = BookResult(net, net, spells, 0, 0, {"gross_cumulative": float((1.0 + gross).prod() - 1.0) if len(gross) else 0.0})
    return {"ctrend_1x": book}, info


# ------------------------------------------------------------------------------------------- trend core sleeve


def load_trend_data(core: Mapping[str, Any], *, history_start: str, end: str, fetch: bsa.Fetcher = bsa.http_fetch,
                    futures_dir: Path | None = None, workers: int = 17) -> dict[str, Any]:
    """Perp 1h (OHLC), mark 1h and funding of the core's Binance symbols from ``history_start``."""
    base = futures_dir if futures_dir is not None else fa.cache_dir()
    names = [str(s) for s in core["groups"]["crypto"]]
    symbols = {n: tcl.binance_symbol(n) for n in names}

    def work(item: tuple[str, str]) -> tuple[str, dict[str, pd.DataFrame]]:
        sym = item[1]
        return sym, {ds: fa.load_dataset(ds, sym, end=end, start=history_start, fetch=fetch, directory=base)
                     for ds in ("perp", "mark", "funding")}

    frames, funding, marks, hourly = {}, {}, {}, {}
    missing: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, parts in pool.map(work, list(symbols.items())):
            if len(parts["perp"]) == 0:
                missing.append(sym)
                continue
            tcl.validate_high_low(parts["perp"], f"{sym} perp")
            bars, _ = tcl.build_8h_bars(parts["perp"])
            frames[sym] = bars
            hourly[sym] = parts["perp"]
            funding[sym] = parts["funding"]["rate"].astype(float)
            marks[sym], _, _ = tcl.mark_with_fallback(parts["mark"], parts["perp"])
    return {"frames": frames, "funding_raw": funding, "marks": marks, "missing": missing, "symbols": symbols,
            "history_start": history_start}


def fill_missing_settlements(index: pd.DatetimeIndex, raw: pd.Series, cover: pd.Timestamp
                             ) -> tuple[pd.Series, list[pd.Timestamp], list[pd.Timestamp]]:
    """Zero-rate settlements for every bar open that the engine would find short of settlements.

    Returns (filled series, pending bar opens at or after ``cover`` (month not published), gap bar opens inside
    published months).  Rows are placed at the settlement cadence (median of the last gaps) ending at the bar open, so
    the engine's interval estimate (and hence the expected count) is unchanged.  Bars before the first settlement are
    left alone.
    """
    if len(raw) < 2:
        return raw, [], []
    times = pd.DatetimeIndex(pd.to_datetime(raw.index, utc=True))
    cadence = pd.Series(np.diff(times.sort_values().as_unit("ns").asi8)[-7:]).median()
    cadence = pd.Timedelta(int(cadence), unit="ns")
    short, _ = tcl.funding_shortfalls(index, raw, [(0, len(index) - 1)])
    add: dict[pd.Timestamp, float] = {}
    pending: list[pd.Timestamp] = []
    gaps: list[pd.Timestamp] = []
    first = times.min()
    known = set(times)
    for t, count, expected in short:
        if index[t] <= first:
            continue
        need, k = max(1, expected - count), 0
        while need > 0:  # slots at the settlement cadence ending at the bar open, skipping real settlements
            when = index[t] - k * cadence
            if when not in known and when not in add:
                add[when] = 0.0
                need -= 1
            k += 1
        (pending if index[t] >= cover else gaps).append(index[t])
    if not add:
        return raw, [], []
    filled = pd.concat([raw, pd.Series(add, dtype=float)]).sort_index()
    filled.index = pd.DatetimeIndex(pd.to_datetime(filled.index, utc=True))
    return filled, pending, gaps


def neutralized_intervals(intervals: Mapping[str, pd.Series], episodes: Sequence[Mapping[str, Any]],
                          keep: set[int]) -> dict[str, pd.Series]:
    """Per-sleeve 8h interval returns with every episode NOT in ``keep`` removed (the sleeve is flat there).

    The canonical accounting books an episode's own growth in its intervals ``pi .. pj-1`` and its exit cost and last
    funding in the exit interval ``pj`` together with whatever the next episode does there (``tcl.episode_exit_factors``).
    Each removed episode divides out exactly its own part (the first interval also carries the previous episode's exit
    part when they share it), so the kept episodes keep the interval factors the full canonical run gave them.
    """
    by_sleeve: dict[str, list[int]] = {}
    for i, e in enumerate(episodes):
        by_sleeve.setdefault(e["sleeve"], []).append(i)
    out: dict[str, pd.Series] = {}
    for name, r in intervals.items():
        stamps = pd.DatetimeIndex(r.index)
        n = len(stamps)
        f = 1.0 + r.to_numpy(dtype=float)
        order = sorted(by_sleeve.get(name, []), key=lambda i: pd.Timestamp(episodes[i]["entry_time"]))
        if not order or all(i in keep for i in order):
            out[name] = r.copy()
            continue
        positions = [tcl.episode_positions(stamps, episodes[i]) for i in order]
        xs = tcl.episode_exit_factors(f, positions, [episodes[i]["net_return"] for i in order])
        removed = np.ones(n)
        prev_pj, prev_x = -1, None
        for i, (pi, pj), x in zip(order, positions, xs):
            if i not in keep and pi < n:
                shared = pi == prev_pj and prev_x is not None
                end = min(pj, n)
                for k in range(pi, end):
                    removed[k] *= f[k] / prev_x if (k == pi and shared) else f[k]
                if pj < n and x is not None:
                    removed[pj] *= x
            prev_pj, prev_x = pj, x
        out[name] = pd.Series(f / removed - 1.0, index=r.index)
    return out


def episode_funding_flags(episodes: Sequence[Mapping[str, Any]], filled_bars: Mapping[str, Sequence[pd.Timestamp]],
                          last_open: pd.Timestamp) -> list[bool]:
    """An episode is flagged when a listed bar open ``t`` satisfies ``entry < t <= exit`` (its exit being the last bar
    of the data for an episode that is still open).  Pass the pending bars for ``funding_pending`` and the in-month hole
    bars for ``funding_gap_zero_filled``."""
    flags = []
    for e in episodes:
        bars = filled_bars.get(e["symbol"], [])
        exit_ = min(pd.Timestamp(e["exit_time"]), last_open)
        flags.append(any(pd.Timestamp(e["entry_time"]) < t <= exit_ for t in bars))
    return flags


def trend_core_sleeve(core: Mapping[str, Any], data: Mapping[str, Any], start: pd.Timestamp, data_end: pd.Timestamp
                      ) -> tuple[dict[str, BookResult], dict[str, Any]]:
    symbols = [s for n, s in data["symbols"].items() if s in data["frames"]]
    run_core = {**core, "source": {**core["source"], "symbols": symbols}}
    # score only to the common last complete bar: a day is never scored on a partial symbol set
    last_bar_by_symbol = {s: data["frames"][s].index[-1] for s in symbols}
    common_last = min(last_bar_by_symbol.values())
    frames = {s: data["frames"][s].loc[data["frames"][s].index <= common_last] for s in symbols}
    funding: dict[str, pd.Series] = {}
    filled_bars: dict[str, list[pd.Timestamp]] = {}
    pending_bars: dict[str, list[pd.Timestamp]] = {}
    gap_bars: dict[str, list[pd.Timestamp]] = {}
    for s in symbols:
        raw = data["funding_raw"][s]
        cover = month_after_last(pd.DatetimeIndex(raw.index))
        funding[s], pending_bars[s], gap_bars[s] = fill_missing_settlements(frames[s].index, raw, cover)
        filled_bars[s] = sorted(pending_bars[s] + gap_bars[s])
    run = tcl.run_sleeves_detailed(run_core, frames, funding)  # no REST: shortfalls were filled with zero rates above
    episodes = run.episodes
    paths = [tcl.episode_adverse_path(e, data["marks"].get(e["symbol"])) for e in episodes]
    last_open = max(f.index[-1] for f in frames.values())
    flags = episode_funding_flags(episodes, pending_bars, last_open)       # unpublished months only
    gap_flags = episode_funding_flags(episodes, gap_bars, last_open)       # holes inside published months
    scored_idx = [i for i, e in enumerate(episodes) if pd.Timestamp(e["entry_time"]) > start]
    keep_all = set(scored_idx)
    keep_clean = {i for i in scored_idx if not flags[i]}
    first_stamp = start.normalize() + pd.Timedelta(days=1)
    books: dict[str, BookResult] = {}
    liq_detail: dict[int, list[dict[str, Any]]] = {}
    for level in TREND_LEVELS:
        daily_by_variant = {}
        for label, keep in (("all", keep_all), ("clean", keep_clean)):
            order = sorted(keep)
            neutral = neutralized_intervals(run.intervals, episodes, keep)
            sim = tcl.simulate_level(neutral, [episodes[i] for i in order], [paths[i] for i in order], level)
            daily = sim["daily"].dropna()
            daily = daily.loc[daily.index >= first_stamp]
            if len(daily):
                full = pd.date_range(first_stamp, daily.index[-1], freq="D", tz="UTC")
                daily = daily.reindex(full).fillna(0.0)
            daily_by_variant[label] = daily
            if label == "all":
                liq_detail[level] = [{"sleeve": x["sleeve"], "time": pd.Timestamp(x["time"]).isoformat(),
                                      "entry_time": pd.Timestamp(x["entry_time"]).isoformat()}
                                     for x in sim["liquidations"]]
        books[f"trend_core_{level}x"] = BookResult(
            daily_by_variant["all"], daily_by_variant["clean"], len(scored_idx), len(liq_detail[level]),
            int(sum(flags[i] for i in scored_idx)), {"liquidations": liq_detail[level]},
            int(sum(gap_flags[i] for i in scored_idx)))
    open_eps = [{"sleeve": episodes[i]["sleeve"], "entry_time": pd.Timestamp(episodes[i]["entry_time"]).isoformat(),
                 "side": episodes[i]["side"], "terminal": episodes[i]["terminal"]}
                for i in scored_idx if pd.Timestamp(episodes[i]["exit_time"]) >= last_open]
    ignored_open = [i for i, e in enumerate(episodes)
                    if pd.Timestamp(e["entry_time"]) <= start <= pd.Timestamp(e["exit_time"])]
    info = {"history_start": data["history_start"], "symbols": symbols, "symbols_missing": list(data["missing"]),
            "sleeves": int(run.daily.shape[1]), "episodes_total": len(episodes),
            "episodes_scored": len(scored_idx), "episodes_open_at_start_ignored": len(ignored_open),
            "episodes_still_open": open_eps, "last_bar_open": last_open.isoformat(),
            "common_last_bar": common_last.isoformat(),
            "last_bar_by_symbol": {k: v.isoformat() for k, v in last_bar_by_symbol.items()},
            "symbols_behind_common_end": sorted(k for k, v in last_bar_by_symbol.items() if v > common_last),
            "funding_pending_bars": {s: [t.isoformat() for t in v] for s, v in pending_bars.items() if v},
            "funding_gap_bars_filled_zero": {s: [t.isoformat() for t in v] for s, v in gap_bars.items() if v},
            "episodes": [{"sleeve": episodes[i]["sleeve"], "entry_time": pd.Timestamp(episodes[i]["entry_time"]).isoformat(),
                          "exit_time": pd.Timestamp(episodes[i]["exit_time"]).isoformat(), "side": episodes[i]["side"],
                          "net_return": float(episodes[i]["net_return"]), "funding_pending": bool(flags[i]),
                          "funding_gap_zero_filled": bool(gap_flags[i])}
                         for i in scored_idx]}
    return books, info


# ------------------------------------------------------------------------------------------------------ bands


def forward_cumulative(returns: pd.Series) -> float:
    return float((1.0 + returns.dropna()).prod() - 1.0)


def bootstrap_band(values: np.ndarray, n_days: int, *, paths: int = BAND_PATHS, mean_block: float = BAND_MEAN_BLOCK,
                   seed: int = BAND_SEED) -> np.ndarray:
    """Cumulative returns after ``n_days`` of ``paths`` stationary-bootstrap paths of ``values`` (``leverage_sim``).
    The random stream does not depend on ``n_days``: a longer horizon extends every path."""
    idx = lev.stationary_bootstrap_indices(len(values), paths, n_days, mean_block, seed)
    return np.prod(np.clip(1.0 + values[idx], 0.0, None), axis=1) - 1.0


def percentile_of(sample: np.ndarray, value: float) -> float:
    """Mid-rank percentile (0-100) of ``value`` in ``sample``."""
    below, equal = float((sample < value).sum()), float((sample == value).sum())
    return 100.0 * (below + 0.5 * equal) / len(sample)


def band_report(forward: pd.Series, reference: Mapping[str, Any] | None) -> dict[str, Any]:
    n = int(len(forward.dropna()))
    if reference is None:
        return {"available": False, "reason": "no reference series for this book"}
    ref = np.asarray(reference["values"], dtype=float)
    out: dict[str, Any] = {"available": True, "window": list(reference["window"]), "reference_days": int(len(ref)),
                           "paths": BAND_PATHS, "mean_block_days": BAND_MEAN_BLOCK, "seed": BAND_SEED,
                           "forward_days": n}
    if n == 0:
        out["note"] = "no scored day yet"
        return out
    fwd = forward_cumulative(forward)
    out["forward_cumulative_return"] = fwd
    for label, vals in (("as_backtested", ref), ("zero_edge_demeaned", ref - ref.mean())):
        band = bootstrap_band(vals, n)
        out[label] = {"forward_percentile": percentile_of(band, fwd),
                      "band_quantiles": {f"p{q:02d}": float(np.percentile(band, q)) for q in BAND_QUANTILES},
                      "reference_mean_daily_bps": float(vals.mean() * 1e4)}
    out["below_p05_as_backtested"] = bool(out["as_backtested"]["forward_percentile"] < 5.0)
    return out


# ---------------------------------------------------------------------------------------------------- assembly


def _series_dict(series: pd.Series) -> dict[str, float]:
    return {ts.isoformat(): float(v) for ts, v in series.dropna().items()}


def _forward_entry(daily: pd.Series, daily_no_pending: pd.Series, book: BookResult) -> dict[str, Any]:
    out = summarize(daily, nw_lags=NW_LAGS)
    out["trades"] = int(book.trades)
    out["liquidations"] = int(book.liquidations)
    out["funding_pending_trades"] = int(book.funding_pending)
    out["funding_gap_zero_filled_trades"] = int(book.funding_gap_zero_filled)
    out["cumulative_return_excluding_funding_pending"] = forward_cumulative(daily_no_pending)
    out["pending_trades_contribution"] = out["cumulative_return"] - out["cumulative_return_excluding_funding_pending"]
    return out


def _after(series: pd.Series, start: pd.Timestamp) -> pd.Series:
    """The part of a daily series with stamps strictly after ``start`` (an empty series stays empty)."""
    if len(series) == 0:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    return series.loc[series.index > start]


def build_report(config: Mapping[str, Any], books: Mapping[str, BookResult], sleeve_info: Mapping[str, Any],
                 reference: Mapping[str, Any] | None, *, as_of: Any, data_end: pd.Timestamp,
                 extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise NearMissError("wrong watch config")
    as_of_ts = _utc(as_of)
    start = _utc(config["prospective_start_utc"])
    series = {name: _after(books[name].daily, start) for name in BOOKS}
    if any(len(books[n].daily) != len(series[n]) for n in BOOKS):
        raise NearMissError("a scored daily stamp is not strictly after the prospective start")
    days = max((len(s) for s in series.values()), default=0)
    review_days = int(config["reporting"]["review_after_days"])
    ref_series = (reference or {}).get("series", {})
    clean = {name: _after(books[name].daily_no_pending, start) for name in BOOKS}
    forward = {name: _forward_entry(series[name], clean[name], books[name]) for name in BOOKS}
    report: dict[str, Any] = {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "data_end_utc": data_end.isoformat(),
        "review_window_open": bool((as_of_ts - start).days >= review_days),
        "forward": forward,
        "daily_returns": {name: _series_dict(series[name]) for name in BOOKS},
        "bands": {name: band_report(series[name], ref_series.get(name)) for name in BOOKS},
        "sleeves": dict(sleeve_info),
        "stamp_convention": {"cascade_*": "UTC day of the trade exit; stamp = that day 00:00, zero-filled from the first "
                                          "day after the start",
                             "ctrend_1x": "UTC day of the return (close of the previous day to close of the day)",
                             "trend_core_*": "repo convention: stamp d covers day d-1"},
        "claims": dict(config["claims"]),
    }
    if extra:
        report.update(dict(extra))
    return report


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


def _load_reference(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run(config: Mapping[str, Any], *, as_of: Any, reference: Mapping[str, Any] | None, fetch: bsa.Fetcher,
        universe: Mapping[str, Any], round_cfg: Mapping[str, Any], core: Mapping[str, Any],
        cache_root: Path | None = None, workers: int = 24) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of_ts = _utc(as_of)
    t0 = time.time()
    day = latest_published_day(as_of_ts, fetch)
    end = day.strftime("%Y-%m-%d")
    data_end = day + pd.Timedelta(days=1)
    _log(f"latest published archive day {end}")
    futures_dir = None if cache_root is None else cache_root / fa.CACHE_DIRNAME
    metrics_dir = None if cache_root is None else cache_root / bfm.CACHE_DIRNAME
    spot_dir = None if cache_root is None else cache_root / bsa.CACHE_DIRNAME
    books: dict[str, BookResult] = {}
    info: dict[str, Any] = {}

    def load(replay_start: pd.Timestamp) -> dict[str, Any]:
        return load_cascade_data(list(universe["symbols"]), replay_start=replay_start, end=end, fetch=fetch,
                                 futures_dir=futures_dir, metrics_dir=metrics_dir, workers=workers)

    b, i = cascade_sleeve_auto(load, round_cfg, start, data_end)
    replay_start = pd.Timestamp(i["replay_start"])
    _log(f"cascade data loaded ({i['symbols_in_universe']} contracts, warm-up {i['warmup_days']} d)")
    books.update(b)
    info["cascade"] = i
    _log(f"cascade replayed after {time.time() - t0:.0f}s")

    panel = load_spot_panel(start=CTREND_HISTORY_START, end=end, fetch=fetch, directory=spot_dir, workers=workers)
    _log(f"spot panel loaded ({panel['close'].shape}) after {time.time() - t0:.0f}s")
    panel = trim_incomplete_tail(panel)
    b, i = ctrend_sleeve(panel, start)
    books.update(b)
    info["ctrend"] = i
    _log(f"ctrend replayed after {time.time() - t0:.0f}s")

    tdata = load_trend_data(core, history_start=TREND_HISTORY_START, end=end, fetch=fetch, futures_dir=futures_dir)
    b, i = trend_core_sleeve(core, tdata, start, data_end)
    books.update(b)
    info["trend_core"] = i
    _log(f"trend core replayed after {time.time() - t0:.0f}s")
    return build_report(config, books, info, reference, as_of=as_of_ts, data_end=data_end,
                        extra={"data": {"latest_published_day": end, "probe": "BTCUSDT daily spot 1d, perp 1h, mark 1h, "
                                        "metrics",
                                        "ctrend_history_start": CTREND_HISTORY_START,
                                        "trend_history_start": TREND_HISTORY_START,
                                        "cascade_replay_start": replay_start.isoformat(),
                                        "elapsed_seconds": round(time.time() - t0, 1)}})


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the near-miss paper forward watch (descriptive only).")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--reference", default=DEFAULT_REFERENCE)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--round2-config", default=DEFAULT_ROUND2_CONFIG)
    parser.add_argument("--core-config", default=DEFAULT_CORE_CONFIG)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None, help="UTC timestamp (default: now): the latest archive day probed is the UTC day of this instant, so that whole "
                         "day is used if it is already published; only for tests and re-runs, it does not hide later data "
                         "from a published day")
    parser.add_argument("--cache-root", default=None,
                        help="directory holding the three archive caches (default: each module's own cache)")
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    reference = _load_reference(Path(args.reference))
    fetch = CountingFetch(bsa.http_fetch)
    report = run(config, as_of=as_of, reference=reference, fetch=fetch,
                 universe=json.loads(Path(args.universe).read_text(encoding="utf-8")),
                 round_cfg=json.loads(Path(args.round2_config).read_text(encoding="utf-8")),
                 core=json.loads(Path(args.core_config).read_text(encoding="utf-8")),
                 cache_root=None if args.cache_root is None else Path(args.cache_root), workers=args.workers)
    report["data"]["http_requests"] = fetch.requests
    report["data"]["http_megabytes"] = round(fetch.bytes / 1e6, 2)
    report["provenance"] = {
        "config_sha256": sha256(Path(args.config).read_bytes()).hexdigest(),
        "reference_sha256": sha256(Path(args.reference).read_bytes()).hexdigest() if Path(args.reference).exists() else None,
        "universe_sha256": sha256(Path(args.universe).read_bytes()).hexdigest()}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "data_end_utc": report["data_end_utc"],
                      "days": {k: v["days"] for k, v in report["forward"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

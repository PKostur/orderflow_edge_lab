"""Leverage assessment of the crypto trend core on Binance USDT-M perpetuals (``trend-core-leverage-assessment-v1``).

Descriptive study of an existing strategy (rules ``config/crypto_trend_core_v1.json``); simulation only: no orders, no
keys, no promotion.  Leverage scales an edge, it cannot create one.

Pipeline
--------
1. Cached Binance archive files (``%TEMP%/binance_futures_archive``, written by ``binance_futures_archive``; read
   directly here so open/high/low are available) -> 8h bars labelled by their OPEN time (00/08/16 UTC, so the bar ends
   at 08/16/00).  Only complete bars (8 hourly bars) are kept.
2. Each sleeve (DON8 / EMA8 x symbol) is run exactly as ``trend_portfolio_forward.sleeve_daily_returns`` does it
   (``legacy_strategy`` + ``vol_sized_strategy`` + ``run_canonical_backtest_v3`` at 20 bps round trip with funding), but
   the trade ledger is kept too.  The unlevered account return is the mean over sleeves (NaN sleeves skipped, as in
   ``strategy_search.crypto_trend_core_reference``).
3. Leverage ``L`` (the sleeve is a fixed fraction of the account; the sleeve's 8h interval returns scale by ``L``,
   floored at -100%; entry-time costs and funding scale with the notional).  The booking runs on the canonical 8h
   ``equity_path`` intervals, per sleeve; episodes of one sleeve occupy disjoint intervals [entry, exit).  An episode is
   liquidated at the first 1h mark bar, counted from the entry fill (the open of the entry bar), whose adverse
   excursion reaches ``1/L - 0.005`` (``leverage_sim`` functions), in the 8h interval ``tau`` containing that bar.
   That episode's own intervals from its entry up to and including ``tau`` then compound to one loss of
   ``|w| * (1 + 0.005 L)`` of the sleeve capital at entry (its own earlier booked growth is reversed at ``tau``); its
   remaining intervals up to the scheduled exit are 0 (the sleeve is flat); and its exit cost and last funding settlement, which the canonical
   accounting books in the exit interval (shared with the next episode's entry when the position flips or
   re-enters at once), are removed.  No other episode's interval content is touched.  Intervals are then compounded to
   the 00:00 daily stamps (stamp d covers day d-1) and averaged over sleeves.
4. Bootstrap ruin, max safe leverage: ``leverage_sim.stationary_bootstrap_indices`` / ``bootstrap_ruin_probability``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as archive
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy

BAR = pd.Timedelta(hours=8)
SAMPLES = {"whole": ("2020-01-01", "2026-09-30"), "from_2023": ("2023-01-01", "2026-09-30")}
RESULT_RELPATH = "research/trend_core_leverage/assessment_v1.json"
FUNDING_UNCOVERED_LISTED = 5  # uncovered held opens listed in the error message


class TrendCoreLeverageError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------- symbols


def binance_symbol(mexc_symbol: str) -> str:
    """``BTC_USDT`` -> ``BTCUSDT`` (no scaled-contract names occur among the core's symbols)."""
    return mexc_symbol.replace("_", "")


def cache_root() -> Path:
    return Path(os.environ.get("TEMP", tempfile.gettempdir())) / archive.CACHE_DIRNAME


def cached_files(dataset: str, symbol: str, directory: Path | None = None) -> list[Path]:
    base = (directory if directory is not None else cache_root()) / dataset
    out: list[Path] = []
    for kind in ("monthly", "daily"):
        folder = base / kind / archive.safe_name(symbol)
        if folder.is_dir():
            out.extend(sorted(folder.glob("*.zip")))
    return out


def split_symbols(mexc_symbols: Sequence[str], directory: Path | None = None) -> tuple[dict[str, str], list[str]]:
    """(available {mexc: binance}, mexc names missing from the cache): available = perp klines exist in the cache.

    A symbol missing from the cache may be unlisted on Binance or simply not prefetched; the cache cannot tell.
    """
    available: dict[str, str] = {}
    missing: list[str] = []
    for name in mexc_symbols:
        sym = binance_symbol(name)
        (available.__setitem__(name, sym) if cached_files("perp", sym, directory) else missing.append(name))
    return available, missing


# ------------------------------------------------------------------------------------------------- loading


def _load_cached(dataset: str, symbol: str, directory: Path | None, end: str) -> pd.DataFrame:
    parser = archive.parse_funding_zip if dataset == "funding" else archive.parse_hourly_zip
    frames = [parser(path.read_bytes()) for path in cached_files(dataset, symbol, directory)]
    frames = [f for f in frames if len(f)]
    if not frames:
        return archive.empty_frame(dataset)
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out.loc[out.index <= pd.Timestamp(end, tz="UTC") + pd.Timedelta("1D")]


def validate_high_low(frame: pd.DataFrame, label: str) -> None:
    """High/low must be finite, positive and ordered: a NaN would silently block later liquidations (the running
    adverse excursion is a ``maximum.accumulate``)."""
    if len(frame) == 0:
        return
    high, low = frame["high"].to_numpy(dtype=float), frame["low"].to_numpy(dtype=float)
    bad = ~(np.isfinite(high) & np.isfinite(low) & (high > 0.0) & (low > 0.0) & (high >= low))
    if bad.any():
        first = [str(t) for t in frame.index[bad][:3]]
        raise TrendCoreLeverageError(f"{label}: {int(bad.sum())} hourly bars with non-finite, non-positive or "
                                     f"inverted high/low, first at {first}")


def load_hourly(symbol: str, dataset: str = "perp", *, directory: Path | None = None,
                end: str = archive.END_DATE) -> pd.DataFrame:
    """Cached 1h klines with open/high/low/close, indexed by bar END time (high/low validated)."""
    if dataset not in ("perp", "mark"):
        raise TrendCoreLeverageError("dataset must be perp or mark")
    frame = _load_cached(dataset, symbol, directory, end)
    validate_high_low(frame, f"{symbol} {dataset}")
    return frame


def load_funding(symbol: str, *, directory: Path | None = None, end: str = archive.END_DATE) -> pd.Series:
    frame = _load_cached("funding", symbol, directory, end)
    return frame["rate"].astype(float)


def input_digest(symbols: Mapping[str, str], directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """sha256 over the sorted (file name, file sha256) pairs of every cached input, per symbol and dataset."""
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols.values():
        out[sym] = {}
        for dataset in ("perp", "mark", "funding"):
            files = cached_files(dataset, sym, directory)
            h = sha256()
            for path in files:
                h.update(path.name.encode())
                h.update(sha256(path.read_bytes()).digest())
            out[sym][dataset] = {"files": len(files), "sha256": h.hexdigest()}
    return out


# ------------------------------------------------------------------------------------------------- 8h bars


def build_8h_bars(hourly: pd.DataFrame, *, bars_needed: int = 8) -> tuple[pd.DataFrame, int]:
    """8h OHLC bars labelled by OPEN time (00/08/16 UTC) from 1h bars indexed by END time.

    A bar needs ``bars_needed`` hourly bars; incomplete ones are dropped (their count is returned).
    """
    if len(hourly) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close"],
                            index=pd.DatetimeIndex([], tz="UTC")), 0
    h = hourly.sort_index()
    open_time = h.index - pd.Timedelta(hours=1)
    key = open_time.floor("8h")
    grouped = h.groupby(key)
    out = pd.DataFrame({
        "open": grouped["open"].first(), "high": grouped["high"].max(), "low": grouped["low"].min(),
        "close": grouped["close"].last(), "n": grouped["close"].count(),
    })
    complete = out["n"] >= bars_needed
    dropped = int((~complete).sum())
    out = out.loc[complete].drop(columns="n")
    out.index.name = "open_time"
    return out, dropped


# ------------------------------------------------------------------------------------------------- sleeves


def _daily(series: pd.Series) -> pd.Series:
    return series.loc[(series.index.hour == 0) & (series.index.minute == 0)]


def funding_gaps(index: pd.DatetimeIndex, raw: pd.Series | None,
                 held: Sequence[tuple[int, int]]) -> tuple[list[str], int]:
    """Held bar opens that did not receive their funding settlements, and the number of held opens checked.

    ``held``: (entry bar, exit bar) positions on ``index``; the position is held into the opens ``entry+1 .. exit``
    (including the terminal bar), and each needs its settlements in (previous open, this open] (the slots of
    ``canonical_v3.align_funding``).  The expected number per bar follows the funding interval of the series itself:
    per settlement the gap to the previous one, median-smoothed over 7 neighbours so that one missing settlement in a
    4h series is not mistaken for an 8h interval; expected = round(bar length / interval), at least 1.  Holes while the
    sleeve is flat are not checked.
    """
    opens = sorted({t for entry, exit_ in held for t in range(entry + 1, exit_ + 1)})
    if not opens:
        return [], 0
    times = pd.DatetimeIndex([], tz="UTC")
    if raw is not None and len(raw):
        times = pd.DatetimeIndex(pd.to_datetime(raw.index, utc=True)).sort_values().unique()
    counts = np.zeros(len(index), dtype=int)
    expected = np.ones(len(index), dtype=int)
    if len(times):
        slot = index.searchsorted(times[(times > index[0]) & (times <= index[-1])], side="left")
        counts = np.bincount(slot, minlength=len(index))
        if len(times) >= 2:
            gaps = pd.Series(np.diff(times.as_unit("ns").asi8).astype(float))
            gaps = pd.concat([gaps.iloc[:1], gaps], ignore_index=True)  # the first settlement takes the next gap
            interval = gaps.rolling(7, center=True, min_periods=1).median().to_numpy()
            nearest = np.clip(times.searchsorted(index, side="left"), 0, len(times) - 1)
            length = np.diff(index.as_unit("ns").asi8, prepend=index.as_unit("ns").asi8[0]).astype(float)
            expected = np.maximum(1, np.rint(length / interval[nearest])).astype(int)
    missing = [f"{index[t].isoformat()} ({int(counts[t])} of {int(expected[t])} settlements)"
               for t in opens if counts[t] < expected[t]]
    return missing, len(opens)


class SleeveRun(NamedTuple):
    daily: pd.DataFrame  # per-sleeve daily returns, exactly ``sleeve_daily_returns``
    episodes: list[dict[str, Any]]
    intervals: dict[str, pd.Series]  # per sleeve: 8h interval returns, stamped at the interval's closing open
    funding_coverage: dict[str, dict[str, Any] | None]  # per sleeve: engine coverage and the held-bar check


def interval_returns(equity: pd.Series) -> pd.Series:
    """8h interval returns of a canonical ``equity_path`` without its terminal point (the daily convention).

    Interval k (open of bar k to open of bar k+1) is stamped at the open of bar k+1; capital starts at 1.0.
    """
    path = equity.iloc[:-1]
    previous = path.shift(1)
    previous.iloc[0] = 1.0
    return path / previous - 1.0


def run_sleeves_detailed(core: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                         funding: Mapping[str, pd.Series] | None) -> SleeveRun:
    """Per-sleeve daily returns (exactly ``sleeve_daily_returns``), episodes (trade ledger) and 8h interval returns.

    Episode: {sleeve, symbol, entry_time (open of the entry bar), exit_time, side, weight (signed entry position),
    entry_price (open of the entry bar), net_return, terminal}.  With ``funding`` given, every bar open at which a
    position is held (entry+1 .. exit of each episode) must have all its expected funding settlements
    (``funding_gaps``), otherwise this raises: a gap would be booked as zero funding.  Holes while flat are allowed.
    """
    from orderflow_edge_lab.vol_sizing import vol_sized_strategy

    execution = ExecutionModel(round_trip_cost_bps=float(core["economics"]["round_trip_cost_bps"]),
                               max_abs_position=float(core["economics"]["max_abs_position"]))
    sizing = core["sizing"]
    if sizing.get("method") != "entry_inverse_vol":
        raise TrendCoreLeverageError(f"unknown sizing method: {sizing.get('method')}")
    columns: dict[str, pd.Series] = {}
    intervals: dict[str, pd.Series] = {}
    coverage: dict[str, dict[str, Any] | None] = {}
    episodes: list[dict[str, Any]] = []
    for spec in core["strategies"]:
        strategy = vol_sized_strategy(legacy_strategy(str(spec["family"])), window=int(sizing["window_bars"]),
                                      target_vol=float(sizing["target_annual_vol"]), cap=float(sizing["cap"]),
                                      bars_per_year=int(sizing.get("bars_per_year", 3 * 365)))
        for symbol in core["source"]["symbols"]:
            frame = frames[symbol]
            result = run_canonical_backtest_v3(
                frame, strategy, dict(spec["parameters"]), execution, return_equity=True,
                funding=None if funding is None else funding.get(symbol, pd.Series(dtype=float)))
            equity = result.get("equity_path")
            if equity is None or len(equity) < 2:
                raise TrendCoreLeverageError(f"{spec['audit_id']}/{symbol}: no equity path")
            name = f"{spec['audit_id']}:{symbol}"
            if funding is not None:
                held = [(frame.index.get_loc(pd.Timestamp(t["entry"])), frame.index.get_loc(pd.Timestamp(t["exit"])))
                        for t in result.get("trades_ledger", [])]
                uncovered, n_held = funding_gaps(frame.index, funding.get(symbol), held)
                if uncovered:
                    raise TrendCoreLeverageError(
                        f"{name}: {len(uncovered)} of {n_held} held bar opens lack funding settlements (would be "
                        f"booked as zero funding); first {FUNDING_UNCOVERED_LISTED}: "
                        + "; ".join(uncovered[:FUNDING_UNCOVERED_LISTED]))
                cov = result["accounting"].get("funding_coverage")
                coverage[name] = {"engine_coverage": None if cov is None else float(cov), "held_bar_opens": n_held,
                                  "held_bar_opens_uncovered": 0}
            else:
                coverage[name] = None
            columns[name] = _daily(equity.iloc[:-1]).pct_change()
            intervals[name] = interval_returns(equity)
            opens = frame["open"].astype(float)
            for trade in result.get("trades_ledger", []):
                entry = pd.Timestamp(trade["entry"])
                episodes.append({
                    "sleeve": name, "symbol": symbol, "entry_time": entry, "exit_time": pd.Timestamp(trade["exit"]),
                    "side": int(trade["side"]), "weight": float(trade["entry_position"]),
                    "entry_price": float(opens.loc[entry]), "net_return": float(trade["net_bps"]) / 1e4,
                    "terminal": bool(trade["terminal_liquidation"]),
                })
    return SleeveRun(pd.DataFrame(columns).iloc[1:], episodes, intervals, coverage)


def run_sleeves(core: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                funding: Mapping[str, pd.Series] | None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """(per-sleeve daily returns, episodes) of ``run_sleeves_detailed``."""
    run = run_sleeves_detailed(core, frames, funding)
    return run.daily, run.episodes


def position_book(episodes: Sequence[Mapping[str, Any]], n_sleeves: int) -> pd.DataFrame:
    """Episodes as a ``leverage_sim`` position frame (weight = sleeve weight / number of sleeves).

    ``unit_return`` is the net episode return per unit of signed sleeve weight.  Informational: the study itself
    simulates on daily sleeve returns (see ``simulate_level``), because holds last days.
    """
    rows = [{"symbol": e["symbol"], "mark_key": e["symbol"], "sleeve": e["sleeve"], "entry_time": e["entry_time"],
             "exit_time": e["exit_time"], "weight": e["weight"] / n_sleeves, "entry_price": e["entry_price"],
             "unit_return": e["net_return"] / e["weight"] if e["weight"] else 0.0} for e in episodes]
    return pd.DataFrame(rows, columns=["symbol", "mark_key", "sleeve", "entry_time", "exit_time", "weight",
                                       "entry_price", "unit_return"])


# ------------------------------------------------------------------------------------------------- marks


def mark_with_fallback(mark: pd.DataFrame,
                       perp_hourly: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp | None, dict[str, int]]:
    """Mark high/low where the mark archive has a bar; the PERP 1h high/low stand in everywhere else.

    That is before the first mark bar AND for holes after it.  The frame has ``high``, ``low`` and ``is_mark``.
    Returns (frame, first mark bar end or None when the mark archive is empty, counts of fallback bars:
    ``before_first_mark``, ``holes_after_first_mark``).
    """
    perp = perp_hourly[["high", "low"]]
    validate_high_low(perp, "perp fallback")
    if len(mark) == 0:
        return perp.assign(is_mark=False), None, {"before_first_mark": int(len(perp)), "holes_after_first_mark": 0}
    validate_high_low(mark, "mark")
    first = mark.index[0]
    missing = perp.loc[~perp.index.isin(mark.index)]
    out = pd.concat([mark[["high", "low"]].assign(is_mark=True), missing.assign(is_mark=False)]).sort_index()
    return out, first, {"before_first_mark": int((missing.index < first).sum()),
                        "holes_after_first_mark": int((missing.index > first).sum())}


def mark_perp_divergence(mark: pd.DataFrame, perp_hourly: pd.DataFrame) -> dict[str, Any]:
    """Largest relative |mark - perp| high and low at matching hourly bars (exposes bad mark wicks).  Descriptive."""
    common = mark.index.intersection(perp_hourly.index)
    if len(common) == 0:
        return {"bars_compared": 0, "max_rel_diff_high": None, "at_high": None, "max_rel_diff_low": None,
                "at_low": None}
    m, q = mark.loc[common], perp_hourly.loc[common]
    high = ((m["high"] - q["high"]).abs() / q["high"]).astype(float)
    low = ((m["low"] - q["low"]).abs() / q["low"]).astype(float)
    return {"bars_compared": int(len(common)), "max_rel_diff_high": float(high.max()),
            "at_high": high.idxmax().isoformat(), "max_rel_diff_low": float(low.max()),
            "at_low": low.idxmax().isoformat()}


def top_adverse_excursions(episodes: Sequence[Mapping[str, Any]], paths: Sequence[tuple[np.ndarray, np.ndarray]],
                           coverage: Sequence[Mapping[str, int]], *, top: int = 10) -> dict[str, list[dict[str, Any]]]:
    """Per symbol the ``top`` largest adverse excursions of an episode from its entry fill (descriptive)."""
    rows: dict[str, list[dict[str, Any]]] = {}
    for e, (_, adverse), cov in zip(episodes, paths, coverage):
        if len(adverse) == 0:
            continue
        rows.setdefault(e["symbol"], []).append({
            "sleeve": e["sleeve"], "entry_time": pd.Timestamp(e["entry_time"]).isoformat(),
            "exit_time": pd.Timestamp(e["exit_time"]).isoformat(), "side": e["side"],
            "max_adverse_excursion": float(adverse[-1]), "perp_fallback_bars": int(cov["fallback"])})
    return {sym: sorted(v, key=lambda r: -r["max_adverse_excursion"])[:top] for sym, v in sorted(rows.items())}


def episode_mark_coverage(episode: Mapping[str, Any], mark: pd.DataFrame | None) -> dict[str, int]:
    """Hourly bars ending in (entry, exit]: expected, present, and present but taken from the perp fallback."""
    expected = int(round((pd.Timestamp(episode["exit_time"]) - pd.Timestamp(episode["entry_time"]))
                         / pd.Timedelta(hours=1)))
    if mark is None or len(mark) == 0:
        return {"expected": expected, "present": 0, "fallback": 0}
    ts = pd.DatetimeIndex(mark.index).as_unit("ns").asi8
    a = np.searchsorted(ts, pd.Timestamp(episode["entry_time"]).as_unit("ns").value, side="right")
    b = np.searchsorted(ts, pd.Timestamp(episode["exit_time"]).as_unit("ns").value, side="right")
    fallback = int((~mark["is_mark"].to_numpy(dtype=bool)[a:b]).sum()) if "is_mark" in mark else 0
    return {"expected": expected, "present": int(max(0, b - a)), "fallback": fallback}


def episode_adverse_path(episode: Mapping[str, Any], mark: pd.DataFrame | None) -> tuple[np.ndarray, np.ndarray]:
    """(bar end times in ns, running adverse excursion) of mark bars in (entry_time, exit_time]."""
    if mark is None or len(mark) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0)
    ts = pd.DatetimeIndex(mark.index).as_unit("ns").asi8
    a = np.searchsorted(ts, pd.Timestamp(episode["entry_time"]).as_unit("ns").value, side="right")
    b = np.searchsorted(ts, pd.Timestamp(episode["exit_time"]).as_unit("ns").value, side="right")
    if b <= a:
        return np.empty(0, dtype=np.int64), np.empty(0)
    low, high = mark["low"].to_numpy(dtype=float)[a:b], mark["high"].to_numpy(dtype=float)[a:b]
    price = float(episode["entry_price"])
    if episode["side"] > 0:
        adv = np.maximum.accumulate(np.maximum(0.0, (price - low) / price))
    else:
        adv = np.maximum.accumulate(np.maximum(0.0, (high - price) / price))
    return ts[a:b], adv


def liquidation_time(ts_ns: np.ndarray, adverse: np.ndarray, leverage: float,
                     maintenance: float = lev.MAINTENANCE_MARGIN_RATE) -> pd.Timestamp | None:
    """End time of the first mark bar whose running adverse excursion reaches ``1/L - maintenance``."""
    if len(adverse) == 0:
        return None
    hit = np.flatnonzero(np.asarray(lev.is_liquidated(adverse, leverage, maintenance), dtype=bool))
    return pd.Timestamp(int(ts_ns[hit[0]]), tz="UTC") if len(hit) else None


# ------------------------------------------------------------------------------------------------- simulation


def episode_positions(stamps: pd.DatetimeIndex, episode: Mapping[str, Any]) -> tuple[int, int]:
    """(first own interval, first interval after the own ones) of an episode on a sleeve's interval stamps.

    Interval k is stamped at the open of bar k+1, so the entry bar's interval is the first stamp after the entry time
    and the exit-bar interval (which carries the exit cost and the last funding settlement) is the first stamp after the
    exit time.  Values equal to ``len(stamps)`` mean the interval is not in the series (the series ends first).
    """
    return (int(stamps.searchsorted(pd.Timestamp(episode["entry_time"]), side="right")),
            int(stamps.searchsorted(pd.Timestamp(episode["exit_time"]), side="right")))


def episode_exit_factors(factors: np.ndarray, positions: Sequence[tuple[int, int]],
                         net_returns: Sequence[float]) -> list[float | None]:
    """Exit factor X of every episode of ONE sleeve: the part of the exit interval due to the closing episode.

    The canonical accounting books an episode's last funding settlement and its exit cost in the interval of the exit
    bar, together with whatever the next episode does in that bar (flip or immediate re-entry).  The interval factor is
    ``f[pj] = X_prev-episode * B_first[next episode]``.  The ledger fixes X: the episode's compounded net return is
    ``B_first * prod(f[pi+1:pj]) * X``, with ``B_first = f[pi] / X_prev`` when the previous episode exits at ``pi``.
    ``None`` when the exit interval is not in the series (episode ending at the end of the data).  Episodes must be
    disjoint and sorted by entry.
    """
    n = len(factors)
    out: list[float | None] = []
    prev_pj, prev_x = -1, None
    for (pi, pj), net in zip(positions, net_returns):
        if pi < prev_pj:
            raise TrendCoreLeverageError("episodes of one sleeve overlap")
        if pi >= n or pj >= n:
            out.append(None)
            prev_pj, prev_x = pj, None
            continue
        if pj <= pi:
            raise TrendCoreLeverageError("episode without own intervals")
        shared = pi == prev_pj
        if shared and prev_x is None:
            raise TrendCoreLeverageError("exit factor of the previous episode is unknown")
        first = factors[pi] / (prev_x if shared else 1.0)
        x = (1.0 + net) / (first * float(np.prod(factors[pi + 1:pj])))
        if not (np.isfinite(x) and x > 0.0):
            raise TrendCoreLeverageError(f"episode exit factor {x} is not a positive number; ledger and equity differ")
        out.append(float(x))
        prev_pj, prev_x = pj, float(x)
    return out


def compound_to_daily(stamps: pd.DatetimeIndex, factors: np.ndarray) -> pd.Series:
    """Compound interval factors (1 + return) to the 00:00 stamps; the first stamp is NaN (as ``pct_change``).

    Stamp d holds the product of the intervals stamped in (previous 00:00 stamp, d].  Intervals before the first or
    after the last 00:00 stamp are dropped (the repo convention of ``sleeve_daily_returns``).
    """
    days = stamps[(stamps.hour == 0) & (stamps.minute == 0)]
    if len(days) == 0:
        return pd.Series(dtype=float)
    group = days.searchsorted(stamps, side="left")
    ok = (group >= 1) & (group < len(days))
    products = pd.Series(np.asarray(factors, dtype=float)[ok]).groupby(group[ok]).prod()
    values = np.full(len(days), np.nan)
    values[products.index.to_numpy()] = products.to_numpy() - 1.0
    return pd.Series(values, index=days)


def simulate_level(intervals: Mapping[str, pd.Series], episodes: Sequence[Mapping[str, Any]],
                   paths: Sequence[tuple[np.ndarray, np.ndarray]], leverage: float, *,
                   config: lev.LeverageConfig = lev.LeverageConfig()) -> dict[str, Any]:
    """Daily account return at one leverage level, with episode-level liquidation, booked on the 8h intervals.

    ``intervals``: per sleeve the canonical 8h interval returns (``interval_returns``).  Levered interval return =
    ``L`` x unlevered, floored at -100%.  A liquidated episode (first mark bar whose adverse excursion reaches
    ``1/L - maintenance``, in interval ``kt``): the growth G its own intervals booked before ``kt`` is reversed in
    interval ``kt`` so that its own intervals from entry through ``kt`` compound to the single loss factor
    ``max(0, 1 - |w|(1 + fee L))`` of the sleeve capital at entry (interval ``kt`` carries ``factor / G``); its remaining
    own intervals are 0; its exit cost and last funding (``episode_exit_factors``) are removed from the exit interval.
    Only that episode's own part of each interval is changed (another episode's exit cost or entry in a shared interval
    is kept), so several liquidations of one sleeve, also within a day, all stay booked.  Intervals that mix a closing
    and an opening episode are, for a liquidated episode, rebuilt as the product of the two levered parts (differs from
    ``L`` x the combined return only at second order).
    """
    by_sleeve: dict[str, list[int]] = {}
    for i, episode in enumerate(episodes):
        by_sleeve.setdefault(episode["sleeve"], []).append(i)
    columns: dict[str, pd.Series] = {}
    liquidations: list[dict[str, Any]] = []
    for name, r in intervals.items():
        stamps = pd.DatetimeIndex(r.index)
        n = len(stamps)
        f = 1.0 + r.to_numpy(dtype=float)
        order = sorted(by_sleeve.get(name, []), key=lambda i: pd.Timestamp(episodes[i]["entry_time"]))
        positions = [episode_positions(stamps, episodes[i]) for i in order]
        hits: list[tuple[int, int, int, pd.Timestamp, int]] = []  # (pi, pj, kt, tau, episode index)
        for i, (pi, pj) in zip(order, positions):
            tau = liquidation_time(*paths[i], leverage, config.maintenance_margin_rate)
            if tau is None:
                continue
            kt = int(stamps.searchsorted(tau, side="left"))
            if kt >= n:
                continue  # after the last interval of the series: outside every daily path
            if not pi <= kt < pj:
                raise TrendCoreLeverageError(f"{name}: liquidation at {tau} is outside the episode's own intervals")
            hits.append((pi, pj, kt, tau, i))
        levered = np.maximum(-1.0, leverage * (f - 1.0))
        if hits:
            exit_x = np.ones(n)
            for (pi, pj), x in zip(positions, episode_exit_factors(
                    f, positions, [episodes[i]["net_return"] for i in order])):
                if x is not None and pj < n:
                    exit_x[pj] = x
            own = f / exit_x  # the interval's factor without the closing episode's exit part
            exit_removed = np.zeros(n, dtype=bool)
            for pi, pj, kt, tau, i in hits:
                if pj < n:
                    exit_removed[pj] = True
                liquidations.append({"sleeve": name, "time": tau, "entry_time": episodes[i]["entry_time"]})

            def lev_factor(x: float) -> float:
                return 1.0 + max(-1.0, leverage * (x - 1.0))

            def exit_part(k: int) -> float:
                return 1.0 if exit_removed[k] else lev_factor(exit_x[k])

            for pi, pj, kt, tau, i in hits:  # entry order: a later episode never rewrites an earlier one's intervals
                loss = abs(episodes[i]["weight"]) * (1.0 + config.liquidation_fee_rate * leverage)
                booked = 1.0  # the episode's own growth before tau, reversed at tau
                for k in range(pi, kt):
                    levered[k] = max(-1.0, lev_factor(own[k]) * exit_part(k) - 1.0)
                    booked *= lev_factor(own[k])
                remaining = max(0.0, 1.0 - loss) / booked if booked > 0.0 else 0.0
                levered[kt] = max(-1.0, remaining * exit_part(kt) - 1.0)
                levered[kt + 1:min(pj, n)] = 0.0
                if pj < n:
                    levered[pj] = max(-1.0, lev_factor(own[pj]) - 1.0)  # the next episode's part only
        columns[name] = compound_to_daily(stamps, 1.0 + levered)
    account = pd.DataFrame(columns).iloc[1:].mean(axis=1).clip(lower=-1.0)
    return {"daily": account, "liquidations": liquidations}


def trim_leading_zero(daily: pd.Series) -> pd.Series:
    nonzero = daily[daily != 0]
    return daily[daily.index >= nonzero.index[0]] if len(nonzero) else daily


def window(daily: pd.Series, start: str, end: str) -> pd.Series:
    """Stamp d covers day d-1; keep stamps whose covered day lies in [start, end]."""
    covered = daily.index - pd.Timedelta(days=1)
    return daily[(covered >= pd.Timestamp(start, tz="UTC")) & (covered <= pd.Timestamp(end, tz="UTC"))]


def level_stats(daily: pd.Series, liquidation_times: Sequence[pd.Timestamp], leverage: int, start: str, end: str, *,
                indices: np.ndarray | None, config: lev.LeverageConfig) -> dict[str, Any]:
    r = window(daily, start, end)
    if len(r) == 0:
        raise TrendCoreLeverageError("empty sample window")
    equity = (1.0 + r).cumprod()
    years = len(r) / 365.0
    boot = lev.bootstrap_ruin_probability(r, indices=indices, config=config)
    lo, hi = r.index[0] - pd.Timedelta(days=1), r.index[-1]
    n_liq = int(sum(lo <= t <= hi for t in liquidation_times))
    return {
        "leverage": leverage, "days": int(len(r)), "annual_return": float(equity.iloc[-1] ** (1.0 / years) - 1.0),
        "final_equity": float(equity.iloc[-1]), "max_drawdown": float((equity / equity.cummax() - 1.0).min()),
        "min_equity": float(equity.min()), "n_liquidations": n_liq,
        "ruin_probability_365d": boot["ruin_probability"], "median_equity_1y": boot["median_final_equity"],
        "p05_equity_1y": boot["p05_final_equity"], "historical_ruin": bool(equity.min() < config.ruin_fraction),
    }


def assess(core: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series] | None,
           marks: Mapping[str, pd.DataFrame], *, samples: Mapping[str, tuple[str, str]] = SAMPLES,
           config: lev.LeverageConfig = lev.LeverageConfig()) -> dict[str, Any]:
    run = run_sleeves_detailed(core, frames, funding)
    sleeves, episodes = run.daily, run.episodes
    paths = [episode_adverse_path(e, marks.get(e["symbol"])) for e in episodes]
    coverage = [episode_mark_coverage(e, marks.get(e["symbol"])) for e in episodes]
    account = sleeves.mean(axis=1).dropna()
    keep = trim_leading_zero(account).index
    report: dict[str, Any] = {name: {} for name in samples}
    indices: dict[str, np.ndarray] = {}
    effective: dict[str, Any] = {}
    for level in config.levels:
        sim = simulate_level(run.intervals, episodes, paths, level, config=config)
        daily = sim["daily"].loc[sim["daily"].index.isin(keep)]
        liq_times = [x["time"] for x in sim["liquidations"]]
        for name, (start, end) in samples.items():
            r = window(daily, start, end)
            if name not in indices and len(r):
                indices[name] = lev.stationary_bootstrap_indices(len(r), config.paths, config.horizon_days,
                                                                 config.mean_block_days, config.seed)
            if len(r) and name not in effective:
                effective[name] = {"requested": [start, end], "days": int(len(r)),
                                   "first_daily_stamp": r.index[0].isoformat(), "last_daily_stamp": r.index[-1].isoformat(),
                                   "first_covered_day": (r.index[0] - pd.Timedelta(days=1)).isoformat(),
                                   "last_covered_day": (r.index[-1] - pd.Timedelta(days=1)).isoformat()}
            report[name][str(level)] = level_stats(daily, liq_times, level, start, end,
                                                   indices=indices.get(name), config=config)
    safe = {name: _max_safe(report[name], config) for name in samples}
    names = list(samples)
    registered = None
    if "from_2023" in report:
        ok = [int(L) for L, row in report["from_2023"].items()
              if row["n_liquidations"] == 0 and all(report[n][L]["ruin_probability_365d"] <= config.max_ruin_probability
                                                    for n in names)]
        registered = max(ok) if ok else None
    kept = sleeves.loc[sleeves.index.isin(keep)]
    return {
        "samples": {n: list(v) for n, v in samples.items()}, "levels": report, "max_safe_leverage_by_sample": safe,
        "max_safe_leverage_registered": registered,
        "max_safe_leverage_rule": ("largest L with P(ruin 365d) <= 5% in EVERY reported sample and no liquidations "
                                   "in the 2023-2026 path (conservative reading of the registration)"),
        "n_sleeves": int(sleeves.shape[1]), "n_episodes": len(episodes),
        "effective_window": {
            "first_daily_stamp_any_sleeve": None if sleeves.empty else sleeves.index[0].isoformat(),
            "last_daily_stamp_any_sleeve": None if sleeves.empty else sleeves.index[-1].isoformat(),
            "first_daily_stamp_used": None if len(keep) == 0 else keep[0].isoformat(),
            "last_daily_stamp_used": None if len(keep) == 0 else keep[-1].isoformat(),
            "warmup_stamps_trimmed": int(len(sleeves) - len(kept)), "days_used": int(len(keep)),
            "note": "stamp d covers day d-1; leading stamps before the first non-zero account return are trimmed",
            "samples": effective,
        },
        "funding_coverage": dict(run.funding_coverage),
        "top_adverse_excursions_by_symbol": top_adverse_excursions(episodes, paths, coverage),
        "episodes_without_mark_bars": int(sum(len(p[0]) == 0 for p in paths)),
        "mark_coverage": {
            "episodes_with_missing_hours": int(sum(c["present"] < c["expected"] for c in coverage)),
            "episodes_partially_covered": int(sum(0 < c["present"] < c["expected"] for c in coverage)),
            "episodes_with_perp_fallback_bars": int(sum(c["fallback"] > 0 for c in coverage)),
            "episodes_entirely_perp_fallback": int(sum(c["present"] > 0 and c["fallback"] == c["present"]
                                                       for c in coverage)),
        },
        "unlevered_check_final_equity": float((1.0 + kept.mean(axis=1)).prod()),
    }


def _max_safe(rows: Mapping[str, Mapping[str, Any]], config: lev.LeverageConfig) -> int | None:
    ok = [int(L) for L, r in rows.items()
          if r["ruin_probability_365d"] <= config.max_ruin_probability and r["n_liquidations"] == 0]
    return max(ok) if ok else None


# ------------------------------------------------------------------------------------------------- output


def write_result(path: Path, payload: Mapping[str, Any]) -> None:
    """Write the result JSON exclusively (mode ``x``): refuses to overwrite; serializes first (no partial file)."""
    path = Path(path)
    text = json.dumps(payload, indent=2, sort_keys=True, default=_json_default, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not serializable: {type(value)}")

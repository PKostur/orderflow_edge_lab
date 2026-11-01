"""Binance USDT-M futures 5-minute open-interest metrics (data.binance.vision) and the round-2 universe builder.

Used by strategy-search-v3 round 2 (liquidation-cascade reversal).  Descriptive research code: no keys, no orders.

Dataset: ``data/futures/um/daily/metrics/{SYM}/{SYM}-metrics-YYYY-MM-DD.zip`` (+ ``.CHECKSUM``), one zip per UTC day,
cached under ``%TEMP%/binance_futures_metrics/{SYM}/`` and re-verified against the checksum on every reuse (resumable:
a re-run downloads only what is missing).

Columns of the csv, verified on real files (BTCUSDT 2021-01-01, 2022-06-15, 2024-03-10, 2026-09-30; ETHUSDT 2023-05-02)::

    create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,
    sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio

* ``create_time``: ``YYYY-MM-DD HH:MM:SS`` UTC, one record per 5 minutes (00:00 .. 23:55).
* ``sum_open_interest``: open interest in BASE-ASSET units (BTCUSDT 34 935.881 = coins; for a scaled contract such as
  1000SHIBUSDT one unit is one 1000-coin contract).  This is the registered field.  ``sum_open_interest_value`` is the
  same quantity in USDT at the mark price and is NOT used (a price move would move it mechanically).

Observed data-quality facts (handled, not hidden)
-------------------------------------------------
* Files are not always sorted (2026-09-30 is shuffled) -> sorted on load.
* Some files repeat every row (BTCUSDT 2021-01-01 has 576 rows = 288 x 2) -> exact duplicates are dropped and counted; two
  different values for one ``create_time`` raise ``MetricsError``.
* Files can be incomplete (2021-06-22 has 126 of 288 rows) and days can be missing -> reported in the provenance.
* ``create_time`` is a snapshot label whose meaning changed: the implied price ``sum_open_interest_value /
  sum_open_interest`` matches the 1-minute mark price at ``create_time`` in 2021-2023 files (record = state at
  ``create_time``) but at ``create_time + 5 min`` in files from about March 2024 on (record = state at the END of the
  5-minute interval).  The strategy therefore never reads a record stamped later than ``x - 5 min`` for a decision at
  ``x`` (see ``liquidation_cascade.OI_SNAPSHOT_LAG_MINUTES``).

Universe builder: Binance USDT-M perpetuals ranked by mean daily perp quote volume over 2020-10-01..2020-12-31 (1h
klines, bars OPENED in the window; days without a bar count as zero volume), stablecoin/fiat bases and leveraged
tokens excluded, walking down the ranking and keeping the first 30 whose metrics listing contains 2021-12-01 (amendment: the archive publishes open interest from
2021-12-01 for every perpetual except BTCUSDT, which starts 2020-09-01).  Only data dated before 2021-01-01 enters the
ranking.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from orderflow_edge_lab.binance_futures_archive import (
    ArchiveError,
    ArchiveHTTPError,
    Fetcher,
    data_url,
    download_verified,
    http_fetch,
    list_all,
    safe_name,
)

CACHE_DIRNAME = "binance_futures_metrics"
METRICS_PREFIX = "data/futures/um/daily/metrics/{s}/"
OI_COLUMN = "sum_open_interest"
TIME_COLUMN = "create_time"
EXPECTED_COLUMNS = ("create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
                    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio",
                    "sum_taker_long_short_vol_ratio")
DATA_START = "2021-12-01"  # registered first sample day = the metrics file every universe member must list
OI_LOAD_START = "2021-11-30"  # one day earlier where it exists, so the 4h look-back is available on the first day
DATA_END = "2026-09-30"
ROWS_PER_DAY = 288  # 24 h of 5-minute records
RANK_START = "2020-10-01"
RANK_END = "2020-12-31"
UNIVERSE_SIZE = 30
_DAY_RE = re.compile(r"-metrics-(\d{4}-\d{2}-\d{2})\.zip$")


class MetricsError(ArchiveError):
    pass


def cache_dir() -> Path:
    path = Path(os.environ.get("TEMP", tempfile.gettempdir())) / CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def metrics_key(symbol: str, day: str) -> str:
    return METRICS_PREFIX.format(s=symbol) + f"{symbol}-metrics-{day}.zip"


# ------------------------------------------------------------------------------------------------ parsing


def parse_metrics_csv(raw: bytes | str, *, symbol: str | None = None) -> tuple[pd.Series, int]:
    """One metrics csv -> (``sum_open_interest`` Series indexed by ``create_time`` UTC sorted ascending, dropped dups).

    Raises ``MetricsError`` for a missing column, a symbol column that disagrees with ``symbol``, an unparseable or
    non-finite number or timestamp, or two different values for one timestamp.  Exact duplicate rows are dropped.
    """
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    lines = [ln for ln in text.splitlines() if ln.strip()]
    empty = pd.Series([], index=pd.DatetimeIndex([], tz="UTC", name=TIME_COLUMN), dtype=float, name=OI_COLUMN)
    if not lines:
        return empty, 0
    header = [c.strip() for c in lines[0].split(",")]
    for needed in (TIME_COLUMN, OI_COLUMN):
        if needed not in header:
            raise MetricsError(f"metrics csv without column {needed!r}: header {header}")
    i_time, i_oi = header.index(TIME_COLUMN), header.index(OI_COLUMN)
    i_sym = header.index("symbol") if "symbol" in header else None
    times: list[str] = []
    values: list[str] = []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) != len(header):
            raise MetricsError(f"metrics row with {len(parts)} fields, expected {len(header)}: {ln[:80]!r}")
        if symbol is not None and i_sym is not None and parts[i_sym].strip() != symbol:
            raise MetricsError(f"row for {parts[i_sym]!r} in the {symbol} file")
        times.append(parts[i_time].strip())
        values.append(parts[i_oi].strip())
    if not times:
        return empty, 0
    try:
        stamps = np.array(times, dtype="datetime64[s]")
        oi = np.array(values, dtype=float)
    except ValueError as exc:
        raise MetricsError(f"unparseable metrics value or timestamp: {exc}") from exc
    if not np.isfinite(oi).all():
        raise MetricsError("non-finite sum_open_interest in the metrics file")
    order = np.argsort(stamps, kind="stable")
    stamps, oi = stamps[order], oi[order]
    same = stamps[1:] == stamps[:-1]
    dropped = 0
    if same.any():
        if (oi[1:][same] != oi[:-1][same]).any():
            raise MetricsError("two different sum_open_interest values for one create_time")
        keep = np.concatenate([[True], ~same])
        dropped = int((~keep).sum())
        stamps, oi = stamps[keep], oi[keep]
    index = pd.DatetimeIndex(stamps.astype("datetime64[ns]")).tz_localize("UTC")
    index.name = TIME_COLUMN
    return pd.Series(oi, index=index, name=OI_COLUMN), dropped


def parse_metrics_zip(data: bytes, *, symbol: str | None = None) -> tuple[pd.Series, int]:
    return parse_metrics_csv(fa._csv_member(data), symbol=symbol)


# ------------------------------------------------------------------------------------------------ listing


def list_metrics_days(symbol: str, *, fetch: Fetcher = http_fetch, day: str | None = None) -> list[str]:
    """Sorted ``YYYY-MM-DD`` strings of the daily metrics zips the archive lists for ``symbol``.

    With ``day`` only that one file is looked up (an S3 listing with the exact key as prefix: one small request instead
    of five pages); the result is ``[day]`` or ``[]``.
    """
    prefix = metrics_key(symbol, day) if day else METRICS_PREFIX.format(s=symbol)
    _, keys = list_all(prefix, delimiter=None, fetch=fetch)
    days = {m.group(1) for k in keys if k.endswith(".zip") for m in [_DAY_RE.search(k)] if m}
    return sorted(days)


# ------------------------------------------------------------------------------------------------ download


def _load_day(symbol: str, day: str, base: Path, fetch: Fetcher) -> tuple[pd.Series, int]:
    key = metrics_key(symbol, day)
    target = base / safe_name(symbol) / safe_name(Path(key).name)
    return parse_metrics_zip(download_verified(data_url(key), target, fetch=fetch), symbol=symbol)


def _assemble(pieces: list[tuple[pd.Series, int]], symbol: str) -> tuple[pd.Series, int]:
    dropped = sum(d for _, d in pieces)
    series = [s for s, _ in pieces if len(s)]
    if not series:
        return pd.Series([], index=pd.DatetimeIndex([], tz="UTC", name=TIME_COLUMN), dtype=float, name=OI_COLUMN), dropped
    out = pd.concat(series).sort_index()
    dup = out.index.duplicated(keep="first")
    if dup.any():
        first = out[~dup]
        if not np.array_equal(out[dup].to_numpy(), first.reindex(out.index[dup]).to_numpy()):
            raise MetricsError(f"{symbol}: different open interest for one create_time across files")
        dropped += int(dup.sum())
        out = first
    return out, dropped


def _coverage(series: pd.Series, days_listed: list[str], days_loaded: list[str]) -> dict[str, Any]:
    if len(series) == 0:
        return {"partial_days": {}, "n_partial_days": 0, "rows": 0, "first": None, "last": None, "days_listed": len(days_listed), "days_loaded": 0,
                "days_missing_within_span": 0, "zero_or_negative_rows": 0, "max_gap_minutes": None}
    span = pd.date_range(pd.Timestamp(days_loaded[0]), pd.Timestamp(days_loaded[-1]), freq="D")
    gaps = series.index.to_series().diff().dropna()
    per_day = series.groupby(series.index.strftime("%Y-%m-%d")).size()
    partial = {str(d): int(n) for d, n in per_day.items() if n < ROWS_PER_DAY}
    return {"partial_days": partial, "n_partial_days": len(partial), "rows": int(len(series)), "first": str(series.index[0]), "last": str(series.index[-1]),
            "days_listed": len(days_listed), "days_loaded": len(days_loaded),
            "days_missing_within_span": int(len(span) - len(set(days_loaded))),
            "zero_or_negative_rows": int((series.to_numpy() <= 0).sum()),
            "max_gap_minutes": float(gaps.max().total_seconds() / 60.0) if len(gaps) else 0.0}


def load_metrics_universe(symbols: Iterable[str], *, start: str = DATA_START, end: str = DATA_END, workers: int = 24,
                          fetch: Fetcher = http_fetch, directory: Path | None = None,
                          progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """5-minute open-interest series of ``symbols`` for the listed days in ``[start, end]`` (inclusive).

    Every zip is checksum-verified and cached.  Returns ``{"oi": {symbol: Series}, "provenance": {symbol: {...}}}``;
    a symbol with no listed day in the range maps to an empty series (the caller decides whether that is fatal).
    """
    base = directory if directory is not None else cache_dir()
    syms = list(dict.fromkeys(symbols))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        listed = dict(zip(syms, pool.map(lambda s: list_metrics_days(s, fetch=fetch), syms), strict=True))
        days = {s: [d for d in listed[s] if start <= d <= end] for s in syms}
        tasks = [(s, d) for s in syms for d in days[s]]
        done = 0
        results: dict[str, list[tuple[pd.Series, int]]] = {s: [] for s in syms}
        for (s, _d), piece in zip(tasks, pool.map(lambda t: _load_day(t[0], t[1], base, fetch), tasks), strict=True):
            results[s].append(piece)
            done += 1
            if progress is not None and (done % 500 == 0 or done == len(tasks)):
                progress(done, len(tasks))
    oi: dict[str, pd.Series] = {}
    provenance: dict[str, Any] = {}
    for s in syms:
        series, dropped = _assemble(results[s], s)
        oi[s] = series
        provenance[s] = {**_coverage(series, listed[s], days[s]), "duplicate_rows_dropped": dropped,
                         "first_listed_day": listed[s][0] if listed[s] else None,
                         "last_listed_day": listed[s][-1] if listed[s] else None}
    return {"oi": oi, "provenance": provenance, "start": start, "end": end}


def load_oi_series(symbol: str, *, start: str = DATA_START, end: str = DATA_END, workers: int = 24,
                   fetch: Fetcher = http_fetch, directory: Path | None = None) -> pd.Series:
    """The 5-minute ``sum_open_interest`` series of one symbol indexed by ``create_time`` (UTC)."""
    return load_metrics_universe([symbol], start=start, end=end, workers=workers, fetch=fetch,
                                 directory=directory)["oi"][symbol]


# ------------------------------------------------------------------------------------------------ universe


def _kline_months(start: str, end: str) -> list[str]:
    return [str(p) for p in pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")]


def pre_period_volume(symbol: str, *, start: str = RANK_START, end: str = RANK_END, fetch: Fetcher = http_fetch,
                      directory: Path | None = None) -> dict[str, Any]:
    """Total / mean-per-calendar-day perp quote volume of ``symbol`` over ``[start, end]`` from the monthly 1h klines.

    Only bars OPENED inside the window count (a bar ending at the end of ``end`` is the last one), so data dated
    after the window never enters, even if a monthly file extends beyond it.  A month without a file contributes zero.
    """
    base = directory if directory is not None else fa.cache_dir()
    first_open = pd.Timestamp(start, tz="UTC")
    last_end = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)  # bar end of the last bar of the final day
    frames = []
    for month in _kline_months(start, end):
        key = fa.DATASETS["perp"][0].format(s=symbol) + f"{symbol}-1h-{month}.zip"
        target = base / "perp" / "monthly" / safe_name(symbol) / safe_name(Path(key).name)
        try:
            frames.append(fa.parse_hourly_zip(download_verified(data_url(key), target, fetch=fetch)))
        except ArchiveHTTPError as exc:
            if exc.status not in (403, 404):
                raise
    n_days = int((pd.Timestamp(end) - pd.Timestamp(start)).days) + 1
    if not frames:
        return {"total_quote_volume": 0.0, "mean_daily_quote_volume": 0.0, "trading_days": 0,
                "mean_daily_over_trading_days": 0.0, "n_days": n_days}
    frame = pd.concat(frames)
    frame = frame[~frame.index.duplicated(keep="first")]
    frame = frame.loc[(frame.index > first_open) & (frame.index <= last_end)]  # bar end in (start, end + 1d]
    total = float(frame["quote_volume"].sum())
    day = (frame.index - pd.Timedelta(hours=1)).normalize()
    trading_days = int((frame["quote_volume"].groupby(day).sum() > 0).sum())
    return {"total_quote_volume": total, "mean_daily_quote_volume": total / n_days, "trading_days": trading_days,
            "mean_daily_over_trading_days": total / trading_days if trading_days else 0.0, "n_days": n_days}


def build_universe(symbols: Iterable[str] | None = None, *, size: int = UNIVERSE_SIZE, rank_start: str = RANK_START,
                   rank_end: str = RANK_END, metrics_day: str = DATA_START, workers: int = 16,
                   fetch: Fetcher = http_fetch, directory: Path | None = None,
                   metrics_lister: Callable[[str], list[str]] | None = None) -> dict[str, Any]:
    """The round-2 universe: top ``size`` perps by pre-2021 volume that have a metrics file for ``metrics_day``.

    ``symbols`` defaults to every USDT-M perpetual in the archive listing (stablecoin / fiat bases and leveraged
    tokens removed by the registered exclusions).  Returns ``{"symbols": [...rank order...], "ranking": [...top
    rows...], "skipped_no_metrics": [...], ...}``.  Ties in volume are broken by symbol name.
    """
    base = directory if directory is not None else fa.cache_dir()
    listed = list(symbols) if symbols is not None else fa.list_perp_symbols(fetch=fetch, directory=base)
    kept, excluded = fa.filter_symbols(s for s in listed if fa.is_perpetual_usdt(s))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        volumes = dict(zip(kept, pool.map(lambda s: pre_period_volume(s, start=rank_start, end=rank_end, fetch=fetch,
                                                                       directory=base), kept), strict=True))
    ranked = sorted((s for s in kept if volumes[s]["total_quote_volume"] > 0),
                    key=lambda s: (-volumes[s]["mean_daily_quote_volume"], s))
    full_lister = metrics_lister or (lambda s: list_metrics_days(s, fetch=fetch))
    lister = metrics_lister or (lambda s: list_metrics_days(s, fetch=fetch, day=metrics_day))
    chosen: list[str] = []
    skipped: list[dict[str, Any]] = []
    for sym in ranked:
        if len(chosen) >= size:
            break
        if metrics_day in lister(sym):
            chosen.append(sym)
        else:
            days = full_lister(sym)  # only for the report: when does its metrics history start?
            skipped.append({"symbol": sym, "rank": ranked.index(sym) + 1,
                            "first_metrics_day": days[0] if days else None, "metrics_days": len(days)})
    # descriptive only: the alternative convention (mean over days with volume) -- how different would the set be
    alt = sorted(ranked, key=lambda s: (-volumes[s]["mean_daily_over_trading_days"], s))
    alt_chosen: list[str] = []
    for sym in alt:
        if len(alt_chosen) >= size:
            break
        if sym in chosen or metrics_day in lister(sym):
            alt_chosen.append(sym)
    return {
        "rule": (f"top {size} USDT-M perps by mean daily perp quote volume over {rank_start}..{rank_end} "
                 f"(total / calendar days) that list a metrics file for {metrics_day}; ties by symbol"),
        "rank_window": [rank_start, rank_end], "metrics_day": metrics_day, "size": size,
        "symbols": chosen,
        "ranking": [{"symbol": s, "rank_among_candidates": ranked.index(s) + 1,
                     "mean_daily_quote_volume": volumes[s]["mean_daily_quote_volume"],
                     "trading_days": volumes[s]["trading_days"]} for s in chosen],
        "skipped_no_metrics": skipped,
        "candidates_ranked": len(ranked), "candidates_without_pre_period_volume": len(kept) - len(ranked),
        "symbols_excluded_by_filter": excluded,
        "descriptive_alt_convention_trading_day_mean_differs_by": len(set(chosen) ^ set(alt_chosen)),
    }


def universe_matches(registered: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> bool:
    """Same symbols in the same order and, wherever both record it, the same metrics day, size and ranking window."""
    for key in ("metrics_day", "size", "rank_window"):
        if key in registered and key in rebuilt and list(np.atleast_1d(registered[key])) != list(
                np.atleast_1d(rebuilt[key])):
            return False
    return list(registered["symbols"]) == list(rebuilt["symbols"])


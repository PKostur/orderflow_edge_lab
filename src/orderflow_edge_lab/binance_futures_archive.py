"""Binance USDT-M perpetual archive (data.binance.vision, futures/um) plus matching spot 1h klines.

Used by strategy-search-v3 round 1 (perp log-basis quintile sort).  Descriptive research code: no keys, no orders.

Datasets per perpetual symbol (all checksum-verified, cached under ``%TEMP%/binance_futures_archive/``, resumable):

* ``perp``    1h klines  ``data/futures/um/{monthly,daily}/klines/{SYM}/1h/``
* ``mark``    1h mark-price klines  ``.../markPriceKlines/{SYM}/1h/`` (liquidation checks)
* ``funding`` fundingRate history  ``.../fundingRate/{SYM}/`` (monthly zips only: the archive publishes no daily
  fundingRate files, the loader still looks for them for months after the last monthly zip)
* ``spot``    1h spot klines of the matching ``{SYM}`` USDT pair  ``data/spot/{monthly,daily}/klines/{SYM}/1h/``

Conventions
-----------
* Kline frames are indexed by the bar END time (open time + 1 hour, UTC): the value at index ``t`` is the close of
  the bar ending at ``t`` and is known at ``t``.  Open times are milliseconds up to 2024 and microseconds from 2025
  (spot); both are handled row by row.
* Funding frames are indexed by the settlement timestamp as given by the archive, rounded to the nearest minute (the
  archive stamps ``calc_time`` with millisecond jitter, e.g. ``08:00:00.001``).  Contracts that moved from 8h to 4h
  (or 1h) funding simply carry more rows; ``funding_interval_hours`` is kept as given.
* A hole of more than 30 days between two bars of one perp symbol is a relisting: the later part becomes a new
  instrument ``SYMBOL#2`` (and so on) so no return is computed across the gap.  Funding, mark and spot data are kept
  per base symbol (``base_name``).
* Exclusions: stablecoin / fiat bases and leveraged tokens (``binance_spot_archive.filter_symbols``), delivery
  contracts (``SYM_YYMMDD``) and non-USDT quotes never enter the listing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_spot_archive as spot
from orderflow_edge_lab.binance_spot_archive import (  # noqa: F401  (re-exported)
    MAX_GAP_DAYS,
    ArchiveError,
    ArchiveHTTPError,
    ChecksumError,
    Fetcher,
    data_url,
    download_verified,
    filter_symbols,
    http_fetch,
    list_all,
    safe_name,
    split_on_gaps,
)

CACHE_DIRNAME = "binance_futures_archive"
FUTURES_ROOT = "data/futures/um/"
LISTING_PREFIX = FUTURES_ROOT + "monthly/klines/"
END_DATE = "2026-09-30"
KLINE_COLUMNS = spot.KLINE_COLUMNS
DATASETS: dict[str, tuple[str, str]] = {
    "perp": (FUTURES_ROOT + "monthly/klines/{s}/1h/", FUTURES_ROOT + "daily/klines/{s}/1h/"),
    "mark": (FUTURES_ROOT + "monthly/markPriceKlines/{s}/1h/", FUTURES_ROOT + "daily/markPriceKlines/{s}/1h/"),
    "funding": (FUTURES_ROOT + "monthly/fundingRate/{s}/", FUTURES_ROOT + "daily/fundingRate/{s}/"),
    "spot": ("data/spot/monthly/klines/{s}/1h/", "data/spot/daily/klines/{s}/1h/"),
}
PERP_KEEP = ("close", "quote_volume")
MARK_KEEP = ("high", "low")


def cache_dir() -> Path:
    path = Path(os.environ.get("TEMP", tempfile.gettempdir())) / CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def base_name(name: str) -> str:
    """Archive symbol of an instrument name (``SYM#2`` -> ``SYM``)."""
    return name.split("#", 1)[0]


# ------------------------------------------------------------------------------------- spot matching

_SCALE_PREFIX = re.compile(r"^(1(?:0+|M))(?=\S)")


def match_spot(perp_symbol: str, spot_symbols: set[str] | frozenset[str]) -> tuple[str, float] | None:
    """Spot pair of a perpetual and the contract multiplier ``k`` (perp price ~ k * spot price).

    Exact name first (``k = 1``; so ``1INCHUSDT`` maps to itself).  Otherwise a scaled-contract prefix
    (``1000``, ``10000``, ``1000000``, ... or ``1M``) is stripped and ``<BASE>USDT`` must exist as a spot pair.  Returns
    ``None`` when there is no spot pair (the contract stays excluded).
    """
    if perp_symbol in spot_symbols:
        return perp_symbol, 1.0
    m = _SCALE_PREFIX.match(perp_symbol)
    if m is None:
        return None
    prefix = m.group(1)
    k = 1_000_000.0 if prefix == "1M" else float(prefix)
    spot_symbol = perp_symbol[len(prefix):]
    if spot_symbol.endswith("USDT") and len(spot_symbol) > len("USDT") and spot_symbol in spot_symbols:
        return spot_symbol, k
    return None


# ----------------------------------------------------------------------------------------------- listing


def is_perpetual_usdt(symbol: str) -> bool:
    """USDT-quoted perpetual: ends in USDT, no ``_YYMMDD`` delivery suffix."""
    return symbol.endswith("USDT") and "_" not in symbol and len(symbol) > len("USDT")


def list_perp_symbols(*, fetch: Fetcher = http_fetch, cache: bool = True, directory: Path | None = None) -> list[str]:
    """Every USDT-M perpetual with monthly klines in the archive (delisted contracts are listed too)."""
    base = directory if directory is not None else cache_dir()
    path = base / "perp_symbols.json"
    if cache and path.exists():
        return list(json.loads(path.read_text(encoding="utf-8")))
    prefixes, _ = list_all(LISTING_PREFIX, fetch=fetch)
    symbols = sorted({p[len(LISTING_PREFIX):].strip("/") for p in prefixes} - {""})
    perps = [s for s in symbols if is_perpetual_usdt(s)]
    if cache:
        base.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(perps), encoding="utf-8")
    return perps


# ------------------------------------------------------------------------------------------------ parsing


def _epoch_seconds(open_time: np.ndarray) -> np.ndarray:
    t = np.asarray(open_time, dtype=np.int64)
    return np.where(t >= 10**14, t // 1_000_000, t // 1_000)


def _read_rows(raw: bytes | str, columns: list[str]) -> pd.DataFrame:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    if not text.strip():
        return pd.DataFrame(columns=columns, dtype=str)
    frame = pd.read_csv(io.StringIO(text), header=None, dtype=str, skip_blank_lines=True)
    if frame.shape[1] < len(columns):
        raise ArchiveError(f"expected at least {len(columns)} columns, got {frame.shape[1]}")
    frame = frame.iloc[:, :len(columns)]
    frame.columns = columns
    if len(frame) and not re.fullmatch(r"\d+", str(frame.iloc[0, 0]).strip()):
        frame = frame.iloc[1:]  # header row
    return frame


_HOURLY_VALUE_COLUMNS = ["open", "high", "low", "close", "volume", "quote_volume", "trades"]


def parse_hourly_csv(raw: bytes | str) -> pd.DataFrame:
    """1h kline csv (header optional, ms or us open times) -> frame indexed by the bar END time (UTC)."""
    frame = _read_rows(raw, list(KLINE_COLUMNS))
    if frame.empty:
        return pd.DataFrame(columns=_HOURLY_VALUE_COLUMNS, index=pd.DatetimeIndex([], tz="UTC", name="bar_end"),
                            dtype=float)
    seconds = _epoch_seconds(frame["open_time"].astype("int64").to_numpy()) + 3600
    index = pd.DatetimeIndex(pd.to_datetime(seconds, unit="s", utc=True), name="bar_end")
    return pd.DataFrame({c: pd.to_numeric(frame[c]).to_numpy(dtype=float) for c in _HOURLY_VALUE_COLUMNS},
                        index=index)


def parse_funding_csv(raw: bytes | str) -> pd.DataFrame:
    """fundingRate csv (``calc_time,funding_interval_hours,last_funding_rate``) -> settlement-indexed frame.

    The index is ``calc_time`` rounded to the nearest minute.  Columns: ``rate`` (fraction, positive = longs pay
    shorts) and ``interval_hours`` (NaN for the legacy two-column files).
    """
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    if not text.strip():
        return pd.DataFrame(columns=["rate", "interval_hours"],
                            index=pd.DatetimeIndex([], tz="UTC", name="settlement"), dtype=float)
    frame = pd.read_csv(io.StringIO(text), header=None, dtype=str, skip_blank_lines=True)
    if frame.shape[1] not in (2, 3):
        raise ArchiveError(f"unexpected fundingRate layout with {frame.shape[1]} columns")
    if len(frame) and not re.fullmatch(r"\d+", str(frame.iloc[0, 0]).strip()):
        frame = frame.iloc[1:]
    if frame.empty:
        return pd.DataFrame(columns=["rate", "interval_hours"], index=pd.DatetimeIndex([], tz="UTC", name="settlement"),
                            dtype=float)
    seconds = _epoch_seconds(frame.iloc[:, 0].astype("int64").to_numpy())
    index = pd.DatetimeIndex(pd.to_datetime(seconds, unit="s", utc=True), name="settlement").round("min")
    if frame.shape[1] == 3:
        interval = pd.to_numeric(frame.iloc[:, 1]).to_numpy(dtype=float)
        rate = pd.to_numeric(frame.iloc[:, 2]).to_numpy(dtype=float)
    else:
        interval = np.full(len(frame), np.nan)
        rate = pd.to_numeric(frame.iloc[:, 1]).to_numpy(dtype=float)
    return pd.DataFrame({"rate": rate, "interval_hours": interval}, index=index)


def _csv_member(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ArchiveError("zip without a csv member")
        return archive.read(names[0])


def parse_hourly_zip(data: bytes) -> pd.DataFrame:
    return parse_hourly_csv(_csv_member(data))


def parse_funding_zip(data: bytes) -> pd.DataFrame:
    return parse_funding_csv(_csv_member(data))


# ------------------------------------------------------------------------------------------------ download

_MONTHLY_RE = re.compile(r"-(\d{4}-\d{2})\.zip$")
_DAILY_RE = re.compile(r"-(\d{4}-\d{2})-\d{2}\.zip$")


def _month_of(key: str, kind: str) -> str | None:
    m = (_MONTHLY_RE if kind == "monthly" else _DAILY_RE).search(key)
    return m.group(1) if m else None


def _month_number(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7])


def empty_frame(dataset: str) -> pd.DataFrame:
    if dataset == "funding":
        return parse_funding_csv("")
    return parse_hourly_csv("")


def load_dataset(dataset: str, symbol: str, *, end: str = END_DATE, start: str | None = None,
                 fetch: Fetcher = http_fetch, directory: Path | None = None) -> pd.DataFrame:
    """One symbol's frame for ``dataset`` ('perp', 'mark', 'funding', 'spot') from ``start`` to ``end`` (inclusive).

    Monthly zips first; months after the last monthly zip (up to two) are filled from daily zips.  Every zip is
    verified against its ``.CHECKSUM``.  Klines are clipped to bars ending at or before ``end`` + 1 day 00:00 and
    funding to settlements at or before that instant.  Returns an empty frame when the archive has nothing.
    """
    if dataset not in DATASETS:
        raise ArchiveError(f"unknown dataset {dataset}")
    base = directory if directory is not None else cache_dir()
    monthly_prefix, daily_prefix = (p.format(s=symbol) for p in DATASETS[dataset])
    parser = parse_funding_zip if dataset == "funding" else parse_hourly_zip
    end_ts = pd.Timestamp(end, tz="UTC")
    end_month = end_ts.strftime("%Y-%m")
    start_month = pd.Timestamp(start, tz="UTC").strftime("%Y-%m") if start else "0000-00"
    _, keys = list_all(monthly_prefix, fetch=fetch)
    monthly = sorted(k for k in keys if k.endswith(".zip")
                     and start_month <= (_month_of(k, "monthly") or "9999") <= end_month)
    frames: list[pd.DataFrame] = []
    for key in monthly:
        target = base / dataset / "monthly" / safe_name(symbol) / safe_name(Path(key).name)
        frames.append(parser(download_verified(data_url(key), target, fetch=fetch)))
    all_monthly = sorted(_month_of(k, "monthly") for k in keys if k.endswith(".zip") and _month_of(k, "monthly"))
    last_month = all_monthly[-1] if all_monthly else None
    need_daily = (last_month is None) or (1 <= _month_number(end_month) - _month_number(last_month) <= 2)
    if need_daily:
        _, dkeys = list_all(daily_prefix, fetch=fetch)
        for key in sorted(k for k in dkeys if k.endswith(".zip")):
            month = _month_of(key, "daily")
            if month is None or month > end_month or month < start_month:
                continue
            if last_month is not None and month <= last_month:
                continue
            target = base / dataset / "daily" / safe_name(symbol) / safe_name(Path(key).name)
            frames.append(parser(download_verified(data_url(key), target, fetch=fetch)))
    frames = [f for f in frames if len(f)]
    if not frames:
        return empty_frame(dataset)
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out.loc[out.index <= end_ts + pd.Timedelta("1D")]


def _later_month(start: str | None, first_open: pd.Timestamp) -> str:
    """The later of ``start`` and the first day of the month containing ``first_open`` (as a date string)."""
    month_start = first_open.strftime("%Y-%m-01")
    return month_start if start is None or month_start > start else start


# ---------------------------------------------------------------------------------------------- universe


def load_universe(*, end: str = END_DATE, start: str | None = None, symbols: Iterable[str] | None = None,
                  workers: int = 12, fetch: Fetcher = http_fetch, directory: Path | None = None,
                  progress: Callable[[int, int], None] | None = None, include_mark: bool = False,
                  mark_start: str | None = None) -> dict[str, Any]:
    """Perp / funding / spot (and optionally mark) frames of every USDT-M perpetual that has a matching spot pair.

    ``symbols`` (perp symbols) overrides the archive listing (smoke tests); ``start`` limits the first month loaded.
    Matching (``match_spot``): perp ``XUSDT`` needs spot ``XUSDT``; scaled contracts such as ``1000PEPEUSDT`` map to
    spot ``PEPEUSDT`` with multiplier ``k = 1000``.  Perps with no spot pair are reported under ``perps_without_spot``
    and the (perp -> spot, k) mappings of scaled contracts under ``provenance["spot_mapping"]``.  Returns::

        {"perp": {name: frame[close, quote_volume]}, "spot": {perp symbol: frame[close] of its spot pair},
         "spot_scale": {perp symbol: k}, "funding": {symbol: frame[rate, interval_hours]},
         "mark": {symbol: frame[high, low]}, "provenance": {...}}

    ``perp`` is keyed by instrument name (relisted tickers become ``SYM#2``); the other frames by perp symbol.
    """
    base = directory if directory is not None else cache_dir()
    listed = list(symbols) if symbols is not None else list_perp_symbols(fetch=fetch, directory=base)
    kept, excluded = filter_symbols(s for s in listed if is_perpetual_usdt(s))
    spot_listed = set(spot.list_usdt_symbols(fetch=fetch, directory=base))
    mapping = {s: match_spot(s, spot_listed) for s in kept}
    matched = [s for s in kept if mapping[s] is not None]
    without_spot = [s for s in kept if mapping[s] is None]
    mark_from = mark_start or start

    def work(sym: str) -> tuple[str, dict[str, pd.DataFrame]]:
        perp_frame = load_dataset("perp", sym, end=end, start=start, fetch=fetch, directory=base)
        # spot history older than the perp listing is never used: start the spot download at the perp's first month
        spot_start = _later_month(start, perp_frame.index[0] - pd.Timedelta("1h")) if len(perp_frame) else start
        parts = {
            "perp": perp_frame,
            "funding": load_dataset("funding", sym, end=end, start=start, fetch=fetch, directory=base),
            "spot": load_dataset("spot", mapping[sym][0], end=end, start=spot_start, fetch=fetch, directory=base),
        }
        if include_mark and len(parts["perp"]):
            parts["mark"] = load_dataset("mark", sym, end=end, start=mark_from, fetch=fetch, directory=base)
        return sym, parts

    perp: dict[str, pd.DataFrame] = {}
    spot_out: dict[str, pd.DataFrame] = {}
    spot_scale: dict[str, float] = {}
    funding: dict[str, pd.DataFrame] = {}
    mark: dict[str, pd.DataFrame] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, parts in pool.map(work, matched):
            done += 1
            if len(parts["perp"]) and len(parts["spot"]):
                for n, part in enumerate(split_on_gaps(parts["perp"][list(PERP_KEEP)]), start=1):
                    perp[sym if n == 1 else f"{sym}#{n}"] = part
                spot_out[sym] = parts["spot"][["close"]]
                spot_scale[sym] = mapping[sym][1]
                funding[sym] = parts["funding"]
                if "mark" in parts and len(parts["mark"]):
                    mark[sym] = parts["mark"][list(MARK_KEEP)]
            if progress is not None:
                progress(done, len(matched))
    if not perp:
        raise ArchiveError("no perpetual data loaded")
    provenance = {
        "perp_symbols_listed": len(listed),
        "symbols_excluded": excluded,
        "perps_without_spot": sorted(without_spot),
        "symbols_matched": len(matched),
        "spot_mapping": {s: {"spot": mapping[s][0], "k": mapping[s][1]} for s in matched if mapping[s][1] != 1.0},
        "instruments_used": len(perp),
        "end": end,
        "start": start,
        "include_mark": include_mark,
        "mark_start": mark_from if include_mark else None,
        "per_instrument": {n: {"first_bar_end": str(f.index[0]), "last_bar_end": str(f.index[-1]), "rows": int(len(f))}
                           for n, f in perp.items()},
        "funding": {s: {"rows": int(len(f)), "first": str(f.index[0]) if len(f) else None,
                        "last": str(f.index[-1]) if len(f) else None,
                        "interval_hours": sorted({float(x) for x in f["interval_hours"].dropna().unique()})}
                    for s, f in funding.items()},
        "spot": {s: {"rows": int(len(f)), "first": str(f.index[0]), "last": str(f.index[-1])}
                 for s, f in spot_out.items()},
    }
    return {"perp": perp, "spot": spot_out, "spot_scale": spot_scale, "funding": funding, "mark": mark, "provenance": provenance}

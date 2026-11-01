"""Binance spot daily klines from the public archive data.binance.vision (all USDT pairs, delisted included).

Used by the strategy-search-v1 round-2 CTREND candidate.  Descriptive research code: no keys, no orders.

* ``list_usdt_symbols`` pages through the S3 listing (``marker`` / ``NextMarker``) of ``data/spot/monthly/klines/``.
* ``load_symbol_daily`` downloads the monthly 1d kline zips (daily zips for months after the last published monthly one),
  verifies every zip against its ``.CHECKSUM`` sha256, and parses open/high/low/close and quote-asset volume (USDT
  dollar volume).  Open times are milliseconds up to 2024 and microseconds from 2025; both are handled row by row.
* Everything is cached under ``%TEMP%/binance_spot_archive/``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import http.client
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd

LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DATA_URL = "https://data.binance.vision/"
MONTHLY_PREFIX = "data/spot/monthly/klines/"
DAILY_PREFIX = "data/spot/daily/klines/"
CACHE_DIRNAME = "binance_spot_archive"
KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
                 "taker_buy_base", "taker_buy_quote", "ignore"]
END_DATE = "2026-09-30"

# Stablecoin and fiat base assets (registered exclusion: "stablecoins/fiat bases").
STABLE_FIAT_BASES = frozenset({
    "USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "PAX", "USDS", "UST", "USTC", "USDSB", "SUSD", "AEUR", "EURI",
    "USD1", "USDE", "RLUSD", "XUSD", "BFUSD", "PYUSD", "USDD", "GUSD", "LUSD", "FRAX", "VAI", "TUSDB", "USDT",
    "EUR", "GBP", "AUD", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "IDRT", "BIDR", "BKRW", "PLN", "RON", "ARS", "JPY",
    "CZK", "MXN", "COP", "KRW", "VND", "CAD", "CHF",
})
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


MAX_GAP_DAYS = 30  # a longer hole between two bars of one symbol is treated as a relisting (a new coin)


def data_url(key: str) -> str:
    """Download URL of an archive key; non-ASCII symbols are percent-encoded (UTF-8), '/' is kept."""
    return DATA_URL + urllib.parse.quote(key, safe="/")


def safe_name(name: str) -> str:
    """Filesystem-safe cache component: ASCII letters, digits and ``_.-`` are unchanged, the rest is %-encoded."""
    return urllib.parse.quote(name, safe="")


class ArchiveError(ValueError):
    pass


class ChecksumError(ArchiveError):
    pass


def cache_dir() -> Path:
    path = Path(os.environ.get("TEMP", tempfile.gettempdir())) / CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


Fetcher = Callable[[str], bytes]


class ArchiveHTTPError(ArchiveError):
    def __init__(self, url: str, status: int):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


_THREAD = threading.local()


def _connection(host: str, timeout: float) -> http.client.HTTPSConnection:
    pool = getattr(_THREAD, "connections", None)
    if pool is None:
        pool = _THREAD.connections = {}
    if host not in pool:
        pool[host] = http.client.HTTPSConnection(host, timeout=timeout)
    return pool[host]


def http_fetch(url: str, *, timeout: float = 90.0, retries: int = 5) -> bytes:
    """GET with one persistent HTTPS connection per thread (connection set-up costs seconds on this network)."""
    parts = urllib.parse.urlsplit(url)
    # http.client only sends ASCII request lines: encode any raw non-ASCII (already %-encoded text is left alone)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-_.~")
    target = path + (f"?{parts.query}" if parts.query else "")
    last: Exception | None = None
    for attempt in range(retries):
        conn = _connection(parts.netloc, timeout)
        try:
            conn.request("GET", target, headers={"User-Agent": "orderflow-edge-lab-research"})
            response = conn.getresponse()
            body = response.read()
            if response.status == 200:
                return body
            if response.status in (403, 404):
                raise ArchiveHTTPError(url, response.status)
            last = ArchiveHTTPError(url, response.status)
        except ArchiveHTTPError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            last = exc
        conn.close()
        _THREAD.connections.pop(parts.netloc, None)
        time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise last


# ----------------------------------------------------------------------------------------------- listing


@dataclass(frozen=True)
class ListingPage:
    prefixes: tuple[str, ...]
    keys: tuple[str, ...]
    truncated: bool
    next_marker: str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_listing_xml(text: str | bytes) -> ListingPage:
    """One S3 ListBucketResult page.  ``next_marker`` falls back to the last returned entry when S3 omits NextMarker."""
    root = ET.fromstring(text)
    prefixes: list[str] = []
    keys: list[str] = []
    truncated = False
    next_marker: str | None = None
    for child in root:
        name = _local(child.tag)
        if name == "CommonPrefixes":
            for sub in child:
                if _local(sub.tag) == "Prefix" and sub.text:
                    prefixes.append(sub.text)
        elif name == "Contents":
            for sub in child:
                if _local(sub.tag) == "Key" and sub.text:
                    keys.append(sub.text)
        elif name == "IsTruncated":
            truncated = (child.text or "").strip().lower() == "true"
        elif name == "NextMarker":
            next_marker = (child.text or "").strip() or None
    if truncated and next_marker is None:
        last = keys[-1] if keys else (prefixes[-1] if prefixes else None)
        if last is None:
            raise ArchiveError("truncated listing without any entry to continue from")
        next_marker = last
    return ListingPage(tuple(prefixes), tuple(keys), truncated, next_marker)


def list_all(prefix: str, *, delimiter: str | None = "/", fetch: Fetcher = http_fetch,
             max_pages: int = 10_000) -> tuple[list[str], list[str]]:
    """All common prefixes and keys under ``prefix`` (paginating with ``marker``)."""
    prefixes: list[str] = []
    keys: list[str] = []
    marker: str | None = None
    for _ in range(max_pages):
        params = {"prefix": prefix}
        if delimiter:
            params["delimiter"] = delimiter
        if marker:
            params["marker"] = marker
        page = parse_listing_xml(fetch(f"{LIST_URL}?{urllib.parse.urlencode(params, safe='/')}"))
        prefixes.extend(page.prefixes)
        keys.extend(page.keys)
        if not page.truncated:
            return prefixes, keys
        if page.next_marker == marker:
            raise ArchiveError("listing marker did not advance")
        marker = page.next_marker
    raise ArchiveError("listing did not terminate")


def list_usdt_symbols(*, fetch: Fetcher = http_fetch, cache: bool = True, directory: Path | None = None) -> list[str]:
    """Every symbol ending in USDT with monthly spot klines (delisted pairs are listed by the archive too)."""
    base = directory if directory is not None else cache_dir()
    path = base / "usdt_symbols.json"
    if cache and path.exists():
        return list(json.loads(path.read_text(encoding="utf-8")))
    prefixes, _ = list_all(MONTHLY_PREFIX, fetch=fetch)
    symbols = sorted({p[len(MONTHLY_PREFIX):].strip("/") for p in prefixes} - {""})
    usdt = [s for s in symbols if s.endswith("USDT")]
    if cache:
        base.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(usdt), encoding="utf-8")
    return usdt


# --------------------------------------------------------------------------------------------- exclusions


def base_asset(symbol: str) -> str:
    if not symbol.endswith("USDT"):
        raise ArchiveError(f"not a USDT pair: {symbol}")
    return symbol[: -len("USDT")]


def is_leveraged_token(base: str, all_bases: Iterable[str]) -> bool:
    """UP/DOWN/BULL/BEAR suffix tokens (e.g. BTCUP, ETHBEAR).

    A suffix match counts only if the prefix is itself a listed base asset, so ordinary coins that merely end in
    ``UP`` (JUP) are kept while BTCUP -> BTC, ETHDOWN -> ETH are removed.
    """
    listed = all_bases if isinstance(all_bases, (set, frozenset)) else set(all_bases)
    for suffix in LEVERAGED_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix) and base[: -len(suffix)] in listed:
            return True
    return False


def filter_symbols(symbols: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    """Registered exclusions.  Returns (kept symbols, {excluded symbol: reason})."""
    syms = sorted(set(symbols))
    bases = frozenset(base_asset(s) for s in syms)
    kept: list[str] = []
    excluded: dict[str, str] = {}
    for s in syms:
        b = base_asset(s)
        if not b:
            excluded[s] = "empty base"
        elif b in STABLE_FIAT_BASES:
            excluded[s] = "stablecoin or fiat base"
        elif is_leveraged_token(b, bases):
            excluded[s] = "leveraged token (UP/DOWN/BULL/BEAR)"
        else:
            kept.append(s)
    return kept, excluded


# ----------------------------------------------------------------------------------------------- download


def parse_checksum(text: str | bytes) -> str:
    raw = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else text
    token = raw.strip().split()[0].lower() if raw.strip() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ChecksumError(f"unparseable checksum file: {raw[:80]!r}")
    return token


def verify_checksum(data: bytes, checksum_text: str | bytes, *, name: str = "") -> str:
    expected = parse_checksum(checksum_text)
    actual = sha256(data).hexdigest()
    if actual != expected:
        raise ChecksumError(f"sha256 mismatch for {name}: expected {expected}, got {actual}")
    return actual


def download_verified(url: str, target: Path, *, fetch: Fetcher = http_fetch) -> bytes:
    """Zip bytes verified against ``<url>.CHECKSUM``; cached next to ``target`` and re-verified on every reuse."""
    checksum_path = target.with_name(target.name + ".CHECKSUM")
    if target.exists() and checksum_path.exists():
        data = target.read_bytes()
        try:
            verify_checksum(data, checksum_path.read_text(encoding="utf-8", errors="replace"), name=target.name)
            return data
        except ChecksumError:
            target.unlink()
            checksum_path.unlink()
    checksum_text = fetch(url + ".CHECKSUM")
    data = fetch(url)
    verify_checksum(data, checksum_text, name=url)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    checksum_path.write_text(checksum_text.decode("utf-8", errors="replace"), encoding="utf-8")
    return data


# ------------------------------------------------------------------------------------------------ parsing


def _to_utc_dates(open_time: np.ndarray) -> pd.DatetimeIndex:
    """Milliseconds (13 digits) or microseconds (16 digits, archives from 2025) -> UTC midnight timestamps."""
    t = np.asarray(open_time, dtype=np.int64)
    seconds = np.where(t >= 10**14, t // 1_000_000, t // 1_000)
    return pd.DatetimeIndex(pd.to_datetime(seconds, unit="s", utc=True)).normalize()


def parse_kline_csv(raw: bytes | str) -> pd.DataFrame:
    """Daily kline csv (with or without a header row) -> frame indexed by UTC date.

    Columns: open, high, low, close, volume, quote_volume (dollar volume for USDT pairs), trades.
    """
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    frame = pd.read_csv(io.StringIO(text), header=None, names=KLINE_COLUMNS, dtype=str)
    if len(frame) and not re.fullmatch(r"\d+", str(frame["open_time"].iloc[0]).strip()):
        frame = frame.iloc[1:]  # header row
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_volume", "trades"],
                            index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    index = _to_utc_dates(frame["open_time"].astype("int64").to_numpy())
    out = pd.DataFrame({c: pd.to_numeric(frame[c]).to_numpy(dtype=float)
                        for c in ("open", "high", "low", "close", "volume", "quote_volume", "trades")}, index=index)
    out.index.name = "date"
    return out


def parse_kline_zip(data: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ArchiveError("zip without a csv member")
        return parse_kline_csv(archive.read(names[0]))


def _month_of(key: str, kind: str) -> str | None:
    m = re.search(r"-1d-(\d{4}-\d{2})\.zip$" if kind == "monthly" else r"-1d-(\d{4}-\d{2})-\d{2}\.zip$", key)
    return m.group(1) if m else None


def _month_gap(first: str, second: str) -> int:
    a, b = int(first[:4]) * 12 + int(first[5:7]), int(second[:4]) * 12 + int(second[5:7])
    return b - a


def load_symbol_daily(symbol: str, *, end: str = END_DATE, fetch: Fetcher = http_fetch,
                      directory: Path | None = None) -> pd.DataFrame:
    """Daily bars of one spot symbol up to ``end`` (inclusive), checksum-verified.  Empty frame if no data."""
    base = directory if directory is not None else cache_dir()
    end_ts = pd.Timestamp(end, tz="UTC")
    end_month = end_ts.strftime("%Y-%m")
    _, keys = list_all(f"{MONTHLY_PREFIX}{symbol}/1d/", fetch=fetch)
    monthly = sorted(k for k in keys if k.endswith(".zip") and (_month_of(k, "monthly") or "9999") <= end_month)
    frames: list[pd.DataFrame] = []
    for key in monthly:
        data = download_verified(data_url(key), base / "monthly" / safe_name(symbol) / safe_name(Path(key).name),
                                 fetch=fetch)
        frames.append(parse_kline_zip(data))
    last_month = _month_of(monthly[-1], "monthly") if monthly else None
    if last_month is not None and 1 <= _month_gap(last_month, end_month) <= 2:
        # months after the last published monthly zip come from daily zips (older gaps mean the pair was delisted)
        _, dkeys = list_all(f"{DAILY_PREFIX}{symbol}/1d/", fetch=fetch)
        for key in sorted(k for k in dkeys if k.endswith(".zip")):
            month = _month_of(key, "daily")
            if month is not None and last_month < month <= end_month:
                data = download_verified(data_url(key), base / "daily" / safe_name(symbol) / safe_name(Path(key).name),
                                     fetch=fetch)
                frames.append(parse_kline_zip(data))
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_volume", "trades"],
                            index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out.loc[out.index <= end_ts]


def split_on_gaps(frame: pd.DataFrame, max_gap_days: int = MAX_GAP_DAYS) -> list[pd.DataFrame]:
    """Split one symbol's bars wherever two consecutive bars are more than ``max_gap_days`` calendar days apart."""
    if len(frame) < 2:
        return [frame] if len(frame) else []
    gaps = np.diff(frame.index.values.astype("datetime64[D]")).astype(int)
    cut = np.flatnonzero(gaps > max_gap_days) + 1
    return [frame.iloc[positions] for positions in np.split(np.arange(len(frame)), cut)]


def load_universe(*, end: str = END_DATE, symbols: Iterable[str] | None = None, workers: int = 12,
                  fetch: Fetcher = http_fetch, directory: Path | None = None,
                  progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Panel frames (dates x symbols) of open/high/low/close/quote_volume plus provenance.

    ``symbols`` (USDT pairs) overrides the archive listing, e.g. for smoke tests.
    """
    listed = list(symbols) if symbols is not None else list_usdt_symbols(fetch=fetch, directory=directory)
    kept, excluded = filter_symbols(listed)
    results: dict[str, pd.DataFrame] = {}

    def work(sym: str) -> tuple[str, pd.DataFrame]:
        return sym, load_symbol_daily(sym, end=end, fetch=fetch, directory=directory)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, frame in pool.map(work, kept):
            done += 1
            # a relisted ticker (gap > 30 days) is a new coin: SYMBOL, SYMBOL#2, ... so bar counts and indicators
            # restart and no return is computed across the gap
            for n, part in enumerate(split_on_gaps(frame), start=1):
                results[sym if n == 1 else f"{sym}#{n}"] = part
            if progress is not None:
                progress(done, len(kept))
    names = sorted(results)
    if not names:
        raise ArchiveError("no symbol data loaded")
    union = pd.DatetimeIndex(sorted(set().union(*[set(results[s].index) for s in names])))
    panel = {field: pd.DataFrame({s: results[s][field] for s in names}).reindex(union)
             for field in ("open", "high", "low", "close", "quote_volume")}
    provenance = {
        "symbols_listed": len(listed),
        "symbols_excluded": excluded,
        "symbols_used": len(names),
        "end": end,
        "per_symbol": {s: {"first_date": str(results[s].index[0].date()), "last_date": str(results[s].index[-1].date()),
                           "rows": int(len(results[s]))} for s in names},
    }
    return {**panel, "provenance": provenance}

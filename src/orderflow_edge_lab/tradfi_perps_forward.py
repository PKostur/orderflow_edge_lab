"""TradFi perpetuals paper forward watch (``tradfi-perps-forward-v1``, ``config/tradfi_perps_forward_v1.json``).

Descriptive only: no promotion, no orders, no keys.  Binance lists US-stock, ETF and commodity perpetuals that trade 24/7.
Three books on the stock perps, scored on daily account returns:

* ``B0_equal_weight_long`` (1x): long all eligible stocks, equal weight, gross 1.0, rebalanced monthly (benchmark).
* ``B1_xs_momentum_12_1`` (1x, 2x): Jegadeesh-Titman 12-1 quintile long/short on Yahoo adjusted closes, formed at the
  US close of the first US trading day of each month.
* ``B2_weekend_fade`` (1x, 2x, 5x): fade the weekend perp move of the first US trading day of the week, entered one
  15-minute bar after the signal bar, exited at that day's US close.

Data: data.binance.vision only (15m perp and mark-price klines, monthly fundingRate) plus Yahoo daily bars of the
underlyings and SPY.  The archive lags about a day; a day is scored only when every bar it needs is published for every
held symbol (per-symbol freshness: a lagging symbol makes the period pending, a stale price is never carried).
``fundingRate`` is published monthly: settlements of an unpublished month are applied as zero and the period carries
``funding_pending``; the history is replayed on every run so a later published file replaces the zeros.

Contamination rule (registration saw metadata only): nothing dated before ``prospective_start_utc`` is scored or
summarised.  Signals may read earlier closes (they are inputs, as in near-miss-forward-v1); every event, session and
settlement that is scored or described starts after the start, and while the archive has not reached the start the run
reports ``PRE_START`` with data coverage only.  The first B2 week (Monday 2026-10-19, the start day) forms its signal
from the Friday 2026-10-16 reference bar and the weekend window, which begin before the start but after the
registration of 2026-10-13; only the trade (entry 10:00 ET) is after the start and scored.

Costs: 7 bps per side on traded notional.  B0/B1 turnover is netted between consecutive TARGET weights (sum of
``|w_new - w_old|`` at each formation), not between drifted holdings; B2 pays the 14 bps round trip on its gross 1.0.

Yahoo failures never rewrite history: fetched daily series are cached next to the archive caches; a failed fetch
falls back to the cached series only where it covers a formation, otherwise B1 becomes pending from the first affected
formation (``yahoo_unavailable:<sym>``) and an unavailable SPY makes the calendar check pending, not passed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from orderflow_edge_lab import binance_spot_archive as bsa
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import near_miss_forward as nmf
from orderflow_edge_lab.trend_portfolio_forward import summarize

WATCH_ID = "tradfi-perps-forward-v1"
DEFAULT_CONFIG = "config/tradfi_perps_forward_v1.json"
DEFAULT_UNIVERSE = "research/tradfi_perps_forward/universe_v1.json"

NY = ZoneInfo("America/New_York")
BAR = pd.Timedelta(minutes=15)
DAY = pd.Timedelta(days=1)
ROUND_TRIP_BPS = 14.0
SIDE_COST = ROUND_TRIP_BPS / 2.0 / 1e4       # 7 bps per side on traded notional
MIN_VOLUME_USDT = 1_000_000.0
MIN_NAMES = 20
LIQUIDITY_DAYS = 7
MOMENTUM_MIN_CLOSES = 253
SKIP_DAYS, FORM_DAYS = 21, 252
NW_LAGS = nmf.NW_LAGS
LAG_WINDOW_DAYS = nmf.LAG_WINDOW_DAYS
DATA_PRELOAD_DAYS = 10                       # klines are loaded from start - 10 days (previous-week reference bar)
YAHOO_HISTORY_DAYS = 430
UNIVERSE_SHA256 = "99cd50e0befd6172683536c8ee1610f052226e62575fa347d91577dc5d8f8e14"   # sha256 of research/tradfi_perps_forward/universe_v1.json (line endings normalised)
LEV_CHECK_TOLERANCE = 1e-9
YAHOO_CACHE_DIRNAME = "yahoo_daily"
NULL_DRAWS = 999
NULL_SEED = 20261013
BOOK_B0, BOOK_B1, BOOK_B2 = "B0_equal_weight_long", "B1_xs_momentum_12_1", "B2_weekend_fade"

COMMODITY_MAP = {"XAU": "GC=F", "XAG": "SI=F", "XPT": "PL=F", "XPD": "PA=F", "CL": "CL=F", "BZ": "BZ=F",
                 "NATGAS": "NG=F", "COPPER": "HG=F"}
SYMBOL_OVERRIDES = {"BRKB": "BRK-B"}

FUTURES_ROOT = fa.FUTURES_ROOT
KLINES_15M: dict[str, tuple[str, str]] = {
    "perp15": (FUTURES_ROOT + "monthly/klines/{s}/15m/", FUTURES_ROOT + "daily/klines/{s}/15m/"),
    "mark15": (FUTURES_ROOT + "monthly/markPriceKlines/{s}/15m/", FUTURES_ROOT + "daily/markPriceKlines/{s}/15m/"),
}
KLINE_COLUMNS_15M = ["open", "high", "low", "close", "volume", "quote_volume", "trades"]


class TradfiError(RuntimeError):
    pass


class ClockError(TradfiError):
    pass


class YahooError(TradfiError):
    pass


_utc = nmf._utc


def _log(message: str) -> None:
    print(f"[tradfi {time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def yahoo_symbol(base_asset: str, underlying_type: str) -> str | None:
    """Config mapping: Yahoo symbol = baseAsset (BRKB -> BRK-B); commodities by the futures map; otherwise unmapped."""
    if underlying_type == "COMMODITY":
        return COMMODITY_MAP.get(base_asset)
    if underlying_type == "EQUITY":
        return SYMBOL_OVERRIDES.get(base_asset, base_asset)
    return None


# ---------------------------------------------------------------------------------------------------------- clock


@dataclass(frozen=True)
class Clock:
    """NYSE sessions 09:30-16:00 America/New_York (13:00 early closes), DST-aware; holidays from the config."""

    holidays: frozenset
    early_closes: frozenset
    covered_through: date

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> Clock:
        c = config["clock"]
        hol = frozenset(date.fromisoformat(x) for x in c["nyse_holidays"])
        early = frozenset(date.fromisoformat(x) for x in c["nyse_early_closes"])
        return cls(hol, early, date(max(hol | early).year, 12, 31))

    def _check(self, d: date) -> None:
        if d > self.covered_through:
            raise ClockError(f"{d} is beyond the registered holiday list (covers through {self.covered_through})")

    def is_session(self, d: date) -> bool:
        self._check(d)
        return d.weekday() < 5 and d not in self.holidays

    @staticmethod
    def _local(d: date, hour: int, minute: int) -> pd.Timestamp:
        return pd.Timestamp(datetime(d.year, d.month, d.day, hour, minute, tzinfo=NY)).tz_convert("UTC")

    def session_open(self, d: date) -> pd.Timestamp:
        if not self.is_session(d):
            raise ClockError(f"{d} is not a US session")
        return self._local(d, 9, 30)

    def session_close(self, d: date) -> pd.Timestamp:
        if not self.is_session(d):
            raise ClockError(f"{d} is not a US session")
        return self._local(d, 13, 0) if d in self.early_closes else self._local(d, 16, 0)

    def next_session_on_or_after(self, d: date) -> date:
        while not self.is_session(d):
            d += timedelta(days=1)
        return d

    def previous_session(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_session(d):
            d -= timedelta(days=1)
        return d

    def first_session_of_month(self, year: int, month: int) -> date:
        return self.next_session_on_or_after(date(year, month, 1))

    def week_first_session(self, d: date) -> date | None:
        """First session of the Monday-Sunday week containing ``d`` (the Tuesday after a Monday holiday), or None."""
        monday = d - timedelta(days=d.weekday())
        first = self.next_session_on_or_after(monday)
        return first if first <= monday + timedelta(days=6) else None

    def sessions_between(self, a: date, b: date) -> list[date]:
        out, d = [], a
        while d <= b:
            if self.is_session(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def first_formation_session(self, start: pd.Timestamp) -> date:
        """First US trading day whose close is after the start (the 'on or after the start' day)."""
        d = self.next_session_on_or_after(start.date() - timedelta(days=1))
        while self.session_close(d) <= start:
            d = self.next_session_on_or_after(d + timedelta(days=1))
        return d


def calendar_check(clock: Clock, spy_dates: Sequence[date], first: date, last: date) -> dict[str, Any]:
    """Compare the registered calendar with the realized Yahoo SPY bars on ``[first, last]``.

    Reports SPY bars on days the clock calls closed and clock sessions without a SPY bar; both sets are returned as
    ``unscored_sessions`` (the affected session is left unscored).  Early closes cannot be seen in daily bars."""
    bars = {d for d in spy_dates if first <= d <= last}
    expected = set(clock.sessions_between(first, last)) if first <= last else set()
    unexpected = sorted(bars - expected)
    missing = sorted(expected - bars)
    return {"checked_from": first.isoformat(), "checked_through": last.isoformat(),
            "spy_bars": len(bars), "sessions_expected": len(expected),
            "bars_on_closed_days": [d.isoformat() for d in unexpected],
            "sessions_without_bar": [d.isoformat() for d in missing],
            "unscored_sessions": sorted(d.isoformat() for d in set(unexpected) | set(missing)),
            "early_closes_checked": False}


# ------------------------------------------------------------------------------------------------ 15m archive helper


def parse_kline_15m_csv(raw: bytes | str) -> pd.DataFrame:
    """15m kline csv (header optional, ms or us open times) -> frame indexed by the bar END time (UTC)."""
    frame = fa._read_rows(raw, list(fa.KLINE_COLUMNS))
    if frame.empty:
        return pd.DataFrame(columns=KLINE_COLUMNS_15M, index=pd.DatetimeIndex([], tz="UTC", name="bar_end"), dtype=float)
    seconds = fa._epoch_seconds(frame["open_time"].astype("int64").to_numpy()) + int(BAR.total_seconds())
    index = pd.DatetimeIndex(pd.to_datetime(seconds, unit="s", utc=True), name="bar_end")
    return pd.DataFrame({c: pd.to_numeric(frame[c]).to_numpy(dtype=float) for c in KLINE_COLUMNS_15M}, index=index)


def parse_kline_15m_zip(data: bytes) -> pd.DataFrame:
    return parse_kline_15m_csv(fa._csv_member(data))


def load_klines_15m(dataset: str, symbol: str, *, end: str, start: str | None = None,
                    fetch: bsa.Fetcher = bsa.http_fetch, directory: Path | None = None) -> pd.DataFrame:
    """15m perp (``perp15``) or mark-price (``mark15``) klines of one symbol from ``start`` to ``end`` (inclusive).

    Same loading rule as ``binance_futures_archive.load_dataset`` (monthly zips, then daily zips for the months after
    the last monthly one, every zip checksum-verified and cached) with the 15-minute prefixes.  New helper: the
    existing loader is hourly and is left unchanged."""
    if dataset not in KLINES_15M:
        raise fa.ArchiveError(f"unknown 15m dataset {dataset}")
    base = directory if directory is not None else fa.cache_dir()
    monthly_prefix, daily_prefix = (p.format(s=symbol) for p in KLINES_15M[dataset])
    end_ts = pd.Timestamp(end, tz="UTC")
    end_month = end_ts.strftime("%Y-%m")
    start_month = pd.Timestamp(start, tz="UTC").strftime("%Y-%m") if start else "0000-00"
    _, keys = bsa.list_all(monthly_prefix, fetch=fetch)
    monthly = sorted(k for k in keys if k.endswith(".zip")
                     and start_month <= (fa._month_of(k, "monthly") or "9999") <= end_month)
    frames: list[pd.DataFrame] = []
    for key in monthly:
        target = base / dataset / "monthly" / bsa.safe_name(symbol) / bsa.safe_name(Path(key).name)
        frames.append(parse_kline_15m_zip(bsa.download_verified(bsa.data_url(key), target, fetch=fetch)))
    all_monthly = sorted(fa._month_of(k, "monthly") for k in keys if k.endswith(".zip") and fa._month_of(k, "monthly"))
    last_month = all_monthly[-1] if all_monthly else None
    need_daily = last_month is None or (1 <= fa._month_number(end_month) - fa._month_number(last_month) <= 2)
    if need_daily:
        _, dkeys = bsa.list_all(daily_prefix, fetch=fetch)
        for key in sorted(k for k in dkeys if k.endswith(".zip")):
            month = fa._month_of(key, "daily")
            if month is None or month > end_month or month < start_month:
                continue
            if last_month is not None and month <= last_month:
                continue
            target = base / dataset / "daily" / bsa.safe_name(symbol) / bsa.safe_name(Path(key).name)
            frames.append(parse_kline_15m_zip(bsa.download_verified(bsa.data_url(key), target, fetch=fetch)))
    frames = [f for f in frames if len(f)]
    if not frames:
        return parse_kline_15m_csv("")
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out.loc[out.index <= end_ts + DAY]


def probe_keys(probe_symbol: str, day: str) -> dict[str, str]:
    return {"perp15": f"{FUTURES_ROOT}daily/klines/{probe_symbol}/15m/{probe_symbol}-15m-{day}.zip",
            "mark15": f"{FUTURES_ROOT}daily/markPriceKlines/{probe_symbol}/15m/{probe_symbol}-15m-{day}.zip"}


def latest_published_day(as_of: pd.Timestamp, probe_symbol: str, fetch: bsa.Fetcher = bsa.http_fetch,
                         max_back: int = nmf.PROBE_DAYS_BACK) -> pd.Timestamp:
    """Latest UTC day ``d <= as_of`` whose 15m perp and mark files of the probe symbol are published."""
    top = _utc(as_of).normalize()
    for back in range(max_back + 1):
        day = top - pd.Timedelta(days=back)
        keys = probe_keys(probe_symbol, day.strftime("%Y-%m-%d"))
        if all(nmf._published(k, fetch) for k in keys.values()):
            return day
    raise TradfiError(f"no published 15m archive day within {max_back} days before {as_of}")


# -------------------------------------------------------------------------------------------------------- Yahoo


def parse_yahoo_chart(payload: Mapping[str, Any]) -> pd.DataFrame:
    """Yahoo chart payload -> daily frame (UTC midnight index): unadjusted open/high/low/close plus ``adjclose``."""
    chart = payload.get("chart") or {}
    results = chart.get("result")
    if not results:
        raise YahooError(f"no chart result: {chart.get('error')}")
    result = results[0]
    quote = result["indicators"]["quote"][0]
    adj_block = result["indicators"].get("adjclose")
    adj = adj_block[0]["adjclose"] if adj_block else quote["close"]
    idx = pd.to_datetime(result.get("timestamp") or [], unit="s", utc=True).normalize()
    frame = pd.DataFrame({"open": quote["open"], "high": quote["high"], "low": quote["low"], "close": quote["close"],
                          "adjclose": adj}, index=idx).apply(pd.to_numeric, errors="coerce")
    frame = frame[frame["close"].notna() & (frame["close"] > 0)]       # only the close is required; others may be NaN
    for col in ("open", "high", "low", "adjclose"):
        frame.loc[frame[col] <= 0, col] = np.nan
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def fetch_yahoo_frame(symbol: str, start: pd.Timestamp, end: pd.Timestamp, *, retries: int = 4) -> pd.DataFrame:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}"
           f"?period1={int(start.timestamp())}&period2={int(end.timestamp())}&interval=1d&events=div%2Csplit")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return parse_yahoo_chart(json.load(response))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                break
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError, YahooError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise YahooError(f"{symbol}: {last}")


YahooFetch = Callable[[str, pd.Timestamp, pd.Timestamp], pd.DataFrame]


class CountingYahoo:
    def __init__(self, inner: YahooFetch = fetch_yahoo_frame) -> None:
        self.inner = inner
        self.requests = 0
        self._lock = threading.Lock()

    def __call__(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        with self._lock:
            self.requests += 1
        return self.inner(symbol, start, end)


# ----------------------------------------------------------------------------------------------------- universe


def universe_sha256(path: Path | str) -> str:
    """sha256 of the file with CRLF normalised to LF (a Windows checkout must hash like the committed blob)."""
    return sha256(Path(path).read_bytes().replace(bytes([13, 10]), bytes([10]))).hexdigest()


def load_universe(path: Path | str, expected_sha256: str | None = None) -> dict[str, Any]:
    """The frozen universe; raises if the file differs from ``UNIVERSE_SHA256``."""
    want = UNIVERSE_SHA256 if expected_sha256 is None else expected_sha256
    got = universe_sha256(path)
    if got != want:
        raise TradfiError(f"universe file {path} changed after registration: sha256 {got} != {want}")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("watch_id") != WATCH_ID:
        raise TradfiError("wrong universe file")
    return payload


def stock_book(universe: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [e for e in universe["symbols"] if e["stock_book"]]


# ---------------------------------------------------------------------------------------------- prices and signals


class Prices:
    """15m closes by bar-end time.  ``exact`` needs the bar; ``at`` forward-fills a missing bar only when the symbol has
    later bars (a hole inside published data) and returns None for a symbol that lags (no bar at or after the time)."""

    def __init__(self, perp: Mapping[str, pd.DataFrame]) -> None:
        self._ns: dict[str, np.ndarray] = {}
        self._close: dict[str, np.ndarray] = {}
        for sym, f in perp.items():
            if len(f):
                self._ns[sym] = pd.DatetimeIndex(f.index).as_unit("ns").asi8
                self._close[sym] = f["close"].to_numpy(dtype=float)

    def symbols(self) -> list[str]:
        return list(self._ns)

    @staticmethod
    def _t(t: pd.Timestamp) -> int:
        return pd.Timestamp(t).as_unit("ns").value

    def exact(self, sym: str, t: pd.Timestamp) -> float | None:
        ns = self._ns.get(sym)
        if ns is None:
            return None
        i = int(np.searchsorted(ns, self._t(t), side="left"))
        return float(self._close[sym][i]) if i < len(ns) and ns[i] == self._t(t) else None

    def at(self, sym: str, t: pd.Timestamp) -> tuple[float | None, bool]:
        ns = self._ns.get(sym)
        if ns is None:
            return None, False
        tv = self._t(t)
        j = int(np.searchsorted(ns, tv, side="right"))      # bars ending at or before t: [0, j)
        if j == 0:
            return None, False
        if ns[j - 1] == tv:
            return float(self._close[sym][j - 1]), False
        if j < len(ns):                                      # a later bar exists: a hole, carry the last trade price
            return float(self._close[sym][j - 1]), True
        return None, False                                   # lag: no bar at or after t

    def last_close(self, sym: str) -> float | None:
        c = self._close.get(sym)
        return None if c is None or len(c) == 0 else float(c[-1])

    def last_bar(self, sym: str) -> pd.Timestamp | None:
        ns = self._ns.get(sym)
        return None if ns is None else pd.Timestamp(int(ns[-1]), unit="ns", tz="UTC")


def median_daily_quote_volume(frame: pd.DataFrame, day: date) -> float | None:
    """Median over the 7 UTC days before ``day`` of the daily perp quote volume (sum of 15m bars); None unless all 7
    days have bars."""
    hi = pd.Timestamp(day, tz="UTC")
    lo = hi - LIQUIDITY_DAYS * DAY
    idx = pd.DatetimeIndex(frame.index)
    a, b = int(idx.searchsorted(lo, side="right")), int(idx.searchsorted(hi, side="right"))
    sub = frame["quote_volume"].iloc[a:b]
    if len(sub) == 0:
        return None
    days = (pd.DatetimeIndex(sub.index) - BAR).floor("D")
    by_day = pd.Series(sub.to_numpy(dtype=float), index=days).groupby(level=0).sum()
    return float(by_day.median()) if len(by_day) == LIQUIDITY_DAYS else None


def momentum_signal(adjclose: pd.Series, formation: date, previous_session: date) -> float | None:
    """12-1 signal: adjusted close 21 trading days before over 252 trading days before the formation day, using closes
    strictly before the formation day only.  None unless 253 such closes exist and the last is the previous session."""
    cut = pd.Timestamp(formation, tz="UTC")
    closes = adjclose.loc[adjclose.index < cut].dropna()
    if len(closes) < MOMENTUM_MIN_CLOSES or closes.index[-1].date() != previous_session:
        return None
    return float(closes.iloc[-SKIP_DAYS] / closes.iloc[-FORM_DAYS] - 1.0)


def quintile_legs(signal: Mapping[str, float]) -> tuple[list[str], list[str]]:
    """(bottom quintile, top quintile) of the signal: ``n // 5`` names each, ties broken by symbol."""
    order = sorted(signal, key=lambda s: (signal[s], s))
    k = len(order) // 5
    return (order[:k], order[len(order) - k:]) if k else ([], [])


def leg_weights(long: Sequence[str], short: Sequence[str]) -> dict[str, float]:
    """0.5 gross per leg, equal weight within the leg."""
    w: dict[str, float] = {}
    for s in long:
        w[s] = 0.5 / len(long)
    for s in short:
        w[s] = -0.5 / len(short)
    return w


# -------------------------------------------------------------------------------------------------- market and events


@dataclass
class Market:
    clock: Clock
    start: pd.Timestamp
    as_of: pd.Timestamp
    horizon: pd.Timestamp                    # data end: 00:00 UTC after the latest published archive day
    perp: dict[str, pd.DataFrame]            # close, high, low, quote_volume (15m, bar-end index)
    marks: dict[str, pd.DataFrame]           # high, low: mark price with perp fallback
    funding: dict[str, pd.DataFrame]
    yahoo: dict[str, pd.DataFrame]
    stock: list[tuple[str, str]]             # (perp symbol, yahoo symbol) of the stock books
    unscored: set[date] = field(default_factory=set)
    min_volume: float = MIN_VOLUME_USDT
    min_names: int = MIN_NAMES
    yahoo_failed: dict[str, str] = field(default_factory=dict)     # yahoo symbol -> error of a failed fetch
    calendar_pending_after: date | None = None                     # sessions after it are unverified (SPY unavailable)

    def __post_init__(self) -> None:
        self.prices = Prices(self.perp)
        self.cover = nmf.covered_through(self.funding)
        self.holes = {k: nmf.funding_hole_intervals(f) for k, f in self.funding.items()}

    def candidates(self, liq_day: date, required: Sequence[pd.Timestamp], need: pd.Timestamp
                   ) -> tuple[list[str], list[str]]:
        """Stock perps that are liquid at ``liq_day`` and have every required bar (eligible), and liquid ones that lag
        (their last bar is before ``need`` and within the lag window of the data end): the formation is pending."""
        eligible: list[str] = []
        lagging: list[str] = []
        lag = pd.Timedelta(days=LAG_WINDOW_DAYS)
        for sym, _ in self.stock:
            frame = self.perp.get(sym)
            if frame is None or len(frame) == 0:
                continue
            vol = median_daily_quote_volume(frame, liq_day)
            if vol is None or vol < self.min_volume:
                continue
            if all(self.prices.exact(sym, t) is not None for t in required):
                eligible.append(sym)
                continue
            last = self.prices.last_bar(sym)
            if last is not None and last < need and last < self.horizon and self.horizon - last <= lag:
                lagging.append(sym)
        return eligible, lagging


@dataclass
class Event:
    kind: str                       # "B1" (monthly formation, also B0) or "B2" (weekly)
    label: str                      # session date, ISO
    session: date
    entry: pd.Timestamp             # B1: execution bar; B2: entry bar
    exit: pd.Timestamp | None
    status: str = "formed"          # formed | pending | unscored_calendar
    reason: str | None = None
    eligible: list[str] = field(default_factory=list)
    lagging: list[str] = field(default_factory=list)
    weights: dict[str, dict[str, float]] = field(default_factory=dict)   # book -> signed 1x weights
    detail: dict[str, Any] = field(default_factory=dict)
    signal: dict[str, float] = field(default_factory=dict)
    yahoo_blocked: list[str] = field(default_factory=list)      # B1 only: "yahoo_unavailable:<sym>" (B0 does not use Yahoo)


def _calendar_pending(mkt: Market, ev: Event) -> bool:
    if mkt.calendar_pending_after is not None and ev.session > mkt.calendar_pending_after:
        ev.status, ev.reason = "pending", "calendar_pending:yahoo_unavailable:SPY"
        return True
    return False


def b1_event(mkt: Market, session: date) -> Event:
    close_t = mkt.clock.session_close(session)
    ev = Event("B1", session.isoformat(), session, close_t, None)
    if _calendar_pending(mkt, ev):
        return ev
    if session in mkt.unscored:
        ev.status, ev.reason = "unscored_calendar", "session differs from the realized SPY calendar"
        return ev
    if close_t > mkt.horizon:
        ev.status, ev.reason = "pending", "formation bar not yet published"
        return ev
    eligible, lagging = mkt.candidates(close_t.date(), [close_t], close_t)
    ev.eligible, ev.lagging = eligible, lagging
    if lagging:
        ev.status, ev.reason = "pending", "per-symbol lag: " + ",".join(sorted(lagging))
        return ev
    prev = mkt.clock.previous_session(session)
    ysym = dict(mkt.stock)
    signals: dict[str, float] = {}
    for sym in eligible:
        y = ysym[sym]
        frame = mkt.yahoo.get(y)
        if y in mkt.yahoo_failed and (frame is None or len(frame) == 0 or frame.index[-1].date() < prev):
            ev.yahoo_blocked.append(f"yahoo_unavailable:{y}")      # never drop a symbol because its fetch failed
            continue
        sig = None if frame is None else momentum_signal(frame["adjclose"], session, prev)
        if sig is not None:
            signals[sym] = sig
    ev.signal = signals
    b0 = {s: 1.0 / len(eligible) for s in eligible} if len(eligible) >= mkt.min_names else {}
    b1: dict[str, float] = {}
    longs: list[str] = []
    shorts: list[str] = []
    if ev.yahoo_blocked:
        ev.reason = "B1 pending: " + ",".join(sorted(ev.yahoo_blocked))
    elif len(signals) >= mkt.min_names:
        shorts, longs = quintile_legs(signals)
        b1 = leg_weights(longs, shorts)
    ev.weights = {BOOK_B0: b0, BOOK_B1: b1}
    ev.detail = {"eligible": len(eligible), "with_signal": len(signals), "b0_flat_min_names": not b0,
                 "b1_flat_min_names": not b1 and not ev.yahoo_blocked, "b1_yahoo_blocked": sorted(ev.yahoo_blocked),
                 "long": sorted(longs), "short": sorted(shorts)}
    return ev


def b2_event(mkt: Market, session: date) -> Event:
    clock = mkt.clock
    open_t = clock.session_open(session)
    sig_t, entry_t, exit_t = open_t + BAR, open_t + 2 * BAR, clock.session_close(session)
    ref_t = clock.session_close(clock.previous_session(session))
    ev = Event("B2", session.isoformat(), session, entry_t, exit_t)
    if _calendar_pending(mkt, ev):
        return ev
    if session in mkt.unscored:
        ev.status, ev.reason = "unscored_calendar", "session differs from the realized SPY calendar"
        return ev
    if exit_t > mkt.horizon:
        ev.status, ev.reason = "pending", "exit bar not yet published"
        return ev
    eligible, lagging = mkt.candidates(sig_t.date(), [ref_t, sig_t, entry_t], entry_t)
    ev.eligible, ev.lagging = eligible, lagging
    if lagging:
        ev.status, ev.reason = "pending", "per-symbol lag: " + ",".join(sorted(lagging))
        return ev
    signal = {s: mkt.prices.exact(s, sig_t) / mkt.prices.exact(s, ref_t) - 1.0 for s in eligible}
    ev.signal = signal
    weights: dict[str, float] = {}
    longs: list[str] = []
    shorts: list[str] = []
    if len(eligible) >= mkt.min_names:
        longs, shorts = quintile_legs(signal)          # long the bottom quintile, short the top
        weights = leg_weights(longs, shorts)
    ev.weights = {BOOK_B2: weights}
    ev.detail = {"eligible": len(eligible), "flat_min_names": not weights, "long": sorted(longs), "short": sorted(shorts),
                 "reference_bar": ref_t.isoformat(), "signal_bar": sig_t.isoformat()}
    return ev


def formation_sessions(clock: Clock, start: pd.Timestamp, as_of: pd.Timestamp) -> list[date]:
    """B1 formation days: the first US trading day on/after the start, then the first of each later month."""
    first = clock.first_formation_session(start)
    out = [first]
    y, m = first.year, first.month
    while True:
        m += 1
        if m == 13:
            y, m = y + 1, 1
        d = clock.first_session_of_month(y, m)
        if clock.session_close(d) > as_of:
            break
        out.append(d)
    return [d for d in out if clock.session_close(d) > start and clock.session_close(d) <= as_of]


def weekend_sessions(clock: Clock, start: pd.Timestamp, as_of: pd.Timestamp) -> list[date]:
    """First US session of each week whose entry bar is after the start and whose open has passed."""
    d = start.date() - timedelta(days=7 + start.date().weekday())
    out: list[date] = []
    while d <= as_of.date():
        first = clock.week_first_session(d)
        if first is not None and clock.session_open(first) + 2 * BAR > start and clock.session_close(first) <= as_of:
            out.append(first)
        d += timedelta(days=7)
    return sorted(set(out))


# ------------------------------------------------------------------------------------------------- period engine


@dataclass
class Period:
    book: str
    label: str
    entry: pd.Timestamp
    exit: pd.Timestamp | None       # None: open, marked on UTC day ends up to ``limit``
    weights: dict[str, float]
    cost_in: float                  # 1x fraction of equity charged at the entry
    turnover: float                 # 1x traded notional (fraction of equity)
    limit: pd.Timestamp


@dataclass
class PeriodResult:
    segments: list[tuple[pd.Timestamp, float]]      # (UTC day, growth factor of the account within that day)
    stall: pd.Timestamp | None                       # first mark time a held symbol could not be priced (lag)
    stalled_symbols: list[str]
    liquidated: list[dict[str, Any]]
    funding_paid: float
    funding_pending: bool
    funding_gap: bool
    ffilled_marks: int
    delisted: dict[str, pd.Timestamp]
    final_growth: float | None
    lev_growth: float | None
    last_sample: pd.Timestamp | None


def _day_of(t: pd.Timestamp) -> pd.Timestamp:
    """UTC day of a mark: a bar ending exactly at midnight belongs to the day that it closes."""
    return (t - pd.Timedelta(1, "ns")).floor("D")


def simulate_period(p: Period, level: float, mkt: Market) -> PeriodResult:
    """One period at ``level`` x leverage.  Weights are fractions of period-start equity at 1x; positions are fixed
    units (buy and hold), isolated margin, liquidation by ``leverage_sim`` on the 15m mark high/low (perp fallback).
    Segments are the growth factors between consecutive marks (entry, UTC day ends, exit)."""
    e = p.entry
    end = p.exit if p.exit is not None else p.limit
    samples: list[pd.Timestamp] = []
    m = e.floor("D") + DAY
    while m < end or (p.exit is None and m == end):
        samples.append(m)
        m += DAY
    if p.exit is not None:
        samples.append(p.exit)
    syms = list(p.weights)
    p0 = {s: mkt.prices.exact(s, e) for s in syms}
    if any(v is None for v in p0.values()):
        raise TradfiError(f"entry bar missing for {[s for s, v in p0.items() if v is None]} at {e}")
    price: dict[str, list[float]] = {s: [] for s in syms}
    stall: pd.Timestamp | None = None
    stalled: list[str] = []
    ffilled = 0
    delisted: dict[str, pd.Timestamp] = {}
    lag = pd.Timedelta(days=LAG_WINDOW_DAYS)
    for k, t in enumerate(samples):
        got = {}
        for s in syms:
            v, ff = mkt.prices.at(s, t)
            if v is None:
                lb = mkt.prices.last_bar(s)
                if lb is not None and lb < t and mkt.horizon - lb > lag:
                    # more than 3 days before the data end: delisted, not lagging; exit at the last available close
                    v, ff = mkt.prices.last_close(s), False
                    delisted.setdefault(s, lb)
            got[s] = (v, ff)
        bad = [s for s, (v, _) in got.items() if v is None]
        if bad:
            stall, stalled = t, bad
            samples = samples[:k]
            break
        for s, (v, ff) in got.items():
            price[s].append(float(v))
            ffilled += int(ff)
    last = samples[-1] if samples else None
    thr_L = float(level)
    # funding: realized settlements in (entry, last mark], paid by a long on the settlement-time notional
    fund_cum: dict[str, list[float]] = {s: [0.0] * len(samples) for s in syms}
    pending = False
    gap = False
    if last is not None:
        for s in syms:
            fr = mkt.funding.get(s)
            if mkt.cover.get(s, nmf.EPOCH) <= last:
                pending = True
            if any(a < last and b > e for a, b in mkt.holes.get(s, ())):
                gap = True
            if fr is None or len(fr) == 0:
                continue
            idx = pd.DatetimeIndex(fr.index)
            lo, hi = int(idx.searchsorted(e, side="right")), int(idx.searchsorted(last, side="right"))
            events = []
            for j in range(lo, hi):
                px_s, _ = mkt.prices.at(s, idx[j])
                if px_s is not None:
                    events.append((idx[j], float(fr["rate"].iloc[j]) * px_s / p0[s]))
            acc, ptr = 0.0, 0
            for k, t in enumerate(samples):
                while ptr < len(events) and events[ptr][0] <= t:
                    acc += events[ptr][1]
                    ptr += 1
                fund_cum[s][k] = acc
    liquidated: list[dict[str, Any]] = []
    t_liq: dict[str, pd.Timestamp] = {}
    lev_growth: float | None = None
    if last is not None and syms:
        pos = pd.DataFrame({
            "entry_time": [e] * len(syms), "exit_time": [last] * len(syms), "symbol": syms, "mark_key": syms,
            "weight": [p.weights[s] for s in syms], "entry_price": [p0[s] for s in syms],
            "unit_return": [price[s][-1] / p0[s] - 1.0 - fund_cum[s][-1] for s in syms]})
        adverse, _ = lev.position_adverse_excursions(pos, mkt.marks)
        hit = np.asarray(lev.is_liquidated(adverse, level), dtype=bool)
        thr = lev.liquidation_threshold(level)
        for i in np.flatnonzero(hit):
            s = syms[i]
            fr = mkt.marks[s]
            sel = fr.loc[(fr.index > e) & (fr.index <= last)]
            adv = ((p0[s] - sel["low"]) if p.weights[s] > 0 else (sel["high"] - p0[s])) / p0[s]
            first = np.flatnonzero(adv.to_numpy(dtype=float) >= thr - 1e-12)
            t_liq[s] = sel.index[int(first[0])] if len(first) else last
            liquidated.append({"symbol": s, "period": p.label, "side": int(np.sign(p.weights[s])),
                               "liquidated_at": t_liq[s].isoformat(), "level": level})
        sim = lev.simulate_leverage(pos, adverse, pd.Series([p.cost_in], index=pd.DatetimeIndex([e])), level)
        lev_growth = float(1.0 + sim["period_returns"].iloc[0])
    g_prev = max(0.0, 1.0 - thr_L * p.cost_in)
    segments: list[tuple[pd.Timestamp, float]] = [(_day_of(e), g_prev)]
    g_last = g_prev
    for k, t in enumerate(samples):
        pnl = 0.0
        for s in syms:
            w = p.weights[s]
            if s in t_liq and t >= t_liq[s]:
                pnl += -abs(w) * (1.0 + lev.LIQUIDATION_FEE_RATE * level)
            else:
                pnl += level * w * (price[s][k] / p0[s] - 1.0 - fund_cum[s][k])
        g = max(0.0, 1.0 - thr_L * p.cost_in + pnl)
        segments.append((_day_of(t), g / g_prev if g_prev > 0 else 1.0))
        g_prev = g_last = g
    funding_paid = 0.0
    if last is not None:
        funding_paid = float(sum(level * p.weights[s] * fund_cum[s][-1] for s in syms if s not in t_liq))
    return PeriodResult(segments, stall, stalled, liquidated, funding_paid, pending, gap, ffilled, delisted,
                        g_last if last is not None else None, lev_growth, last)


@dataclass
class BookRun:
    growth: dict[pd.Timestamp, float]            # UTC day -> account growth factor
    growth_clean: dict[pd.Timestamp, float]      # same without periods that carry funding_pending
    book_end: pd.Timestamp                       # days with day + 1 <= book_end are scored (contiguous prefix)
    liquidated: list[dict[str, Any]]
    trades: int
    turnover: float
    funding_paid: float
    funding_pending_periods: int
    funding_gap_periods: int
    ffilled_marks: int
    stalls: list[dict[str, Any]]
    periods: int
    lev_check_max_abs_diff: float
    min_equity: float = 1.0
    ruin: bool = False
    delisted: list[dict[str, Any]] = field(default_factory=list)


def simulate_book(periods: Sequence[Period], level: float, mkt: Market, book_end: pd.Timestamp) -> BookRun:
    """Simulate the periods in order.  Counters (trades, turnover, funding, liquidations, flags) cover only periods that
    contribute a scored day; the equity path (``min_equity``, ``ruin`` = below half of the start) runs over the scored
    segments; ``leverage_sim`` agreement is enforced to 1e-9."""
    growth: dict[pd.Timestamp, float] = {}
    clean: dict[pd.Timestamp, float] = {}
    run = BookRun(growth, clean, book_end, [], 0, 0.0, 0.0, 0, 0, 0, [], 0, 0.0)
    kept: list[tuple[Period, PeriodResult]] = []
    for p in periods:
        if p.entry >= run.book_end:
            break
        res = simulate_period(p, level, mkt)
        if res.lev_growth is not None and res.final_growth is not None:
            diff = abs(res.lev_growth - res.final_growth)
            run.lev_check_max_abs_diff = max(run.lev_check_max_abs_diff, diff)
            if diff > LEV_CHECK_TOLERANCE:
                raise TradfiError(f"engine and leverage_sim disagree by {diff:.3e} in period {p.label} at {level}x")
        if res.stall is not None:
            run.book_end = min(run.book_end, _day_of(res.stall))      # the day the stalled mark closes is not scored
            run.stalls.append({"period": p.label, "book": p.book, "stall_at": res.stall.isoformat(),
                               "symbols": res.stalled_symbols,
                               "reason": "per-symbol lag (last bar within 3 days of the data end): bar not yet "
                                         "published, pending"})
        kept.append((p, res))
        if res.stall is not None:
            break
    equity = 1.0
    for p, res in kept:
        segs = [(d, f) for d, f in res.segments if d + DAY <= run.book_end]
        if not segs:
            continue
        run.periods += 1
        run.trades += len(p.weights)
        run.turnover += level * p.turnover
        run.liquidated.extend(x for x in res.liquidated
                              if _day_of(pd.Timestamp(x["liquidated_at"])) + DAY <= run.book_end)
        run.funding_paid += res.funding_paid
        run.funding_pending_periods += int(res.funding_pending)
        run.funding_gap_periods += int(res.funding_gap)
        run.ffilled_marks += res.ffilled_marks
        run.delisted.extend({"symbol": s, "period": p.label, "last_bar": t.isoformat(),
                             "flag": "delisted_exit_at_last_close"} for s, t in sorted(res.delisted.items()))
        for day, f in segs:
            growth[day] = growth.get(day, 1.0) * f
            clean[day] = clean.get(day, 1.0) * (1.0 if res.funding_pending else f)
            equity *= f
            run.min_equity = min(run.min_equity, equity)
    run.ruin = bool(run.min_equity < lev.RUIN_EQUITY_FRACTION)
    return run


def daily_series(growth: Mapping[pd.Timestamp, float], first_stamp: pd.Timestamp, book_end: pd.Timestamp) -> pd.Series:
    """Daily account returns stamped at the END of the UTC day they cover (so every stamp is after the start),
    zero-filled over the scored range ``[first_stamp, book_end]``."""
    if book_end < first_stamp:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    stamps = pd.date_range(first_stamp, book_end, freq="D", tz="UTC")
    return pd.Series([growth.get(s - DAY, 1.0) - 1.0 for s in stamps], index=stamps, dtype=float)


def _turnover(prev: Mapping[str, float], new: Mapping[str, float]) -> float:
    return float(sum(abs(new.get(s, 0.0) - prev.get(s, 0.0)) for s in set(prev) | set(new)))


def monthly_periods(events: Sequence[Event], book: str, horizon: pd.Timestamp, yahoo_gated: bool = False
                    ) -> tuple[list[Period], pd.Timestamp, list[dict[str, Any]]]:
    """B0 / B1 periods from the formation events; a pending event stalls the book at its day (earlier days stay
    scored); an unscored-calendar event is skipped (no rebalance that month)."""
    pending: list[dict[str, Any]] = []
    formed: list[Event] = []
    stall: pd.Timestamp | None = None
    for ev in sorted(events, key=lambda x: x.entry):
        if ev.status == "pending":
            stall = ev.entry
            pending.append({"book": book, "event": ev.label, "reason": ev.reason})
            break
        if yahoo_gated and ev.status == "formed" and ev.yahoo_blocked:
            stall = ev.entry                       # B1 is pending from the first formation whose signal needs Yahoo
            pending.append({"book": book, "event": ev.label, "reason": ",".join(sorted(ev.yahoo_blocked))})
            break
        if ev.status == "formed":
            formed.append(ev)
        else:
            pending.append({"book": book, "event": ev.label, "reason": ev.reason, "unscored": True})
    book_end = horizon if stall is None else min(horizon, _day_of(stall))
    periods: list[Period] = []
    prev: dict[str, float] = {}
    for i, ev in enumerate(formed):
        w = ev.weights[book]
        turn = _turnover(prev, w)
        nxt = formed[i + 1].entry if i + 1 < len(formed) else None
        periods.append(Period(book, ev.label, ev.entry, nxt, dict(w), SIDE_COST * turn, turn, book_end))
        prev = w
    return periods, book_end, pending


def weekly_periods(events: Sequence[Event], horizon: pd.Timestamp) -> tuple[list[Period], pd.Timestamp, list[dict[str, Any]]]:
    pending: list[dict[str, Any]] = []
    periods: list[Period] = []
    stall: pd.Timestamp | None = None
    for ev in sorted(events, key=lambda x: x.entry):
        if ev.status == "pending":
            stall = ev.entry
            pending.append({"book": BOOK_B2, "event": ev.label, "reason": ev.reason})
            break
        if ev.status != "formed":
            pending.append({"book": BOOK_B2, "event": ev.label, "reason": ev.reason, "unscored": True})
            continue
        w = ev.weights[BOOK_B2]
        if w:
            gross = float(sum(abs(v) for v in w.values()))
            periods.append(Period(BOOK_B2, ev.label, ev.entry, ev.exit, dict(w), ROUND_TRIP_BPS / 1e4 * gross,
                                  2.0 * gross, horizon))
    book_end = horizon if stall is None else min(horizon, _day_of(stall))
    return periods, book_end, pending


# --------------------------------------------------------------------------------------------- B2 action-matched null


def b2_week_return(returns: Mapping[str, float], long: Sequence[str], short: Sequence[str],
                   round_trip_cost: float = ROUND_TRIP_BPS / 1e4) -> float:
    """1x weekly return of the B2 book: 0.5 gross per leg, equal weight, minus the round-trip cost on gross 1.0."""
    r = 0.0
    if long:
        r += 0.5 * float(np.mean([returns[s] for s in long]))
    if short:
        r -= 0.5 * float(np.mean([returns[s] for s in short]))
    return r - round_trip_cost * (0.5 * bool(long) + 0.5 * bool(short))


def b2_observed_cumulative(weeks: Sequence[Mapping[str, Any]]) -> float:
    g = 1.0
    for wk in weeks:
        g *= 1.0 + b2_week_return(wk["returns"], wk["long"], wk["short"])
    return g - 1.0


def b2_null(weeks: Sequence[Mapping[str, Any]], *, draws: int = NULL_DRAWS, seed: int = NULL_SEED) -> dict[str, Any]:
    """Action-matched null for the review (NOT run on real data before the review): the same number of longs and
    shorts as each B2 week, drawn at random among that week's eligible stocks, ``draws`` times, 1x weekly returns
    compounded.  ``weeks``: [{"returns": {symbol: price return entry->exit, funding EXCLUDED}, "long": [...], "short":
    [...]}] (the eligible set is the key set of ``returns``).  Returns the null distribution and the observed book's
    percentile in it."""
    rng = np.random.default_rng(seed)
    names = [sorted(wk["returns"]) for wk in weeks]
    arrays = [np.array([wk["returns"][s] for s in n], dtype=float) for wk, n in zip(weeks, names)]
    cost = ROUND_TRIP_BPS / 1e4
    cum = np.empty(draws)
    for d in range(draws):
        g = 1.0
        for wk, arr in zip(weeks, arrays):
            nl, ns = len(wk["long"]), len(wk["short"])
            pick = rng.permutation(len(arr))[: nl + ns]
            longs, shorts = arr[pick[:nl]], arr[pick[nl:]]
            r = (0.5 * longs.mean() if nl else 0.0) - (0.5 * shorts.mean() if ns else 0.0) - cost
            g *= 1.0 + r
        cum[d] = g - 1.0
    observed = b2_observed_cumulative(weeks)
    return {"draws": int(draws), "seed": int(seed), "weeks": len(weeks), "observed_cumulative": observed,
            "observed_percentile": nmf.percentile_of(cum, observed),
            "null_cumulative_quantiles": {f"p{q:02d}": float(np.percentile(cum, q)) for q in (5, 25, 50, 75, 95)},
            "null_mean": float(cum.mean())}


# ---------------------------------------------------------------------------------------------------- diagnostics


def d1_funding(mkt: Market, groups: Mapping[str, str], stock_perps: set[str]) -> dict[str, Any]:
    """Annualized realized funding paid by a long, per symbol and month (settlements after the start; a month counts
    only once its fundingRate file is published for the symbol), plus the equal-weighted mean per month."""
    first_month = pd.Timestamp(year=mkt.start.year, month=mkt.start.month, day=1, tz="UTC")
    months: list[pd.Timestamp] = []
    m = first_month
    while m + pd.offsets.MonthBegin(1) <= mkt.horizon:
        months.append(m)
        m = m + pd.offsets.MonthBegin(1)
    per_symbol: dict[str, Any] = {}
    cell: dict[str, dict[str, float]] = {}
    for sym, fr in mkt.funding.items():
        idx = pd.DatetimeIndex(fr.index)
        rows, pending_months = {}, []
        for m0 in months:
            m1 = m0 + pd.offsets.MonthBegin(1)
            key = m0.strftime("%Y-%m")
            if mkt.cover.get(sym, nmf.EPOCH) < m1:
                pending_months.append(key)
                continue
            sel = (idx > mkt.start) & (idx >= m0) & (idx < m1)
            if not sel.any():
                continue
            days = (m1 - max(mkt.start, m0)) / DAY
            ann = float(fr["rate"].to_numpy(dtype=float)[sel].sum() * 365.0 / days)
            rows[key] = {"annualized": ann, "settlements": int(sel.sum())}
            cell.setdefault(key, {})[sym] = ann
        per_symbol[sym] = {"group": groups.get(sym), "months": rows, "funding_pending_months": pending_months}
    ew = {k: {"stock_book": (float(np.mean([v for s, v in c.items() if s in stock_perps]))
                             if any(s in stock_perps for s in c) else None),
              "all_symbols": float(np.mean(list(c.values()))), "symbols": len(c)}
          for k, c in sorted(cell.items())}
    return {"per_symbol": per_symbol, "equal_weighted_by_month": ew,
            "note": "annualized = sum of settlement rates / days observed in the month * 365; positive = longs pay"}


def _dev_stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median_abs_bps": None, "p95_abs_bps": None}
    a = np.asarray(values, dtype=float)
    return {"n": int(len(a)), "median_abs_bps": float(np.median(a)), "p95_abs_bps": float(np.percentile(a, 95))}


def d2_tracking(mkt: Market, symbols: Sequence[tuple[str, str, str]]) -> dict[str, Any]:
    """|perp close of the 15m bar ending at the US close / Yahoo unadjusted close - 1| in bps on US sessions after the
    start; ``symbols``: (perp symbol, yahoo symbol, group) of stocks and ETFs (commodity futures are not comparable)."""
    first = mkt.clock.first_formation_session(mkt.start)
    last = min(mkt.horizon, mkt.as_of - pd.Timedelta(hours=2)).date()
    sessions = [d for d in mkt.clock.sessions_between(first, last) if d not in mkt.unscored]
    per_symbol: dict[str, Any] = {}
    pooled: dict[str, list[float]] = {}
    for sym, ysym, group in symbols:
        frame = mkt.yahoo.get(ysym)
        if frame is None:
            continue
        devs = []
        for d in sessions:
            t = mkt.clock.session_close(d)
            if t <= mkt.start or t > mkt.horizon:
                continue
            ts = pd.Timestamp(d, tz="UTC")
            px = mkt.prices.exact(sym, t)
            if px is None or ts not in frame.index:
                continue
            devs.append(abs(px / float(frame.loc[ts, "close"]) - 1.0) * 1e4)
        per_symbol[sym] = {"group": group, **_dev_stats(devs)}
        pooled.setdefault(group, []).extend(devs)
    return {"per_symbol": per_symbol, "pooled": {g: _dev_stats(v) for g, v in sorted(pooled.items())},
            "sessions_checked": len(sessions)}


def _ols(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    n = len(x)
    if n < 3 or float(np.var(x)) == 0.0 or float(np.var(y)) == 0.0:
        return {"n": int(n), "slope": None, "slope_reverse": None, "correlation": None}
    cov = float(np.cov(x, y, ddof=0)[0, 1])
    return {"n": int(n), "slope": cov / float(np.var(x)), "slope_reverse": cov / float(np.var(y)),
            "correlation": float(np.corrcoef(x, y)[0, 1])}


def d3_weekend_discovery(mkt: Market, b2_events: Sequence[Event]) -> dict[str, Any]:
    """Pooled across stocks and weeks (B2 weeks after the start): the weekend perp return (B2 signal) against (a) the
    underlying's Monday open gap (Yahoo open / previous close - 1) and (b) its first-session open-to-close return.
    ``slope`` regresses the perp return on the regressor, ``slope_reverse`` the regressor on the perp return."""
    ysym = dict(mkt.stock)
    wk, gap, oc = [], [], []
    weeks = 0
    for ev in b2_events:
        if ev.status != "formed":
            continue
        prev = mkt.clock.previous_session(ev.session)
        t_now, t_prev = pd.Timestamp(ev.session, tz="UTC"), pd.Timestamp(prev, tz="UTC")
        used = 0
        for sym, sig in ev.signal.items():
            frame = mkt.yahoo.get(ysym.get(sym, ""))
            if frame is None or t_now not in frame.index or t_prev not in frame.index:
                continue
            g = float(frame.loc[t_now, "open"] / frame.loc[t_prev, "close"] - 1.0)
            o = float(frame.loc[t_now, "close"] / frame.loc[t_now, "open"] - 1.0)
            if not (np.isfinite(g) and np.isfinite(o)):
                continue                                              # Yahoo rows may lack an open
            wk.append(sig)
            gap.append(g)
            oc.append(o)
            used += 1
        weeks += int(used > 0)
    w, g, o = np.array(wk), np.array(gap), np.array(oc)
    return {"weeks": weeks, "observations": int(len(w)),
            "weekend_perp_on_monday_open_gap": _ols(g, w), "weekend_perp_on_first_session_open_to_close": _ols(o, w)}


def beta_to_b0(y: pd.Series, b0: pd.Series) -> dict[str, Any] | None:
    both = pd.concat([y, b0], axis=1, keys=["y", "b0"]).dropna()
    if len(both) < 3 or float(both["b0"].var(ddof=0)) == 0.0:
        return None
    beta = float(both["y"].cov(both["b0"], ddof=0) / both["b0"].var(ddof=0))
    alpha = float(both["y"].mean() - beta * both["b0"].mean())
    net = both["y"] - beta * both["b0"]
    return {"n": int(len(both)), "beta": beta, "alpha_daily_bps": alpha * 1e4,
            "net_of_b0_beta": summarize(net, nw_lags=NW_LAGS),
            "note": "full-sample regression on B0 1x daily returns; descriptive"}


# ----------------------------------------------------------------------------------------------------- assembly


def book_key(book_id: str, level: int) -> str:
    return f"{book_id}_{int(level)}x"


def book_levels(config: Mapping[str, Any]) -> dict[str, list[int]]:
    return {b: [int(x) for x in config["books"][b]["leverage_levels"]] for b in (BOOK_B0, BOOK_B1, BOOK_B2)}


def compute_books(mkt: Market, config: Mapping[str, Any]) -> tuple[dict[str, nmf.BookResult], dict[str, Any]]:
    """All books at all registered levels from a loaded market.  Nothing is computed when the archive has not reached
    the start (``PRE_START``)."""
    levels = book_levels(config)
    first_stamp = mkt.start.normalize() + DAY
    info: dict[str, Any] = {"events": {}, "pending": [], "b2_null_inputs": []}
    books: dict[str, nmf.BookResult] = {}
    if mkt.horizon <= mkt.start:
        return books, info
    b1_events = [b1_event(mkt, d) for d in formation_sessions(mkt.clock, mkt.start, mkt.as_of)]
    b2_events = [b2_event(mkt, d) for d in weekend_sessions(mkt.clock, mkt.start, mkt.as_of)]
    info["events"] = {
        "B1": [{"session": e.label, "status": e.status, "reason": e.reason, **e.detail} for e in b1_events],
        "B2": [{"session": e.label, "status": e.status, "reason": e.reason, **e.detail} for e in b2_events]}
    plans = {BOOK_B0: monthly_periods(b1_events, BOOK_B0, mkt.horizon),
             BOOK_B1: monthly_periods(b1_events, BOOK_B1, mkt.horizon, yahoo_gated=True),
             BOOK_B2: weekly_periods(b2_events, mkt.horizon)}
    b2_end = plans[BOOK_B2][1]
    for book_id, (periods, book_end, pending) in plans.items():
        info["pending"].extend(pending)
        for level in levels[book_id]:
            run = simulate_book(periods, level, mkt, book_end)
            if book_id == BOOK_B2:
                b2_end = min(b2_end, run.book_end)
            info["pending"].extend(s for s in run.stalls if level == levels[book_id][0])
            daily = daily_series(run.growth, first_stamp, run.book_end)
            clean = daily_series(run.growth_clean, first_stamp, run.book_end)
            books[book_key(book_id, level)] = nmf.BookResult(
                daily, clean, run.trades, len(run.liquidated), run.funding_pending_periods,
                {"liquidated_positions": run.liquidated, "turnover_notional_over_equity": run.turnover,
                 "funding_paid_equity_fraction": run.funding_paid, "periods": run.periods,
                 "ffilled_marks": run.ffilled_marks, "scored_through": run.book_end.isoformat(),
                 "leverage_sim_period_check_max_abs_diff": run.lev_check_max_abs_diff,
                 "min_equity": run.min_equity, "ruin": run.ruin,
                 "delisted_exit_at_last_close": run.delisted, "delisted_exit_count": len(run.delisted)},
                run.funding_gap_periods)
    # B2 null inputs: one record per scored week (1x unit returns of the eligible set; the null is NOT run here)
    for ev in b2_events:
        if ev.status != "formed" or not ev.weights.get(BOOK_B2):
            continue
        if ev.exit is None or _day_of(ev.exit) + DAY > b2_end:          # only weeks the simulated B2 run scored
            continue
        rets = {}
        for s in ev.eligible:
            a, b = mkt.prices.exact(s, ev.entry), mkt.prices.at(s, ev.exit)[0]
            if a is not None and b is not None:
                rets[s] = round(b / a - 1.0, 8)
        if not all(s in rets for s in list(ev.detail["long"]) + list(ev.detail["short"])):
            continue                                                    # every leg name needs a return
        info["b2_null_inputs"].append({"week": ev.label, "long": ev.detail["long"], "short": ev.detail["short"],
                                       "returns": rets, "returns_basis": "price return entry to exit, funding excluded"})
    info["_events"] = {"B2": b2_events}
    return books, info


def coverage(mkt: Market, universe: Mapping[str, Any], archive_info: Mapping[str, Any],
             raw_mark_symbols: int | None = None) -> dict[str, Any]:
    """Counts and timestamps only (no prices, returns or funding values)."""
    last_bars = {s: mkt.prices.last_bar(s) for s in mkt.prices.symbols()}
    lagging = sorted(s for s, t in last_bars.items() if t is not None and t < mkt.horizon
                     and mkt.horizon - t <= pd.Timedelta(days=LAG_WINDOW_DAYS))
    stale = sorted(s for s, t in last_bars.items() if t is not None and mkt.horizon - t > pd.Timedelta(days=LAG_WINDOW_DAYS))
    ysym = [y for _, y in mkt.stock]
    return {
        "universe_symbols": len(universe["symbols"]),
        "stock_book_symbols": len(mkt.stock),
        "perp_15m_symbols_with_data": len(last_bars),
        "perp_15m_last_bar_min": min((t for t in last_bars.values() if t is not None), default=None),
        "perp_15m_last_bar_max": max((t for t in last_bars.values() if t is not None), default=None),
        "perp_15m_lagging_symbols": lagging, "perp_15m_stale_symbols": stale,
        "mark_15m_symbols_with_data": len(mkt.marks) if raw_mark_symbols is None else raw_mark_symbols,
        "funding_symbols_with_rows": sum(1 for f in mkt.funding.values() if len(f)),
        "funding_symbols_total": len(mkt.funding),
        "yahoo_symbols_loaded": len(mkt.yahoo),
        "yahoo_stock_symbols_with_253_closes": sum(1 for y in ysym if y in mkt.yahoo and len(mkt.yahoo[y]) >= MOMENTUM_MIN_CLOSES),
        "archive": dict(archive_info),
    }


def _forward_entry(book: nmf.BookResult, daily: pd.Series, clean: pd.Series) -> dict[str, Any]:
    out = nmf._forward_entry(daily, clean, book)
    out["turnover_notional_over_equity"] = book.detail.get("turnover_notional_over_equity", 0.0)
    out["funding_paid_equity_fraction"] = book.detail.get("funding_paid_equity_fraction", 0.0)
    out["scored_through"] = book.detail.get("scored_through")
    out["min_equity"] = book.detail.get("min_equity", 1.0)
    out["ruin"] = book.detail.get("ruin", False)
    out["delisted_exit_count"] = book.detail.get("delisted_exit_count", 0)
    return out


def build_report(config: Mapping[str, Any], books: Mapping[str, nmf.BookResult], info: Mapping[str, Any], *,
                 as_of: Any, data_end: pd.Timestamp, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise TradfiError("wrong watch config")
    as_of_ts = _utc(as_of)
    start = _utc(config["prospective_start_utc"])
    names = [book_key(b, lv) for b, levels in book_levels(config).items() for lv in levels]
    empty = nmf.BookResult(pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC")),
                           pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC")), 0, 0, 0)
    series = {n: nmf._after(books.get(n, empty).daily, start) for n in names}
    clean = {n: nmf._after(books.get(n, empty).daily_no_pending, start) for n in names}
    if any(len(books[n].daily) != len(series[n]) for n in names if n in books):
        raise TradfiError("a scored daily stamp is not strictly after the prospective start")
    days = max((len(s) for s in series.values()), default=0)
    forward = {n: _forward_entry(books.get(n, empty), series[n], clean[n]) for n in names}
    b0 = series[book_key(BOOK_B0, 1)]
    for n in names:
        if n.startswith("B1") or n.startswith("B2"):
            forward[n]["beta_to_b0"] = beta_to_b0(series[n], b0)
    report: dict[str, Any] = {
        "schema_version": 1,
        "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "data_end_utc": data_end.isoformat(),
        "review_window_open": bool((as_of_ts - start).days >= int(config["reporting"]["review_after_days"])),
        "forward": forward,
        "daily_returns": {n: nmf._series_dict(series[n]) for n in names},
        "books": {n: {k: v for k, v in books[n].detail.items()} for n in names if n in books},
        "cost_convention": "7 bps per side on traded notional x leverage; B0/B1 turnover is netted between consecutive "
                           "TARGET weights (sum |w_new - w_old|), not drifted holdings; B2 pays 14 bps on gross 1.0; "
                           "counters (trades, turnover, funding, liquidations) cover scored periods only",
        "stamp_convention": "a daily return is stamped at 00:00 UTC of the day AFTER the UTC day it covers, so that "
                            "every stamp (including the first Monday, which is the start day) is after the start",
        "claims": dict(config["claims"]),
    }
    report.update({k: v for k, v in info.items() if not k.startswith("_")})
    if extra:
        report.update(dict(extra))
    return report


# ------------------------------------------------------------------------------------------------------ loading


def load_market_data(universe: Mapping[str, Any], *, start: pd.Timestamp, end: str, fetch: bsa.Fetcher,
                     cache_root: Path | None, workers: int) -> dict[str, Any]:
    """15m perp (stocks and ETFs), 15m mark (stocks) and fundingRate (every in-scope perp) from start - 10 days."""
    data_start = (start - pd.Timedelta(days=DATA_PRELOAD_DAYS)).strftime("%Y-%m-%d")
    base = fa.cache_dir() if cache_root is None else cache_root / fa.CACHE_DIRNAME
    in_scope = [e for e in universe["symbols"] if e["group"] in ("stock", "etf", "commodity")]
    want_mark = {e["symbol"] for e in in_scope if e["stock_book"]}
    want_perp = {e["symbol"] for e in in_scope if e["group"] in ("stock", "etf")}

    def work(sym: str) -> tuple[str, dict[str, pd.DataFrame]]:
        parts: dict[str, pd.DataFrame] = {}
        if sym in want_perp:
            parts["perp"] = load_klines_15m("perp15", sym, end=end, start=data_start, fetch=fetch, directory=base)
        if sym in want_mark:
            parts["mark"] = load_klines_15m("mark15", sym, end=end, start=data_start, fetch=fetch, directory=base)
        parts["funding"] = fa.load_dataset("funding", sym, end=end, start=data_start, fetch=fetch, directory=base)
        return sym, parts

    perp: dict[str, pd.DataFrame] = {}
    mark: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, parts in pool.map(work, [e["symbol"] for e in in_scope]):
            if len(parts.get("perp", ())):
                perp[sym] = parts["perp"][["close", "high", "low", "quote_volume"]]
            if len(parts.get("mark", ())):
                mark[sym] = parts["mark"][["high", "low"]]
            funding[sym] = parts["funding"]
    return {"perp": perp, "mark": mark, "funding": funding}


def yahoo_cache_path(directory: Path, symbol: str) -> Path:
    return directory / (bsa.safe_name(symbol) + ".csv")


def read_yahoo_cache(directory: Path, symbol: str) -> pd.DataFrame | None:
    path = yahoo_cache_path(directory, symbol)
    if not path.exists():
        return None
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.sort_index()


def write_yahoo_cache(directory: Path, symbol: str, frame: pd.DataFrame) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_csv(yahoo_cache_path(directory, symbol))


def load_yahoo(symbols: Sequence[str], yahoo: YahooFetch, start: pd.Timestamp, as_of: pd.Timestamp, workers: int = 8,
               cache_dir: Path | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    """Fetch the daily series and persist them in ``cache_dir``.  A failed fetch falls back to the cached series (which the
    caller must check against the formations it needs); the failure is always returned in ``failed``:
    ``{symbol: {"error", "used_cache", "cache_last_date"}}``.  A symbol is never silently dropped."""
    lo = start - pd.Timedelta(days=YAHOO_HISTORY_DAYS)
    hi = as_of + pd.Timedelta(days=2)

    def one(sym: str) -> tuple[str, pd.DataFrame | str]:
        try:
            return sym, yahoo(sym, lo, hi)
        except Exception as exc:  # noqa: BLE001  (a failed symbol is reported; never dropped from a signal)
            return sym, f"{type(exc).__name__}: {exc}"

    frames: dict[str, pd.DataFrame] = {}
    failed: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, res in pool.map(one, list(dict.fromkeys(symbols))):
            if not isinstance(res, str):
                frames[sym] = res
                if cache_dir is not None and len(res):
                    try:
                        write_yahoo_cache(cache_dir, sym, res)
                    except OSError as exc:
                        _log(f"yahoo cache write failed for {sym}: {exc}")
                continue
            cached = read_yahoo_cache(cache_dir, sym) if cache_dir is not None else None
            if cached is not None and len(cached):
                frames[sym] = cached
            failed[sym] = {"error": res, "used_cache": cached is not None and len(cached) > 0,
                           "cache_last_date": None if cached is None or not len(cached)
                           else cached.index[-1].date().isoformat()}
    return frames, failed


def resolve_calendar(clock: Clock, frames: Mapping[str, pd.DataFrame], failed: Mapping[str, Any], start: pd.Timestamp,
                     horizon: pd.Timestamp, as_of: pd.Timestamp) -> tuple[dict[str, Any], date | None]:
    """SPY calendar check and the date after which sessions are unverified (None: all verified as usual).  When SPY could
    not be fetched the check is PENDING, not passed: with a cached series it covers sessions up to the cache's last bar,
    without one every session after the start is pending."""
    first = clock.first_formation_session(start)
    last = min(horizon, as_of).date()
    if first > last:
        return {"status": "no_session_yet", "checked_from": None, "checked_through": None, "unscored_sessions": [],
                "note": "no session after the start has occurred"}, None
    spy = frames.get("SPY")
    have = spy is not None and len(spy) > 0
    if "SPY" in failed and not have:
        return {"status": "pending", "reason": "yahoo_unavailable:SPY", "checked_from": None, "checked_through": None,
                "unscored_sessions": []}, first - timedelta(days=1)
    through = min(last, spy.index[-1].date()) if have else first - timedelta(days=1)
    cal = calendar_check(clock, [t.date() for t in spy.index] if have else [], first, through)
    cal["status"] = "checked"
    if "SPY" in failed:
        cal.update(status="pending", reason="yahoo_unavailable:SPY (cached series used; later sessions unverified)")
        return cal, through
    return cal, None


def run(config: Mapping[str, Any], universe: Mapping[str, Any], *, as_of: Any, fetch: bsa.Fetcher, yahoo: YahooFetch,
        cache_root: Path | None = None, workers: int = 24) -> dict[str, Any]:
    start = _utc(config["prospective_start_utc"])
    as_of_ts = _utc(as_of)
    t0 = time.time()
    clock = Clock.from_config(config)
    commodities = [e["symbol"] for e in universe["symbols"] if e["group"] == "commodity"]
    probe = commodities[0] if commodities else stock_book(universe)[0]["symbol"]
    day = latest_published_day(as_of_ts, probe, fetch)
    end = day.strftime("%Y-%m-%d")
    horizon = day + DAY
    _log(f"latest published 15m archive day {end}")
    data = load_market_data(universe, start=start, end=end, fetch=fetch, cache_root=cache_root, workers=workers)
    _log(f"archive loaded: {len(data['perp'])} perp / {len(data['mark'])} mark / {len(data['funding'])} funding "
         f"after {time.time() - t0:.0f}s")
    y_syms = [e["yahoo_symbol"] for e in universe["symbols"] if e["group"] in ("stock", "etf")] + ["SPY"]
    ycache = (fa.cache_dir() if cache_root is None else cache_root) / YAHOO_CACHE_DIRNAME
    frames, failed = load_yahoo(y_syms, yahoo, start, as_of_ts, cache_dir=ycache)
    _log(f"yahoo loaded: {len(frames)} ok, {len(failed)} failed ({sum(f['used_cache'] for f in failed.values())} "
         f"from cache) after {time.time() - t0:.0f}s")
    stock = [(e["symbol"], e["yahoo_symbol"]) for e in stock_book(universe)]
    marks = lc.mark_with_perp_fallback(data["mark"], {s: f[["high", "low"]] for s, f in data["perp"].items()}) \
        if data["perp"] else {}
    cal, cal_pending_after = resolve_calendar(clock, frames, failed, start, horizon, as_of_ts)
    mkt = Market(clock, start, as_of_ts, horizon, data["perp"], marks, data["funding"], frames, stock,
                 {date.fromisoformat(d) for d in cal["unscored_sessions"]},
                 yahoo_failed={k: v["error"] for k, v in failed.items()}, calendar_pending_after=cal_pending_after)
    books, info = compute_books(mkt, config)
    events = info.get("_events", {})
    groups = {e["symbol"]: e["group"] for e in universe["symbols"]}
    diagnostics: dict[str, Any] = {"note": "post-start data only; empty until sessions, settlements and weeks after the "
                                           "start are published"}
    if mkt.horizon > mkt.start:
        sd = [(e["symbol"], e["yahoo_symbol"], e["group"]) for e in universe["symbols"] if e["group"] in ("stock", "etf")]
        diagnostics["D1_funding"] = d1_funding(mkt, groups, {s for s, _ in stock})
        diagnostics["D2_tracking"] = d2_tracking(mkt, sd)
        diagnostics["D3_weekend_discovery"] = d3_weekend_discovery(mkt, events.get("B2", []))
    info["calendar_check"] = cal
    info["yahoo_failed"] = failed                     # top level of the report
    info["diagnostics"] = diagnostics
    info["coverage"] = coverage(mkt, universe, {"latest_published_day": end, "probe_symbol": probe}, len(data["mark"]))
    info["freshness"] = {"data_end": horizon.isoformat(), "lag_window_days": LAG_WINDOW_DAYS,
                         "perp_last_bar": {s: mkt.prices.last_bar(s).isoformat() for s in mkt.prices.symbols()}
                         if mkt.horizon > mkt.start else "withheld until the start (coverage counts above)"}
    return build_report(config, books, info, as_of=as_of_ts, data_end=horizon,
                        extra={"data": {"latest_published_day": end, "elapsed_seconds": round(time.time() - t0, 1)}})


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the TradFi perps paper forward watch (descriptive only).")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None, help="UTC timestamp (default: now); the latest archive day probed is "
                                                      "the UTC day of this instant")
    parser.add_argument("--cache-root", default=None, help="directory holding the archive caches (default: TEMP)")
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    as_of = _utc(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    fetch = nmf.CountingFetch(bsa.http_fetch)
    yahoo = CountingYahoo()
    report = run(config, load_universe(args.universe), as_of=as_of, fetch=fetch, yahoo=yahoo,
                 cache_root=None if args.cache_root is None else Path(args.cache_root), workers=args.workers)
    report["data"]["http_requests"] = fetch.requests
    report["data"]["http_megabytes"] = round(fetch.bytes / 1e6, 2)
    report["data"]["yahoo_requests"] = yahoo.requests
    report["provenance"] = {"config_sha256": sha256(Path(args.config).read_bytes()).hexdigest(),
                            "universe_sha256": universe_sha256(args.universe)}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False, default=nmf._json_default) + "\n",
                   encoding="utf-8")
    cov = report["coverage"]
    print(json.dumps({"status": report["status"], "data_end_utc": report["data_end_utc"],
                      "days": {k: v["days"] for k, v in report["forward"].items()},
                      "coverage": {k: cov[k] for k in ("stock_book_symbols", "perp_15m_symbols_with_data",
                                                       "mark_15m_symbols_with_data", "funding_symbols_with_rows",
                                                       "yahoo_symbols_loaded", "yahoo_stock_symbols_with_253_closes")},
                      "http_requests": report["data"]["http_requests"],
                      "yahoo_requests": report["data"]["yahoo_requests"],
                      "elapsed_seconds": report["data"]["elapsed_seconds"]}, default=nmf._json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

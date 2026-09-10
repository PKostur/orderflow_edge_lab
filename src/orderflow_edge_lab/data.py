from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import csv
import math
import re
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketEvent:
    ts_ns: int
    symbol: str
    kind: str
    price: float | None = None
    size: float | None = None
    bid: float | None = None
    ask: float | None = None
    side: Side = Side.UNKNOWN
    side_source: str = "unknown"
    source: str = "unknown"

    def __post_init__(self) -> None:
        if type(self.ts_ns) is not int or self.ts_ns <= 0 or not self.symbol:
            raise ValueError("event requires a positive integer timestamp and symbol")
        if self.kind not in {"TRADE", "QUOTE"} or not isinstance(self.side, Side):
            raise ValueError("unsupported event kind or side")
        for value in (self.price, self.size, self.bid, self.ask):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
                raise ValueError("event numeric values must be finite")
        if self.kind == "TRADE" and (self.price is None or self.price <= 0):
            raise ValueError("trade price must be positive")
        if any(v is not None and v <= 0 for v in (self.bid, self.ask)):
            raise ValueError("quote prices must be positive")
        if self.size is not None and self.size < 0:
            raise ValueError("size must be nonnegative")

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.ts_ns / 1_000_000_000, tz=timezone.utc)


@dataclass(frozen=True)
class DataQualityPolicy:
    min_events: int = 100
    max_unknown_trade_side_fraction: float = 0.35
    max_tick_rule_trade_fraction: float = 0.50
    min_trade_bbo_fraction_when_explicit_side_low: float = 0.50
    explicit_side_fraction_exempting_bbo: float = 0.90
    max_crossed_quote_fraction: float = 0.001
    max_duplicate_fraction: float = 0.001
    require_monotonic_timestamps: bool = True
    max_latest_age_seconds: float | None = None
    require_trades: bool = True

    def __post_init__(self) -> None:
        if self.min_events < 1:
            raise ValueError("min_events must be >= 1")
        for name in (
            "max_unknown_trade_side_fraction",
            "max_tick_rule_trade_fraction",
            "min_trade_bbo_fraction_when_explicit_side_low",
            "explicit_side_fraction_exempting_bbo",
            "max_crossed_quote_fraction",
            "max_duplicate_fraction",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.max_latest_age_seconds is not None and (not math.isfinite(self.max_latest_age_seconds) or self.max_latest_age_seconds <= 0):
            raise ValueError("max_latest_age_seconds must be positive")


@dataclass(frozen=True)
class DataQualityReport:
    total_events: int
    trades: int
    quotes: int
    explicit_trade_side_fraction: float
    quote_inferred_trade_side_fraction: float
    tick_rule_trade_side_fraction: float
    trade_bbo_fraction: float
    classified_trade_side_fraction: float
    unknown_trade_side_fraction: float
    crossed_quote_fraction: float
    duplicate_fraction: float
    monotonic_timestamps: bool
    latest_age_seconds: float | None
    passed: bool
    failures: tuple[str, ...]


_TS_KEYS = ("timestamp", "time", "datetime", "ts", "event_time", "eventtime")
_SYMBOL_KEYS = ("symbol", "instrument", "ticker", "event_symbol", "eventsymbol")
_KIND_KEYS = ("kind", "event", "event_type", "type")
_PRICE_KEYS = ("price", "trade_price", "last", "last_price")
_SIZE_KEYS = ("size", "trade_size", "quantity", "qty", "volume")
_BID_KEYS = ("bid", "bid_price", "bidprice")
_ASK_KEYS = ("ask", "ask_price", "askprice")
_SIDE_KEYS = ("side", "aggressor", "aggressor_side", "direction")


def _first(row: Mapping[str, object], keys: Sequence[str]) -> object | None:
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = lower.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_timestamp_ns(value: object) -> int:
    """Parse ISO-8601 or unix timestamp values into integer nanoseconds UTC."""
    if value is None:
        raise ValueError("missing timestamp")
    if isinstance(value, bool):
        raise ValueError("boolean is not a timestamp")
    raw = str(value).strip()
    if not raw:
        raise ValueError("empty timestamp")
    try:
        number = Decimal(raw)
    except InvalidOperation:
        text = raw.replace("Z", "+00:00")
        fraction = re.search(r"(?<=\d{2}:\d{2}:\d{2})[.,](\d+)", text)
        ns_fraction = 0
        if fraction:
            digits = fraction.group(1)
            if len(digits) > 9:
                raise ValueError("timestamp precision exceeds nanoseconds")
            ns_fraction = int(digits.ljust(9, "0"))
            text = text[:fraction.start()] + text[fraction.end():]
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            raise ValueError("naive timestamp is not allowed; include timezone")
        delta = dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        result = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000 + ns_fraction
        if result <= 0:
            raise ValueError("timestamp must be positive")
        return result
    if not number.is_finite() or number <= 0:
        raise ValueError("timestamp must be positive and finite")
    magnitude = abs(number)
    if magnitude < 10_000_000_000:
        scale = 1_000_000_000
    elif magnitude < 10_000_000_000_000:
        scale = 1_000_000
    elif magnitude < 10_000_000_000_000_000:
        scale = 1_000
    elif magnitude < 10_000_000_000_000_000_000:
        scale = 1
    else:
        raise ValueError("timestamp magnitude is unsupported")
    result = number * scale
    if result != result.to_integral_value():
        raise ValueError("timestamp precision exceeds nanoseconds")
    return int(result)


def _float_or_none(value: object | None) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric market value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("numeric field must be finite")
    return result


def _explicit_side(value: object | None) -> Side:
    if value is None:
        return Side.UNKNOWN
    text = str(value).strip().upper()
    if text in {"B", "BUY", "ASK", "UP", "1", "+1"}:
        return Side.BUY
    if text in {"S", "SELL", "BID", "DOWN", "-1"}:
        return Side.SELL
    return Side.UNKNOWN


def normalize_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    default_symbol: str | None = None,
    source: str = "dxfeed_or_deepcharts_export",
    max_quote_age_seconds: float = 1.0,
) -> list[MarketEvent]:
    """Normalize loosely named dxFeed/DeepCharts CSV-like rows.

    Aggressor side precedence is explicit side, then quote matching, then tick
    rule, then UNKNOWN. Input order is preserved for monotonicity auditing.
    """
    if not math.isfinite(max_quote_age_seconds) or max_quote_age_seconds <= 0:
        raise ValueError("quote age must be positive and finite")
    out: list[MarketEvent] = []
    previous_trade: dict[str, tuple[int, float]] = {}
    previous_quote: dict[str, tuple[int, float | None, float | None]] = {}
    for row in rows:
        ts_ns = parse_timestamp_ns(_first(row, _TS_KEYS))
        symbol_value = _first(row, _SYMBOL_KEYS)
        symbol = str(symbol_value or default_symbol or "").strip()
        if not symbol:
            raise ValueError("missing symbol")
        kind_value = _first(row, _KIND_KEYS)
        price = _float_or_none(_first(row, _PRICE_KEYS))
        size = _float_or_none(_first(row, _SIZE_KEYS))
        bid = _float_or_none(_first(row, _BID_KEYS))
        ask = _float_or_none(_first(row, _ASK_KEYS))
        kind = str(kind_value or ("TRADE" if price is not None else "QUOTE")).upper()
        if kind not in {"TRADE", "TIMEANDSALE", "QUOTE"}:
            raise ValueError("unsupported event kind")
        is_trade = kind != "QUOTE"
        kind = "TRADE" if is_trade else "QUOTE"
        if is_trade and price is None:
            raise ValueError("trade row requires a price")
        if bid is not None and bid <= 0:
            raise ValueError("bid must be positive")
        if ask is not None and ask <= 0:
            raise ValueError("ask must be positive")
        if price is not None and price <= 0:
            raise ValueError("price must be positive")
        if size is not None and size < 0:
            raise ValueError("size must be non-negative")
        if not is_trade:
            prior = previous_quote.get(symbol)
            if prior is None or ts_ns >= prior[0]:
                # Invalid/incomplete updates invalidate the previous usable BBO.
                previous_quote[symbol] = (ts_ns, bid, ask)
        elif bid is None and ask is None:
            prior = previous_quote.get(symbol)
            if (prior is not None and 0 < ts_ns - prior[0] <= max_quote_age_seconds * 1_000_000_000
                    and prior[1] is not None and prior[2] is not None and prior[1] < prior[2]):
                _, bid, ask = prior
        side = _explicit_side(_first(row, _SIDE_KEYS))
        if not is_trade:
            side = Side.UNKNOWN
        side_source = "explicit" if side is not Side.UNKNOWN else "unknown"
        if is_trade and side is Side.UNKNOWN and price is not None:
            valid_bbo = bid is not None and ask is not None and bid < ask
            if valid_bbo and price >= ask:
                side, side_source = Side.BUY, "quote"
            elif valid_bbo and price <= bid:
                side, side_source = Side.SELL, "quote"
            else:
                prev = previous_trade.get(symbol)
                if prev is not None and prev[0] < ts_ns:
                    if price > prev[1]:
                        side, side_source = Side.BUY, "tick_rule"
                    elif price < prev[1]:
                        side, side_source = Side.SELL, "tick_rule"
        if is_trade and (symbol not in previous_trade or previous_trade[symbol][0] < ts_ns):
            previous_trade[symbol] = (ts_ns, price)
        out.append(MarketEvent(ts_ns, symbol, kind, price, size, bid, ask, side, side_source, source))
    return out


def load_export_csv(path: str | Path, *, default_symbol: str | None = None) -> list[MarketEvent]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return normalize_rows(csv.DictReader(handle), default_symbol=default_symbol)


def quality_report(
    events: Sequence[MarketEvent],
    policy: DataQualityPolicy = DataQualityPolicy(),
    *,
    now_ns: int | None = None,
) -> DataQualityReport:
    total = len(events)
    trades = [e for e in events if e.kind == "TRADE"]
    quotes = [e for e in events if e.kind == "QUOTE" or e.bid is not None or e.ask is not None]
    explicit = sum(e.side_source == "explicit" for e in trades)
    quote_inferred = sum(e.side_source == "quote" for e in trades)
    tick_rule = sum(e.side_source == "tick_rule" for e in trades)
    trade_bbo = sum(e.bid is not None and e.ask is not None for e in trades)
    classified = sum(e.side is not Side.UNKNOWN for e in trades)
    unknown = len(trades) - classified
    crossed = sum(e.bid is not None and e.ask is not None and e.bid > e.ask for e in quotes)
    keys = [(e.ts_ns, e.symbol, e.kind, e.price, e.size, e.bid, e.ask, e.side.value) for e in events]
    duplicate_fraction = 0.0 if not keys else 1 - len(set(keys)) / len(keys)
    monotonic = all(events[i].ts_ns <= events[i + 1].ts_ns for i in range(max(0, total - 1)))
    latest_age = None
    if events and now_ns is not None:
        latest_age = (now_ns - max(e.ts_ns for e in events)) / 1_000_000_000
    trade_count = len(trades)
    explicit_fraction = explicit / trade_count if trade_count else 0.0
    quote_inferred_fraction = quote_inferred / trade_count if trade_count else 0.0
    tick_rule_fraction = tick_rule / trade_count if trade_count else 0.0
    trade_bbo_fraction = trade_bbo / trade_count if trade_count else 0.0
    classified_fraction = classified / trade_count if trade_count else 0.0
    unknown_fraction = unknown / trade_count if trade_count else 0.0
    crossed_fraction = crossed / len(quotes) if quotes else 0.0
    failures: list[str] = []
    if any(e.kind == "QUOTE" and (e.bid is None or e.ask is None) for e in events):
        failures.append("incomplete_quote")
    if any(e.bid is not None and e.bid == e.ask for e in events):
        failures.append("locked_quote")
    if policy.require_trades and not trades:
        failures.append("no_trades")
    if latest_age is not None and latest_age < 0:
        failures.append("future_latest_event")
    if policy.max_latest_age_seconds is not None and latest_age is None:
        failures.append("missing_freshness_reference")
    if total < policy.min_events:
        failures.append(f"events<{policy.min_events}")
    if trade_count and unknown_fraction > policy.max_unknown_trade_side_fraction:
        failures.append("unknown_trade_side_fraction")
    if trade_count and tick_rule_fraction > policy.max_tick_rule_trade_fraction:
        failures.append("tick_rule_trade_fraction")
    if trade_count and explicit_fraction < policy.explicit_side_fraction_exempting_bbo and trade_bbo_fraction < policy.min_trade_bbo_fraction_when_explicit_side_low:
        failures.append("trade_bbo_fraction")
    if crossed_fraction > policy.max_crossed_quote_fraction:
        failures.append("crossed_quote_fraction")
    if duplicate_fraction > policy.max_duplicate_fraction:
        failures.append("duplicate_fraction")
    if policy.require_monotonic_timestamps and not monotonic:
        failures.append("non_monotonic_timestamps")
    if policy.max_latest_age_seconds is not None and latest_age is not None and latest_age > policy.max_latest_age_seconds:
        failures.append("stale_latest_event")
    return DataQualityReport(
        total, trade_count, len(quotes), explicit_fraction, quote_inferred_fraction,
        tick_rule_fraction, trade_bbo_fraction, classified_fraction, unknown_fraction,
        crossed_fraction, duplicate_fraction, monotonic, latest_age, not failures, tuple(failures)
    )

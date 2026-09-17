from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

from .adapters import normalize_dxfeed_rows
from .data import MarketEvent, Side, parse_timestamp_ns


_TS_KEYS = ("timestamp", "time", "datetime", "ts", "event_time", "eventtime")
_KIND_KEYS = ("kind", "event", "event_type", "type")
_BID_KEYS = ("bid", "bid_price", "bidprice")
_ASK_KEYS = ("ask", "ask_price", "askprice")
_BID_SIZE_KEYS = ("bid_size", "bidsize", "bid_qty", "bidqty", "bid_quantity", "bidquantity")
_ASK_SIZE_KEYS = ("ask_size", "asksize", "ask_qty", "askqty", "ask_quantity", "askquantity")
_SEQUENCE_KEYS = ("sequence", "seq", "event_sequence", "eventsequence")


def _lowered(row: Mapping[str, object]) -> dict[str, object]:
    return {str(k).strip().lower(): v for k, v in row.items()}


def _first(row: Mapping[str, object], keys: Sequence[str]) -> object | None:
    lowered = _lowered(row)
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def _float_or_none(value: object | None) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric market field")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("market field must be finite")
    return out


def _sequence(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("sequence must be an integer")
    out = int(value)
    if out < 0:
        raise ValueError("sequence must be non-negative")
    return out


def _is_quote_row(row: Mapping[str, object]) -> bool:
    raw = _first(row, _KIND_KEYS)
    if raw not in (None, ""):
        return str(raw).strip().upper() == "QUOTE"
    # Match the generic normalizer: rows without a trade price are quote rows.
    price = _first(row, ("price", "trade_price", "last", "last_price"))
    return price in (None, "")


@dataclass(frozen=True)
class QuoteState:
    ts_ns: int
    sequence: int | None
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    @property
    def microprice(self) -> float | None:
        total = self.bid_size + self.ask_size
        if total <= 0:
            return None
        return (self.ask * self.bid_size + self.bid * self.ask_size) / total

    @property
    def microprice_edge(self) -> float | None:
        micro = self.microprice
        spread = self.ask - self.bid
        if micro is None or spread <= 0:
            return None
        mid = (self.ask + self.bid) / 2.0
        return (micro - mid) / (spread / 2.0)

    @property
    def bbo_size_imbalance(self) -> float | None:
        total = self.bid_size + self.ask_size
        if total <= 0:
            return None
        return (self.bid_size - self.ask_size) / total


@dataclass(frozen=True)
class Level1BuildResult:
    rows: tuple[dict[str, object], ...]
    trade_rows: int
    quote_rows: int
    trades_with_size: int
    trades_with_classified_side: int
    trades_with_eligible_prior_bbo_sizes: int
    ambiguous_same_timestamp_bbo_uses_blocked: int

    @property
    def h1_eligible(self) -> bool:
        return self.trade_rows > 0 and self.trades_with_size == self.trade_rows and self.trades_with_classified_side == self.trade_rows

    @property
    def h3_eligible(self) -> bool:
        return self.trade_rows > 0 and self.trades_with_eligible_prior_bbo_sizes > 0


class _RollingFlow:
    def __init__(self, window_ns: int = 10_000_000_000) -> None:
        self.window_ns = int(window_ns)
        self.rows: deque[tuple[int, Side, float]] = deque()

    def add(self, ts_ns: int, side: Side, size: float) -> None:
        self.rows.append((ts_ns, side, size))
        cutoff = ts_ns - self.window_ns
        while self.rows and self.rows[0][0] < cutoff:
            self.rows.popleft()

    def snapshot(self, ts_ns: int) -> dict[str, float | int]:
        cutoff = ts_ns - self.window_ns
        while self.rows and self.rows[0][0] < cutoff:
            self.rows.popleft()
        buy = sum(size for _, side, size in self.rows if side == Side.BUY)
        sell = sum(size for _, side, size in self.rows if side == Side.SELL)
        return {
            "rolling_buy_volume": float(buy),
            "rolling_sell_volume": float(sell),
            "rolling_cvd": float(buy - sell),
            "rolling_trade_count": int(len(self.rows)),
        }


def _quote_from_row(row: Mapping[str, object]) -> QuoteState | None:
    if not _is_quote_row(row):
        return None
    ts_ns = parse_timestamp_ns(_first(row, _TS_KEYS))
    bid = _float_or_none(_first(row, _BID_KEYS))
    ask = _float_or_none(_first(row, _ASK_KEYS))
    bid_size = _float_or_none(_first(row, _BID_SIZE_KEYS))
    ask_size = _float_or_none(_first(row, _ASK_SIZE_KEYS))
    if None in (bid, ask, bid_size, ask_size):
        return None
    assert bid is not None and ask is not None and bid_size is not None and ask_size is not None
    if bid <= 0 or ask <= bid or bid_size < 0 or ask_size < 0:
        return None
    return QuoteState(ts_ns, _sequence(_first(row, _SEQUENCE_KEYS)), bid, ask, bid_size, ask_size)


def _state_eligible_for_trade(state: QuoteState | None, *, trade_ts_ns: int, trade_sequence: int | None) -> bool:
    if state is None:
        return False
    if state.ts_ns < trade_ts_ns:
        return True
    if state.ts_ns > trade_ts_ns:
        return False
    return state.sequence is not None and trade_sequence is not None and state.sequence < trade_sequence


def build_dxfeed_level1_feature_rows(
    source_rows: Iterable[Mapping[str, object]],
    *,
    default_symbol: str | None = None,
) -> Level1BuildResult:
    """Build causal H1/H3-ready rows from dxFeed/DeepCharts CSV-like rows.

    Quote state is reusable only from actual quote rows. Same-timestamp quote
    state can influence a trade only when both events carry sequence values that
    establish quote-before-trade order. Top-10 depth is deliberately not
    synthesized here, so CMF-H2 remains ineligible without a separate Level-2
    source/parser.
    """
    raw = [dict(row) for row in source_rows]
    events = normalize_dxfeed_rows(
        raw,
        default_symbol=default_symbol,
        reject_timestamp_regressions=True,
    ).events
    if len(events) != len(raw):
        raise ValueError("dxFeed normalization did not preserve one event per source row")

    quote_state: dict[str, QuoteState] = {}
    flows: dict[str, _RollingFlow] = {}
    output: list[dict[str, object]] = []
    trade_rows = quote_rows = trades_with_size = classified = trades_with_bbo = blocked = 0

    for source, event in zip(raw, events, strict=True):
        parsed_ts = parse_timestamp_ns(_first(source, _TS_KEYS))
        if parsed_ts != event.ts_ns:
            raise ValueError("source/event timestamp mismatch")
        seq = _sequence(_first(source, _SEQUENCE_KEYS))
        q = _quote_from_row(source)
        if event.kind == "QUOTE":
            quote_rows += 1
            if q is not None:
                prior = quote_state.get(event.symbol)
                if prior is None or q.ts_ns > prior.ts_ns or (
                    q.ts_ns == prior.ts_ns
                    and q.sequence is not None
                    and prior.sequence is not None
                    and q.sequence > prior.sequence
                ):
                    quote_state[event.symbol] = q
                output.append(
                    {
                        "event_type": "quote",
                        "symbol": event.symbol,
                        "observed_at_ns": event.ts_ns,
                        "sequence": q.sequence,
                        "best_bid": q.bid,
                        "best_ask": q.ask,
                        "best_bid_qty": q.bid_size,
                        "best_ask_qty": q.ask_size,
                        "microprice": q.microprice,
                        "microprice_edge": q.microprice_edge,
                        "bbo_size_imbalance_diagnostic": q.bbo_size_imbalance,
                    }
                )
            continue

        trade_rows += 1
        flow = flows.setdefault(event.symbol, _RollingFlow())
        size = event.size
        if size is not None:
            trades_with_size += 1
        if event.side != Side.UNKNOWN:
            classified += 1
        if size is not None and event.side != Side.UNKNOWN:
            flow.add(event.ts_ns, event.side, float(size))
        state = quote_state.get(event.symbol)
        state_ok = _state_eligible_for_trade(state, trade_ts_ns=event.ts_ns, trade_sequence=seq)
        if state is not None and state.ts_ns == event.ts_ns and not state_ok:
            blocked += 1
        if state_ok:
            trades_with_bbo += 1
        features = flow.snapshot(event.ts_ns)
        output.append(
            {
                "event_type": "trade",
                "symbol": event.symbol,
                "observed_at_ns": event.ts_ns,
                "sequence": seq,
                "trade_price": event.price,
                "trade_quantity": event.size,
                "aggressor_side": event.side.value,
                **features,
                "best_bid": state.bid if state_ok and state is not None else None,
                "best_ask": state.ask if state_ok and state is not None else None,
                "best_bid_qty": state.bid_size if state_ok and state is not None else None,
                "best_ask_qty": state.ask_size if state_ok and state is not None else None,
                "microprice": state.microprice if state_ok and state is not None else None,
                "microprice_edge": state.microprice_edge if state_ok and state is not None else None,
                "bbo_size_imbalance_diagnostic": state.bbo_size_imbalance if state_ok and state is not None else None,
                "book_imbalance_10": None,
            }
        )

    return Level1BuildResult(
        rows=tuple(output),
        trade_rows=trade_rows,
        quote_rows=quote_rows,
        trades_with_size=trades_with_size,
        trades_with_classified_side=classified,
        trades_with_eligible_prior_bbo_sizes=trades_with_bbo,
        ambiguous_same_timestamp_bbo_uses_blocked=blocked,
    )

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

from .data import parse_timestamp_ns


_TS_KEYS = ("timestamp", "time", "datetime", "ts", "event_time", "eventtime")
_SYMBOL_KEYS = ("symbol", "instrument", "ticker", "event_symbol", "eventsymbol")
_BID_KEYS = ("bid", "bid_price", "bidprice")
_ASK_KEYS = ("ask", "ask_price", "askprice")
_BID_SIZE_KEYS = ("bid_size", "bidsize", "bid_qty", "bidqty", "bid_quantity", "bidquantity")
_ASK_SIZE_KEYS = ("ask_size", "asksize", "ask_qty", "askqty", "ask_quantity", "askquantity")
_SEQUENCE_KEYS = ("sequence", "seq", "event_sequence", "eventsequence")


def _lowered(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key).strip().lower(): value for key, value in row.items()}


def _first(lowered: Mapping[str, object], keys: Sequence[str]) -> object | None:
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _optional_sequence(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("sequence must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("sequence must be an integer") from exc
    if result < 0:
        raise ValueError("sequence must be nonnegative")
    return result


@dataclass(frozen=True)
class BboSample:
    ts_ns: int
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    sequence: int | None = None

    def __post_init__(self) -> None:
        if type(self.ts_ns) is not int or self.ts_ns <= 0:
            raise ValueError("BBO timestamp must be a positive integer")
        if not self.symbol:
            raise ValueError("BBO symbol is required")
        values = (self.bid, self.ask, self.bid_size, self.ask_size)
        if not all(type(value) in (int, float) and math.isfinite(value) for value in values):
            raise ValueError("BBO numeric fields must be finite")
        if self.bid <= 0 or self.ask <= 0 or self.bid >= self.ask:
            raise ValueError("BBO must be positive and uncrossed")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("BBO sizes must be nonnegative")
        if self.sequence is not None and (type(self.sequence) is not int or self.sequence < 0):
            raise ValueError("BBO sequence must be nonnegative")


@dataclass(frozen=True)
class BboExtractionStats:
    rows_seen: int
    rows_with_bbo_prices: int
    complete_size_samples: int
    incomplete_size_rows: int
    locked_or_crossed_rows: int
    timestamp_regressions: int
    same_timestamp_ambiguous_rows: int

    @property
    def size_coverage_fraction(self) -> float:
        return self.complete_size_samples / self.rows_with_bbo_prices if self.rows_with_bbo_prices else 0.0


@dataclass(frozen=True)
class ExtractedBbo:
    samples: tuple[BboSample, ...]
    stats: BboExtractionStats


@dataclass(frozen=True)
class BboOfiEvent:
    ts_ns: int
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    bid_contribution: float
    ask_contribution: float
    ofi: float
    sequence: int | None = None


@dataclass(frozen=True)
class OfiStats:
    samples_seen: int
    ofi_events: int
    same_timestamp_ambiguous_samples: int
    timestamp_regressions: int


def extract_bbo_samples(
    rows: Iterable[Mapping[str, object]],
    *,
    default_symbol: str | None = None,
    reject_timestamp_regressions: bool = False,
) -> ExtractedBbo:
    """Extract BBO prices and sizes from dxFeed/DeepCharts-style rows.

    Input order is preserved. Rows with BBO prices but missing size fields are
    counted rather than synthesized. Locked/crossed quotes are rejected from the
    BBO stream. Equal timestamps are accepted only when a sequence field exists
    and increases for the same symbol; otherwise the later row is considered
    causally ambiguous and omitted.
    """
    samples: list[BboSample] = []
    rows_seen = rows_with_bbo = complete = incomplete = crossed = regressions = ambiguous = 0
    previous_global_ts: int | None = None
    previous_key: dict[str, tuple[int, int | None]] = {}

    for row in rows:
        rows_seen += 1
        lowered = _lowered(row)
        bid_raw = _first(lowered, _BID_KEYS)
        ask_raw = _first(lowered, _ASK_KEYS)
        if bid_raw in (None, "") or ask_raw in (None, ""):
            continue
        rows_with_bbo += 1
        ts_ns = parse_timestamp_ns(_first(lowered, _TS_KEYS))
        if previous_global_ts is not None and ts_ns < previous_global_ts:
            regressions += 1
            if reject_timestamp_regressions:
                raise ValueError(
                    f"source timestamp regression: ts_ns={ts_ns} follows ts_ns={previous_global_ts}"
                )
        previous_global_ts = ts_ns

        symbol_value = _first(lowered, _SYMBOL_KEYS)
        symbol = str(symbol_value or default_symbol or "").strip()
        if not symbol:
            raise ValueError("missing symbol on BBO row")
        bid = _finite_float(bid_raw, "bid")
        ask = _finite_float(ask_raw, "ask")
        if bid <= 0 or ask <= 0 or bid >= ask:
            crossed += 1
            continue

        bid_size_raw = _first(lowered, _BID_SIZE_KEYS)
        ask_size_raw = _first(lowered, _ASK_SIZE_KEYS)
        if bid_size_raw in (None, "") or ask_size_raw in (None, ""):
            incomplete += 1
            continue
        bid_size = _finite_float(bid_size_raw, "bid_size")
        ask_size = _finite_float(ask_size_raw, "ask_size")
        if bid_size < 0 or ask_size < 0:
            raise ValueError("BBO sizes must be nonnegative")
        sequence = _optional_sequence(_first(lowered, _SEQUENCE_KEYS))

        prior = previous_key.get(symbol)
        if prior is not None:
            prior_ts, prior_seq = prior
            if ts_ns < prior_ts:
                if reject_timestamp_regressions:
                    raise ValueError(f"symbol timestamp regression for {symbol}")
                regressions += 1
                continue
            if ts_ns == prior_ts:
                if sequence is None or prior_seq is None or sequence <= prior_seq:
                    ambiguous += 1
                    continue
        previous_key[symbol] = (ts_ns, sequence)
        samples.append(BboSample(ts_ns, symbol, bid, ask, bid_size, ask_size, sequence))
        complete += 1

    return ExtractedBbo(
        samples=tuple(samples),
        stats=BboExtractionStats(
            rows_seen=rows_seen,
            rows_with_bbo_prices=rows_with_bbo,
            complete_size_samples=complete,
            incomplete_size_rows=incomplete,
            locked_or_crossed_rows=crossed,
            timestamp_regressions=regressions,
            same_timestamp_ambiguous_rows=ambiguous,
        ),
    )


def compute_bbo_ofi(samples: Iterable[BboSample]) -> tuple[tuple[BboOfiEvent, ...], OfiStats]:
    """Compute causal best-level order-flow imbalance from BBO changes.

    This is the standard best-level OFI accounting identity. It measures changes
    in displayed best-bid and best-ask queue sizes and prices. It is not market-by-
    order reconstruction and it must not be interpreted as executed volume.
    """
    previous: dict[str, BboSample] = {}
    output: list[BboOfiEvent] = []
    seen = ambiguous = regressions = 0

    for sample in samples:
        seen += 1
        prior = previous.get(sample.symbol)
        if prior is None:
            previous[sample.symbol] = sample
            continue
        if sample.ts_ns < prior.ts_ns:
            regressions += 1
            continue
        if sample.ts_ns == prior.ts_ns:
            if sample.sequence is None or prior.sequence is None or sample.sequence <= prior.sequence:
                ambiguous += 1
                continue

        bid_contribution = 0.0
        if sample.bid >= prior.bid:
            bid_contribution += sample.bid_size
        if sample.bid <= prior.bid:
            bid_contribution -= prior.bid_size

        ask_contribution = 0.0
        if sample.ask <= prior.ask:
            ask_contribution -= sample.ask_size
        if sample.ask >= prior.ask:
            ask_contribution += prior.ask_size

        ofi = bid_contribution + ask_contribution
        output.append(
            BboOfiEvent(
                ts_ns=sample.ts_ns,
                symbol=sample.symbol,
                bid=sample.bid,
                ask=sample.ask,
                bid_size=sample.bid_size,
                ask_size=sample.ask_size,
                bid_contribution=bid_contribution,
                ask_contribution=ask_contribution,
                ofi=ofi,
                sequence=sample.sequence,
            )
        )
        previous[sample.symbol] = sample

    return tuple(output), OfiStats(seen, len(output), ambiguous, regressions)

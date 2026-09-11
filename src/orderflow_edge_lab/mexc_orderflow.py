from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .data import Side


FEATURE_SCHEMA_VERSION = 2


class MexcOrderFlowError(ValueError):
    """Raised when MEXC market data cannot be used safely."""


class SequenceGapError(MexcOrderFlowError):
    """Raised when an incremental depth range does not cover the next version."""

    def __init__(self, expected: int, received_begin: int, received_end: int | None = None) -> None:
        self.expected = expected
        self.received_begin = received_begin
        self.received_end = received_begin if received_end is None else received_end
        # Backward-compatible attribute used by earlier callers.
        self.received = self.received_end
        super().__init__(
            f"depth sequence gap: expected {expected}, received range "
            f"{self.received_begin}..{self.received_end}"
        )


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise MexcOrderFlowError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MexcOrderFlowError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise MexcOrderFlowError(f"{field} must be finite")
    return result


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise MexcOrderFlowError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MexcOrderFlowError(f"{field} must be an integer") from exc
    if result <= 0:
        raise MexcOrderFlowError(f"{field} must be positive")
    return result


def _nonnegative_integral(value: object, field: str) -> int:
    number = _decimal(value, field)
    if number < 0 or number != number.to_integral_value():
        raise MexcOrderFlowError(f"{field} must be a nonnegative integer")
    return int(number)


def _level_rows(value: object, field: str) -> tuple[tuple[Decimal, Decimal, int], ...]:
    """Parse MEXC depth rows as [price, contract volume, order count]."""
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MexcOrderFlowError(f"{field} must be a list of levels")
    out: list[tuple[Decimal, Decimal, int]] = []
    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes, bytearray)) or len(row) < 3:
            raise MexcOrderFlowError(
                f"{field} level must contain price, contract volume, order count"
            )
        price = _decimal(row[0], f"{field}.price")
        volume = _decimal(row[1], f"{field}.contract_volume")
        order_count = _nonnegative_integral(row[2], f"{field}.order_count")
        if price <= 0 or volume < 0:
            raise MexcOrderFlowError(f"{field} level contains an out-of-range value")
        out.append((price, volume, order_count))
    return tuple(out)


def _response_data(payload: Mapping[str, Any], *, expect_list: bool = False) -> Any:
    if payload.get("success") is not True or payload.get("code") not in (0, None):
        raise MexcOrderFlowError("MEXC response did not report success")
    data = payload.get("data")
    expected = list if expect_list else Mapping
    if not isinstance(data, expected):
        raise MexcOrderFlowError("MEXC response data has an unexpected shape")
    return data


def depth_version_range(data: Mapping[str, Any]) -> tuple[int, int, int]:
    """Return (begin, end, version), validating merged-range metadata when present."""
    version = _positive_int(data.get("version"), "depth.version")
    has_begin = data.get("begin") is not None
    has_end = data.get("end") is not None
    if has_begin != has_end:
        raise MexcOrderFlowError("depth range must contain both begin and end")
    if not has_begin:
        return version, version, version

    begin = _positive_int(data.get("begin"), "depth.begin")
    end = _positive_int(data.get("end"), "depth.end")
    if begin > end:
        raise MexcOrderFlowError("depth begin cannot exceed depth end")
    if version != end:
        raise MexcOrderFlowError("depth version must equal depth end for a ranged update")
    return begin, end, version


@dataclass(frozen=True)
class TradePrint:
    symbol: str
    trade_id: str | None
    ts_ms: int
    cts_ms: int | None
    price: Decimal
    quantity: Decimal
    side: Side
    open_close_flag: int | None
    exchange_m_flag: int | None

    @classmethod
    def from_ws(cls, symbol: str, row: Mapping[str, Any]) -> "TradePrint":
        if not symbol:
            raise MexcOrderFlowError("trade symbol is required")
        side_code = int(row.get("T", 0))
        if side_code == 1:
            side = Side.BUY
        elif side_code == 2:
            side = Side.SELL
        else:
            raise MexcOrderFlowError("unsupported MEXC trade side")
        price = _decimal(row.get("p"), "trade.price")
        quantity = _decimal(row.get("v"), "trade.quantity")
        if price <= 0 or quantity < 0:
            raise MexcOrderFlowError("trade price/quantity is out of range")
        ts_ms = _positive_int(row.get("t"), "trade.t")
        cts_raw = row.get("cts")
        cts_ms = None if cts_raw is None else _positive_int(cts_raw, "trade.cts")
        trade_id_raw = row.get("i")
        trade_id = None if trade_id_raw in (None, "") else str(trade_id_raw)
        oc = row.get("O")
        m_flag = row.get("M")
        return cls(
            symbol=symbol,
            trade_id=trade_id,
            ts_ms=ts_ms,
            cts_ms=cts_ms,
            price=price,
            quantity=quantity,
            side=side,
            open_close_flag=None if oc is None else int(oc),
            exchange_m_flag=None if m_flag is None else int(m_flag),
        )


@dataclass(frozen=True)
class DepthDelta:
    version: int
    begin_version: int
    end_version: int
    applied: bool
    bid_added: Decimal = Decimal("0")
    bid_pulled: Decimal = Decimal("0")
    ask_added: Decimal = Decimal("0")
    ask_pulled: Decimal = Decimal("0")

    @property
    def range_span(self) -> int:
        return self.end_version - self.begin_version + 1

    @property
    def merged_range(self) -> bool:
        return self.range_span > 1

    @property
    def depth_flow_imbalance(self) -> Decimal:
        bid_net = self.bid_added - self.bid_pulled
        ask_net = self.ask_added - self.ask_pulled
        return bid_net - ask_net


class OrderBook:
    """Price-level MEXC futures book using absolute contract volumes."""

    def __init__(self, symbol: str) -> None:
        if not symbol:
            raise ValueError("symbol is required")
        self.symbol = symbol
        self.version: int | None = None
        self.timestamp_ms: int | None = None
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}

    @staticmethod
    def _apply_levels(
        book: dict[Decimal, Decimal],
        rows: Iterable[tuple[Decimal, Decimal, int]],
    ) -> tuple[Decimal, Decimal]:
        added = Decimal("0")
        pulled = Decimal("0")
        for price, volume, _order_count in rows:
            old = book.get(price, Decimal("0"))
            if volume == 0:
                if old > 0:
                    pulled += old
                    book.pop(price, None)
                continue
            if volume > old:
                added += volume - old
            elif volume < old:
                pulled += old - volume
            book[price] = volume
        return added, pulled

    @staticmethod
    def _validate_uncrossed(
        bids: Mapping[Decimal, Decimal],
        asks: Mapping[Decimal, Decimal],
    ) -> None:
        if bids and asks and max(bids) >= min(asks):
            raise MexcOrderFlowError("reconstructed order book is locked or crossed")

    def load_snapshot(self, payload: Mapping[str, Any]) -> None:
        data: Mapping[str, Any]
        if "success" in payload or "code" in payload:
            data = _response_data(payload)
        else:
            data = payload
        version = _positive_int(data.get("version"), "depth.version")
        bids: dict[Decimal, Decimal] = {}
        asks: dict[Decimal, Decimal] = {}
        self._apply_levels(bids, _level_rows(data.get("bids", []), "depth.bids"))
        self._apply_levels(asks, _level_rows(data.get("asks", []), "depth.asks"))
        self._validate_uncrossed(bids, asks)
        timestamp = data.get("timestamp")
        self.bids = bids
        self.asks = asks
        self.version = version
        self.timestamp_ms = (
            None if timestamp is None else _positive_int(timestamp, "depth.timestamp")
        )

    def apply_update(
        self,
        data: Mapping[str, Any],
        *,
        require_contiguous: bool = True,
    ) -> DepthDelta:
        begin, end, version = depth_version_range(data)
        if self.version is None:
            raise MexcOrderFlowError("depth snapshot is required before incremental updates")

        if end <= self.version:
            return DepthDelta(
                version=version,
                begin_version=begin,
                end_version=end,
                applied=False,
            )

        expected = self.version + 1
        if require_contiguous and not (begin <= expected <= end):
            raise SequenceGapError(expected, begin, end)

        bids = dict(self.bids)
        asks = dict(self.asks)
        bid_added, bid_pulled = self._apply_levels(
            bids, _level_rows(data.get("bids", []), "depth.bids")
        )
        ask_added, ask_pulled = self._apply_levels(
            asks, _level_rows(data.get("asks", []), "depth.asks")
        )
        self._validate_uncrossed(bids, asks)

        self.bids = bids
        self.asks = asks
        self.version = end
        cts = data.get("cts")
        if cts is not None:
            self.timestamp_ms = _positive_int(cts, "depth.cts")
        return DepthDelta(
            version=version,
            begin_version=begin,
            end_version=end,
            applied=True,
            bid_added=bid_added,
            bid_pulled=bid_pulled,
            ask_added=ask_added,
            ask_pulled=ask_pulled,
        )

    def best_bid(self) -> tuple[Decimal, Decimal] | None:
        if not self.bids:
            return None
        price = max(self.bids)
        return price, self.bids[price]

    def best_ask(self) -> tuple[Decimal, Decimal] | None:
        if not self.asks:
            return None
        price = min(self.asks)
        return price, self.asks[price]

    def spread(self) -> Decimal | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return ask[0] - bid[0]

    def microprice(self) -> Decimal | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        total = bid[1] + ask[1]
        if total <= 0:
            return None
        return (ask[0] * bid[1] + bid[0] * ask[1]) / total

    def imbalance(self, levels: int = 10) -> Decimal | None:
        if levels < 1:
            raise ValueError("levels must be >= 1")
        bid_volume = sum(
            (self.bids[p] for p in sorted(self.bids, reverse=True)[:levels]),
            Decimal("0"),
        )
        ask_volume = sum(
            (self.asks[p] for p in sorted(self.asks)[:levels]),
            Decimal("0"),
        )
        total = bid_volume + ask_volume
        if total <= 0:
            return None
        return (bid_volume - ask_volume) / total


class RollingTradeFlow:
    """Causal rolling aggressive-trade metrics for one symbol."""

    def __init__(self, symbol: str, window_ms: int = 10_000) -> None:
        if not symbol or window_ms <= 0:
            raise ValueError("symbol and positive window_ms are required")
        self.symbol = symbol
        self.window_ms = window_ms
        self._trades: deque[TradePrint] = deque()
        self._last_ts_ms: int | None = None

    def add(self, trade: TradePrint) -> None:
        if trade.symbol != self.symbol:
            raise MexcOrderFlowError("trade symbol does not match rolling flow")
        if self._last_ts_ms is not None and trade.ts_ms < self._last_ts_ms:
            raise MexcOrderFlowError("trade timestamp regression")
        self._last_ts_ms = trade.ts_ms
        self._trades.append(trade)
        self._prune(trade.ts_ms)

    def _prune(self, now_ms: int) -> None:
        cutoff = now_ms - self.window_ms
        while self._trades and self._trades[0].ts_ms < cutoff:
            self._trades.popleft()

    def features(self, now_ms: int | None = None) -> dict[str, float | int]:
        if now_ms is not None:
            self._prune(now_ms)
        buy = sum(
            (t.quantity for t in self._trades if t.side == Side.BUY),
            Decimal("0"),
        )
        sell = sum(
            (t.quantity for t in self._trades if t.side == Side.SELL),
            Decimal("0"),
        )
        count = len(self._trades)
        seconds = self.window_ms / 1000.0
        return {
            "rolling_buy_volume": float(buy),
            "rolling_sell_volume": float(sell),
            "rolling_cvd": float(buy - sell),
            "rolling_trade_count": count,
            "trade_velocity_per_second": count / seconds,
        }


class FeatureEngine:
    """Derive causal price-level order-flow features from MEXC public data."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        trade_window_ms: int = 10_000,
        imbalance_levels: int = 10,
    ) -> None:
        unique = tuple(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))
        if not unique:
            raise ValueError("at least one symbol is required")
        if imbalance_levels < 1:
            raise ValueError("imbalance_levels must be >= 1")
        self.books = {symbol: OrderBook(symbol) for symbol in unique}
        self.flows = {
            symbol: RollingTradeFlow(symbol, trade_window_ms) for symbol in unique
        }
        self.depth_stats = {
            symbol: {
                "depth_messages_seen": 0,
                "compressed_depth_ranges_seen": 0,
                "true_depth_gaps_seen": 0,
                "stale_depth_messages_seen": 0,
            }
            for symbol in unique
        }
        self.imbalance_levels = imbalance_levels

    def _book_fields(self, symbol: str) -> dict[str, float | int | None]:
        book = self.books[symbol]
        bid = book.best_bid()
        ask = book.best_ask()
        imbalance = book.imbalance(self.imbalance_levels)
        spread = book.spread()
        microprice = book.microprice()
        return {
            "book_version": book.version,
            "best_bid": None if bid is None else float(bid[0]),
            "best_bid_qty": None if bid is None else float(bid[1]),
            "best_bid_contract_volume": None if bid is None else float(bid[1]),
            "best_ask": None if ask is None else float(ask[0]),
            "best_ask_qty": None if ask is None else float(ask[1]),
            "best_ask_contract_volume": None if ask is None else float(ask[1]),
            "spread": None if spread is None else float(spread),
            "microprice": None if microprice is None else float(microprice),
            f"book_imbalance_{self.imbalance_levels}": (
                None if imbalance is None else float(imbalance)
            ),
        }

    def _depth_stat_fields(self, symbol: str) -> dict[str, int]:
        return dict(self.depth_stats[symbol])

    def depth_stats_snapshot(self) -> dict[str, dict[str, int]]:
        return {symbol: dict(values) for symbol, values in self.depth_stats.items()}

    def load_snapshot(self, symbol: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        book = self.books[symbol]
        book.load_snapshot(payload)
        return {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "event_type": "snapshot",
            "symbol": symbol,
            **self._book_fields(symbol),
            **self._depth_stat_fields(symbol),
        }

    def on_depth(
        self,
        symbol: str,
        data: Mapping[str, Any],
        *,
        observed: bool = True,
    ) -> dict[str, Any]:
        stats = self.depth_stats[symbol]
        begin, end, _version = depth_version_range(data)
        if observed:
            stats["depth_messages_seen"] += 1
            if end > begin:
                stats["compressed_depth_ranges_seen"] += 1

        book = self.books[symbol]
        try:
            delta = book.apply_update(data)
        except SequenceGapError:
            if observed:
                stats["true_depth_gaps_seen"] += 1
            raise

        if observed and not delta.applied:
            stats["stale_depth_messages_seen"] += 1

        return {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "event_type": "depth",
            "symbol": symbol,
            "exchange_ts_ms": data.get("cts"),
            "depth_applied": delta.applied,
            "depth_begin_version": delta.begin_version,
            "depth_end_version": delta.end_version,
            "depth_range_span": delta.range_span,
            "depth_merged_range": delta.merged_range,
            "bid_liquidity_added": float(delta.bid_added),
            "bid_liquidity_pulled": float(delta.bid_pulled),
            "ask_liquidity_added": float(delta.ask_added),
            "ask_liquidity_pulled": float(delta.ask_pulled),
            "depth_flow_imbalance": float(delta.depth_flow_imbalance),
            **self._book_fields(symbol),
            **self._depth_stat_fields(symbol),
        }

    def on_deals(self, symbol: str, rows: object) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            raise MexcOrderFlowError("push.deal data must be a list")
        trades = [
            TradePrint.from_ws(symbol, row)
            for row in rows
            if isinstance(row, Mapping)
        ]
        if len(trades) != len(rows):
            raise MexcOrderFlowError("push.deal contains a malformed trade row")
        trades.sort(key=lambda t: (t.ts_ms, t.trade_id or ""))
        out: list[dict[str, Any]] = []
        flow = self.flows[symbol]
        for trade in trades:
            flow.add(trade)
            out.append(
                {
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "event_type": "trade",
                    "symbol": symbol,
                    "exchange_ts_ms": trade.ts_ms,
                    "matching_engine_ts_ms": trade.cts_ms,
                    "trade_id": trade.trade_id,
                    "trade_price": float(trade.price),
                    "trade_quantity": float(trade.quantity),
                    "aggressor_side": trade.side.value,
                    "open_close_flag": trade.open_close_flag,
                    # MEXC's REST and WebSocket documentation use different labels
                    # for M. Preserve the exchange value without over-interpreting it.
                    "exchange_m_flag": trade.exchange_m_flag,
                    **flow.features(trade.ts_ms),
                    **self._book_fields(symbol),
                    **self._depth_stat_fields(symbol),
                }
            )
        return out


def apply_recovery_commits(
    book: OrderBook,
    payload: Mapping[str, Any],
    *,
    stop_version: int | None = None,
) -> int:
    """Apply contiguous recovery commits in ascending version order."""
    commits = _response_data(payload, expect_list=True)
    parsed = [row for row in commits if isinstance(row, Mapping)]
    if len(parsed) != len(commits):
        raise MexcOrderFlowError("depth commit response contains a malformed row")
    parsed.sort(key=lambda row: _positive_int(row.get("version"), "depth.version"))
    applied = 0
    for row in parsed:
        version = _positive_int(row.get("version"), "depth.version")
        if stop_version is not None and version > stop_version:
            break
        if book.version is not None and version <= book.version:
            continue
        if book.version is None:
            raise MexcOrderFlowError("snapshot is required before recovery commits")
        if version != book.version + 1:
            continue
        delta = book.apply_update(row)
        if delta.applied:
            applied += 1
    return applied


def decode_ws_message(raw: str | bytes) -> Mapping[str, Any]:
    if isinstance(raw, bytes):
        try:
            text = gzip.decompress(raw).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MexcOrderFlowError(
                    "websocket frame is not valid UTF-8 or gzip JSON"
                ) from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise MexcOrderFlowError("unsupported websocket frame type")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MexcOrderFlowError("websocket frame is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise MexcOrderFlowError("websocket JSON must be an object")
    return payload


class AppendOnlyJsonl:
    """Exclusive-create JSONL writer with a SHA-256 sidecar on clean close."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("x", encoding="utf-8", newline="\n")
        self._closed = False

    def write(self, record: Mapping[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("writer is closed")
        self._fh.write(
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
        self._fh.flush()

    def close(self) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("writer is already closed")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        self._closed = True
        raw = self.path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        manifest = {
            "schema_version": 1,
            "path": self.path.name,
            "bytes": len(raw),
            "sha256": digest,
            "closed_at_ns": time.time_ns(),
        }
        manifest_path = self.path.with_name(self.path.name + ".manifest.json")
        with manifest_path.open("x", encoding="utf-8", newline="\n") as fh:
            json.dump(
                manifest,
                fh,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            fh.write("\n")
        return manifest

    def __enter__(self) -> "AppendOnlyJsonl":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if not self._closed:
            self.close()


def iter_jsonl(path: str | Path) -> Iterator[Mapping[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MexcOrderFlowError(
                    f"invalid JSONL at line {line_number}"
                ) from exc
            if not isinstance(record, Mapping):
                raise MexcOrderFlowError(
                    f"JSONL line {line_number} is not an object"
                )
            yield record

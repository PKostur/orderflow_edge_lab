from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable, Mapping

from .data import MarketEvent, Side, normalize_rows


@dataclass(frozen=True)
class AdapterStats:
    total_events: int
    trade_events: int
    quote_events: int
    trades_with_bbo: int
    trades_enriched_from_prior_bbo: int
    trades_quote_classified: int
    stale_prior_quotes_ignored: int
    future_prior_quotes_ignored: int
    crossed_quotes_ignored: int
    same_timestamp_quotes_ignored: int = 0
    timestamp_regressions: int = 0

    @property
    def trade_bbo_fraction(self) -> float:
        return self.trades_with_bbo / self.trade_events if self.trade_events else 0.0


@dataclass(frozen=True)
class AdaptedEvents:
    events: tuple[MarketEvent, ...]
    stats: AdapterStats


def attach_prior_bbo(
    events: Iterable[MarketEvent],
    *,
    max_quote_age_seconds: float = 2.0,
    reject_timestamp_regressions: bool = False,
) -> AdaptedEvents:
    """Attach the most recent causal BBO to trade events.

    Input order is preserved. A cached quote is eligible only when it appeared
    earlier in the input, is timestamped strictly before the trade, is not locked or crossed,
    and is no older than ``max_quote_age_seconds``. This intentionally avoids
    sorting because sorting an export can hide source-order defects and can
    introduce accidental lookahead during replay.

    Timestamp regressions are counted across the raw input stream. Set
    ``reject_timestamp_regressions`` to fail closed when a source export is not
    globally chronological instead of merely reporting the defect in stats.
    """
    if not isinstance(max_quote_age_seconds, (int, float)) or isinstance(max_quote_age_seconds, bool):
        raise ValueError("max_quote_age_seconds must be a finite positive number")
    if not math.isfinite(max_quote_age_seconds) or max_quote_age_seconds <= 0:
        raise ValueError("max_quote_age_seconds must be a finite positive number")
    if not isinstance(reject_timestamp_regressions, bool):
        raise ValueError("reject_timestamp_regressions must be a bool")

    max_age_ns = int(max_quote_age_seconds * 1_000_000_000)
    last_bbo: dict[str, tuple[int, float | None, float | None]] = {}
    output: list[MarketEvent] = []
    trades = quotes = with_bbo = enriched = quote_classified = 0
    stale_ignored = future_ignored = crossed_ignored = 0
    same_time_ignored = timestamp_regressions = 0
    previous_ts_ns: int | None = None

    for event in events:
        if previous_ts_ns is not None and event.ts_ns < previous_ts_ns:
            timestamp_regressions += 1
            if reject_timestamp_regressions:
                raise ValueError(
                    "source timestamp regression: "
                    f"event ts_ns={event.ts_ns} follows ts_ns={previous_ts_ns}"
                )
        previous_ts_ns = event.ts_ns

        is_full_quote = event.bid is not None and event.ask is not None
        if event.kind == "QUOTE" or is_full_quote:
            quotes += 1
            prior = last_bbo.get(event.symbol)
            if prior is None or event.ts_ns >= prior[0]:
                # Invalid updates invalidate old BBOs rather than reviving them.
                last_bbo[event.symbol] = (event.ts_ns, event.bid, event.ask)
            if is_full_quote and event.bid > event.ask:
                crossed_ignored += 1

        if event.kind != "TRADE":
            output.append(event)
            continue

        trades += 1
        bid, ask = event.bid, event.ask
        used_prior = False

        if bid is None and ask is None:
            cached = last_bbo.get(event.symbol)
            if cached is not None:
                quote_ts, quote_bid, quote_ask = cached
                age_ns = event.ts_ns - quote_ts
                if age_ns < 0:
                    future_ignored += 1
                elif age_ns == 0:
                    same_time_ignored += 1
                elif age_ns > max_age_ns:
                    stale_ignored += 1
                elif quote_bid is not None and quote_ask is not None and quote_bid < quote_ask:
                    bid, ask = quote_bid, quote_ask
                    used_prior = True

        side = event.side
        side_source = event.side_source
        if side_source != "explicit" and event.price is not None and bid is not None and ask is not None and bid < ask:
            if event.price >= ask:
                side, side_source = Side.BUY, "quote"
                quote_classified += 1
            elif event.price <= bid:
                side, side_source = Side.SELL, "quote"
                quote_classified += 1

        if bid is not None and ask is not None:
            with_bbo += 1
        if used_prior:
            enriched += 1

        output.append(replace(event, bid=bid, ask=ask, side=side, side_source=side_source))

    return AdaptedEvents(
        events=tuple(output),
        stats=AdapterStats(
            total_events=len(output),
            trade_events=trades,
            quote_events=quotes,
            trades_with_bbo=with_bbo,
            trades_enriched_from_prior_bbo=enriched,
            trades_quote_classified=quote_classified,
            stale_prior_quotes_ignored=stale_ignored,
            future_prior_quotes_ignored=future_ignored,
            crossed_quotes_ignored=crossed_ignored,
            same_timestamp_quotes_ignored=same_time_ignored,
            timestamp_regressions=timestamp_regressions,
        ),
    )


def normalize_dxfeed_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    default_symbol: str | None = None,
    source: str = "dxfeed_or_deepcharts_export",
    max_quote_age_seconds: float = 2.0,
    reject_timestamp_regressions: bool = False,
) -> AdaptedEvents:
    """Normalize dxFeed/DeepCharts rows and causally enrich trades with prior BBO."""
    normalized = normalize_rows(rows, default_symbol=default_symbol, source=source, enrich_prior_bbo=False)
    return attach_prior_bbo(
        normalized,
        max_quote_age_seconds=max_quote_age_seconds,
        reject_timestamp_regressions=reject_timestamp_regressions,
    )

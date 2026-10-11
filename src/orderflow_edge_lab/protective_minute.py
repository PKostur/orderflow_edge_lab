"""Offline engineering primitives for hypothetical long Spot protective orders.

No signals, market data retrieval, exchange orders or promotion are implemented.
Minute OHLC touch fills are model assumptions, not executable-price guarantees.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import math


def _positive(*values: float) -> None:
    if any(not math.isfinite(x) or x <= 0 for x in values):
        raise ValueError("finite positive values required")


def _time(value: int) -> None:
    if type(value) is not int or value < 0 or value % 60:
        raise ValueError("nonnegative integer UTC minute epoch required")


def _cost(value: float) -> None:
    if not math.isfinite(value) or not 0 <= value < 10000:
        raise ValueError("cost must be finite and in [0,10000) bps")


def _finite_result(*values: float) -> None:
    if any(not math.isfinite(x) for x in values):
        raise ValueError("calculation exceeds finite numeric range")


@dataclass(frozen=True)
class Minute:
    opened_at: int
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        _time(self.opened_at)
        _positive(self.open, self.high, self.low, self.close)
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("inconsistent OHLC")


@dataclass(frozen=True)
class Bracket:
    stop: float
    target: float
    decided_at: int
    active_from: int

    def __post_init__(self) -> None:
        _positive(self.stop, self.target)
        _time(self.decided_at)
        _time(self.active_from)
        if self.stop >= self.target or self.active_from < self.decided_at:
            raise ValueError("ordered levels and causal activation required")


@dataclass(frozen=True)
class ExitBounds:
    minute: int
    lower_price: float
    upper_price: float
    reason: str
    at_open: bool

    def __post_init__(self) -> None:
        _time(self.minute)
        _positive(self.lower_price, self.upper_price)
        if self.lower_price > self.upper_price:
            raise ValueError("inverted exit bounds")

    @property
    def time_interval(self) -> tuple[int, int]:
        """Point at open, otherwise half-open minute interval, never invented ticks."""
        return (self.minute, self.minute if self.at_open else self.minute + 60)


def resolve_minute(bar: Minute, bracket: Bracket, *, market_exit_decided_at: int | None = None) -> ExitBounds | None:
    """Hypothetical open/gap/touch resolution; both-touch keeps adverse/favorable bounds.

    A previously scheduled market close resolves at the open before range touches.
    A stop crossing an open gap references that open. A target gap retains the
    target as a conservative fill and open as price-improvement sensitivity. An
    inactive bracket cannot use any extrema preceding its activation boundary.
    Order activation is minute aligned; subminute activation is unsupported.
    """
    if market_exit_decided_at is not None:
        _time(market_exit_decided_at)
        if market_exit_decided_at > bar.opened_at:
            raise ValueError("future market close decision")
        return ExitBounds(bar.opened_at, bar.open, bar.open, "scheduled_market", True)
    if bracket.active_from > bar.opened_at:
        return None
    if bar.open <= bracket.stop:
        return ExitBounds(bar.opened_at, bar.open, bar.open, "stop_gap", True)
    if bar.open >= bracket.target:
        return ExitBounds(bar.opened_at, bracket.target, bar.open, "target_gap", True)
    stop, target = bar.low <= bracket.stop, bar.high >= bracket.target
    if stop and target:
        return ExitBounds(bar.opened_at, bracket.stop, bracket.target, "both_touched_order_unknown", False)
    if stop:
        return ExitBounds(bar.opened_at, bracket.stop, bracket.stop, "stop_touch", False)
    if target:
        return ExitBounds(bar.opened_at, bracket.target, bracket.target, "target_touch", False)
    return None


def replace_bracket(previous: Bracket, replacement: Bracket, *, last_processed_minute: int) -> Bracket:
    """Install a completed-minute decision; never apply it to processed ranges."""
    _time(last_processed_minute)
    if (replacement.decided_at < last_processed_minute + 60
            or replacement.decided_at < previous.decided_at
            or replacement.active_from < last_processed_minute + 60):
        raise ValueError("retroactive bracket replacement")
    return replacement


def fixed_risk_quantity(cash: float, signal_price: float, stop: float, *, risk_fraction: float = .03,
                        reserve_side_bps: float = 20) -> float:
    """Cash-capped base quantity frozen at signal close, rounded down to 8 decimals.

    Fee/friction reserve is an explicit adaptation. No exchange lot/min-notional
    validation or fill-price resizing is implied by decimal precision.
    """
    _positive(cash, signal_price, stop, risk_fraction)
    _cost(reserve_side_bps)
    if stop >= signal_price or risk_fraction > 1:
        raise ValueError("long risk sizing requires stop below signal and risk <= 1")
    quantity = min(cash * risk_fraction / (signal_price - stop),
                   cash / (signal_price * (1 + reserve_side_bps / 10000)))
    _finite_result(quantity)
    return float(Decimal(str(quantity)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))


@dataclass(frozen=True)
class BuySettlement:
    accepted: bool
    quantity: float
    reference_price: float
    charged_cost: float
    remaining_cash: float
    reason: str


def settle_buy(cash: float, fixed_quantity: float, open_price: float, *, side_bps: float = 20) -> BuySettlement:
    """All-or-reject fixed base quantity; no borrowing, shrinking or future resizing."""
    _positive(cash, open_price)
    _cost(side_bps)
    if not math.isfinite(fixed_quantity) or fixed_quantity < 0:
        raise ValueError("finite nonnegative quantity required")
    cost = fixed_quantity * open_price * side_bps / 10000
    spend = fixed_quantity * open_price + cost
    _finite_result(cost, spend)
    if fixed_quantity == 0 or spend > cash:
        return BuySettlement(False, 0, open_price, 0, cash, "zero_quantity" if fixed_quantity == 0 else "insufficient_cash")
    return BuySettlement(True, fixed_quantity, open_price, cost, cash - spend, "accepted")


def liquidation_cash(cash: float, quantity: float, price: float, *, side_bps: float = 20) -> float:
    _positive(quantity, price)
    _cost(side_bps)
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("finite nonnegative cash required")
    result = cash + quantity * price * (1 - side_bps / 10000)
    _finite_result(result)
    return result


def benchmark_bounds(entry_reference: float, btc: Minute, exit_bounds: ExitBounds,
                     *, round_trip_bps: float = 40) -> tuple[float, float]:
    """BTC reference-return bounds at the same exit point/minute, not an 8h close."""
    _positive(entry_reference)
    _cost(round_trip_bps)
    if btc.opened_at != exit_bounds.minute:
        raise ValueError("BTC minute is not synchronized to exit")
    lower, upper = (btc.open, btc.open) if exit_bounds.at_open else (btc.low, btc.high)
    result = (10000 * (lower / entry_reference - 1) - round_trip_bps,
              10000 * (upper / entry_reference - 1) - round_trip_bps)
    _finite_result(*result)
    return result


def excess_bounds(entry_reference: float, exit_bounds: ExitBounds, btc_entry: float, btc: Minute,
                  *, round_trip_bps: float = 40) -> tuple[float, float]:
    _positive(entry_reference)
    lower, upper = benchmark_bounds(btc_entry, btc, exit_bounds, round_trip_bps=round_trip_bps)
    alt_lower = 10000 * (exit_bounds.lower_price / entry_reference - 1) - round_trip_bps
    alt_upper = 10000 * (exit_bounds.upper_price / entry_reference - 1) - round_trip_bps
    result = alt_lower - upper, alt_upper - lower
    _finite_result(*result)
    return result


def excursion_bounds(entry_reference: float, completed: list[Minute], exit_bar: Minute,
                     exit_bounds: ExitBounds, *, entry_at: int) -> dict[str, tuple[float, float]]:
    """Avoid counting all exit-minute highs/lows as certainly preceding the exit.

    Caller supplies all fully held minutes from the entry open. Their exact grid
    is checked. Exposure before/after the exit inside its minute is unresolved.
    Prices at entry, completed minutes and the exit reference define inner bounds;
    the full exit-minute range defines outer bounds under the OHLC model.
    """
    _positive(entry_reference)
    _time(entry_at)
    if entry_at > exit_bar.opened_at:
        raise ValueError("exit precedes entry")
    if (completed and completed[0].opened_at != entry_at) or (not completed and entry_at != exit_bar.opened_at):
        raise ValueError("held prefix must start at entry")
    if entry_reference != (completed[0].open if completed else exit_bar.open):
        raise ValueError("entry reference must equal its minute open")
    if exit_bar.opened_at != exit_bounds.minute:
        raise ValueError("exit minute mismatch")
    if any(b.opened_at >= exit_bar.opened_at for b in completed):
        raise ValueError("post-exit extrema supplied")
    if any(b.opened_at != a.opened_at + 60 for a, b in zip(completed, completed[1:])):
        raise ValueError("missing, duplicate or reversed held minute")
    if completed and completed[-1].opened_at + 60 != exit_bar.opened_at:
        raise ValueError("missing minute before exit")
    known_high = max([entry_reference, exit_bar.open, exit_bounds.lower_price] + [b.high for b in completed])
    known_low = min([entry_reference, exit_bar.open, exit_bounds.upper_price] + [b.low for b in completed])
    possible_high = max(known_high, exit_bounds.upper_price, exit_bar.open if exit_bounds.at_open else exit_bar.high)
    possible_low = min(known_low, exit_bounds.lower_price, exit_bar.open if exit_bounds.at_open else exit_bar.low)
    result = {"mfe_bps": (10000 * (known_high / entry_reference - 1), 10000 * (possible_high / entry_reference - 1)),
              "mae_bps": (10000 * (possible_low / entry_reference - 1), 10000 * (known_low / entry_reference - 1))}
    _finite_result(*(x for bounds in result.values() for x in bounds))
    return result

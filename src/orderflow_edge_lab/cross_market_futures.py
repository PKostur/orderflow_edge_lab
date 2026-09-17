from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from .data import MarketEvent


@dataclass(frozen=True)
class FuturesSpec:
    root: str
    venue: str
    description: str
    tick_size: float
    point_value_usd: float
    micro_execution_analogue: str

    @property
    def tick_value_usd(self) -> float:
        return self.tick_size * self.point_value_usd


FUTURES_SPECS: Mapping[str, FuturesSpec] = {
    "ES": FuturesSpec("ES", "CME", "E-mini S&P 500", 0.25, 50.0, "MES"),
    "NQ": FuturesSpec("NQ", "CME", "E-mini Nasdaq-100", 0.25, 20.0, "MNQ"),
    "GC": FuturesSpec("GC", "COMEX", "Gold futures", 0.10, 100.0, "MGC"),
    "CL": FuturesSpec("CL", "NYMEX", "WTI Crude Oil futures", 0.01, 1000.0, "MCL"),
}


def futures_spec(root: str) -> FuturesSpec:
    key = str(root).strip().upper()
    try:
        return FUTURES_SPECS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported cross-market futures root: {root!r}") from exc


def extra_round_trip_friction_bps(*, root: str, price: float, total_ticks: float) -> float:
    """Convert a market-native total round-trip tick stress into basis points.

    `total_ticks` is the total additional price friction across entry plus exit.
    The executable bid/ask spread is expected to be modeled separately.
    Contract multiplier cancels when converting a tick price move to return bps.
    """
    spec = futures_spec(root)
    if isinstance(price, bool) or not math.isfinite(price) or price <= 0:
        raise ValueError("price must be finite and positive")
    if isinstance(total_ticks, bool) or not math.isfinite(total_ticks) or total_ticks < 0:
        raise ValueError("total_ticks must be finite and non-negative")
    return float(total_ticks * spec.tick_size / price * 10_000.0)


def friction_surface_bps(*, root: str, price: float, ticks: Iterable[float] = (0.0, 1.0, 2.0)) -> dict[float, float]:
    return {
        float(t): extra_round_trip_friction_bps(root=root, price=price, total_ticks=float(t))
        for t in ticks
    }


def _on_tick(value: float, tick_size: float, *, tolerance: float = 1e-8) -> bool:
    units = value / tick_size
    return abs(units - round(units)) <= tolerance * max(1.0, abs(units))


def audit_native_futures_events(
    events: Iterable[MarketEvent],
    *,
    root: str,
    require_single_symbol: bool = True,
) -> dict[str, object]:
    """Audit event prices against the frozen native futures tick grid.

    This is intentionally a data-integrity check only. It does not create a
    signal and does not infer a roll. Event-level research must remain on one
    recorded native contract per capture batch.
    """
    spec = futures_spec(root)
    rows = tuple(events)
    symbols = sorted({e.symbol for e in rows})
    off_tick = 0
    checked = 0
    for event in rows:
        for value in (event.price, event.bid, event.ask):
            if value is None:
                continue
            checked += 1
            if not _on_tick(float(value), spec.tick_size):
                off_tick += 1
    failures: list[str] = []
    if not rows:
        failures.append("no_events")
    if require_single_symbol and len(symbols) != 1:
        failures.append("multiple_native_contract_symbols")
    if off_tick:
        failures.append("off_tick_prices")
    return {
        "root": spec.root,
        "venue": spec.venue,
        "tick_size": spec.tick_size,
        "tick_value_usd": spec.tick_value_usd,
        "events": len(rows),
        "symbols": symbols,
        "prices_checked": checked,
        "off_tick_prices": off_tick,
        "passed": not failures,
        "failures": failures,
    }

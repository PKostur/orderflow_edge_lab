from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping
from urllib.request import Request, urlopen


class PairScreenError(ValueError):
    pass


DEFAULT_REST_BASE = "https://api.mexc.com"
STABLE_BASES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USDD"}


@dataclass(frozen=True)
class PairScreenConfig:
    top_n: int = 4
    max_spread_bps: float = 5.0
    min_turnover_usdt_24h: float = 10_000_000.0
    quote_coin: str = "USDT"
    context_symbol: str = "BTC_USDT"
    exclude_symbols: tuple[str, ...] = ("ENA_USDT",)
    exclude_stable_bases: bool = True
    rest_base: str = DEFAULT_REST_BASE


def _fetch_json(url: str, timeout: float = 10.0) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise PairScreenError(f"MEXC public REST returned HTTP {response.status}")
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairScreenError("MEXC public REST response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        raise PairScreenError(f"MEXC public REST response failed: {payload}")
    return payload


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _detail_map(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise PairScreenError("contract detail data must be a list")
    return {str(row.get("symbol")): dict(row) for row in data if isinstance(row, Mapping) and row.get("symbol")}


def _ticker_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, Mapping):
        return [dict(data)]
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, Mapping)]
    raise PairScreenError("contract ticker data must be an object or list")


def screen_pairs(config: PairScreenConfig = PairScreenConfig()) -> dict[str, Any]:
    if config.top_n < 1:
        raise PairScreenError("top_n must be positive")
    if config.max_spread_bps <= 0 or config.min_turnover_usdt_24h < 0:
        raise PairScreenError("spread and turnover limits are invalid")
    base = config.rest_base.rstrip("/")
    details = _detail_map(_fetch_json(f"{base}/api/v1/contract/detail"))
    tickers = _ticker_rows(_fetch_json(f"{base}/api/v1/contract/ticker"))
    explicit_excludes = {symbol.upper() for symbol in config.exclude_symbols}
    explicit_excludes.add(config.context_symbol.upper())
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        symbol = str(ticker.get("symbol") or "").upper()
        detail = details.get(symbol, {})
        base_coin = str(detail.get("baseCoin") or (symbol.split("_")[0] if "_" in symbol else ""))
        quote_coin = str(detail.get("quoteCoin") or (symbol.split("_")[1] if "_" in symbol else ""))
        bid = _number(ticker.get("bid1"))
        ask = _number(ticker.get("ask1"))
        last = _number(ticker.get("lastPrice"))
        amount24 = _number(ticker.get("amount24"))
        high24 = _number(ticker.get("high24Price"))
        low24 = _number(ticker.get("lower24Price"))
        funding = _number(ticker.get("fundingRate"))
        spread_bps = None
        if bid is not None and ask is not None and 0 < bid < ask:
            spread_bps = (ask - bid) / ((ask + bid) / 2.0) * 10_000.0
        range24_bps = None
        if last is not None and last > 0 and high24 is not None and low24 is not None and high24 >= low24:
            range24_bps = (high24 - low24) / last * 10_000.0
        reasons: list[str] = []
        if symbol in explicit_excludes:
            reasons.append("explicitly_excluded_symbol")
        if quote_coin != config.quote_coin:
            reasons.append("wrong_quote_coin")
        if config.exclude_stable_bases and base_coin in STABLE_BASES:
            reasons.append("stable_base")
        if spread_bps is None:
            reasons.append("invalid_bbo")
        elif spread_bps > config.max_spread_bps:
            reasons.append("spread_too_wide")
        if amount24 is None or amount24 < config.min_turnover_usdt_24h:
            reasons.append("turnover_too_low")
        if range24_bps is None or range24_bps <= 0:
            reasons.append("invalid_24h_range")
        row = {
            "symbol": symbol,
            "base_coin": base_coin,
            "quote_coin": quote_coin,
            "last_price": last,
            "bid1": bid,
            "ask1": ask,
            "spread_bps": spread_bps,
            "amount24_usdt": amount24,
            "range24_bps": range24_bps,
            "funding_rate": funding,
            "api_allowed": detail.get("apiAllowed"),
            "concept_plate": detail.get("conceptPlate"),
            "research_screen_pass": not reasons,
            "screen_fail_reasons": reasons,
        }
        rows.append(row)
    passing = [row for row in rows if row["research_screen_pass"]]
    passing.sort(key=lambda row: float(row["amount24_usdt"] or 0.0), reverse=True)
    selected = passing[: config.top_n]
    return {
        "schema_version": 1,
        "experiment": "market_compatibility_pair_screen",
        "source": "MEXC public futures contract detail and ticker endpoints",
        "selection_rule": {
            "top_n": config.top_n,
            "quote_coin": config.quote_coin,
            "max_spread_bps": config.max_spread_bps,
            "min_turnover_usdt_24h": config.min_turnover_usdt_24h,
            "excluded_symbols": sorted(explicit_excludes),
            "exclude_stable_bases": config.exclude_stable_bases,
            "ranking": "descending 24h quote turnover after hard compatibility filters",
            "backtest_performance_used_for_selection": False,
            "api_allowed_required_for_research": False,
        },
        "selected_symbols": [row["symbol"] for row in selected],
        "selected": selected,
        "passing_count": len(passing),
        "universe_count": len(rows),
        "universe": rows,
        "claims": {
            "research_only": True,
            "selection_uses_no_strategy_pnl": True,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

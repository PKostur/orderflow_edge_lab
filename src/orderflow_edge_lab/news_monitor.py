from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class NewsMonitorError(ValueError):
    pass


DEFAULT_REST_BASE = "https://api.mexc.com"
DEFAULT_SOURCES: tuple[tuple[str, str], ...] = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/?format=rss"),
)

# Deliberately conservative headline aliases. Ambiguous common words are avoided.
SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("bitcoin", "btc"),
    "ETH": ("ethereum", "ether", "eth"),
    "SOL": ("solana", "sol"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("dogecoin", "doge"),
    "BNB": ("bnb", "binance coin"),
    "ADA": ("cardano", "ada"),
    "AVAX": ("avalanche", "avax"),
    "LINK": ("chainlink", "link"),
    "SUI": ("sui",),
    "HYPE": ("hyperliquid", "hype"),
    "ENA": ("ethena", "ena"),
    "TON": ("toncoin", "the open network"),
    "TRX": ("tron", "trx"),
    "DOT": ("polkadot", "dot"),
    "LTC": ("litecoin", "ltc"),
    "BCH": ("bitcoin cash", "bch"),
    "UNI": ("uniswap", "uni"),
    "AAVE": ("aave",),
    "WIF": ("dogwifhat", "wif"),
    "PEPE": ("pepe",),
    "TAO": ("bittensor", "tao"),
    "ZEC": ("zcash", "zec"),
    "XLM": ("stellar", "xlm"),
    "ARB": ("arbitrum", "arb"),
    "OP": ("optimism",),
    "APT": ("aptos", "apt"),
    "NEAR": ("near protocol",),
}


@dataclass(frozen=True)
class NewsMonitorConfig:
    context_symbol: str = "BTC_USDT"
    interval: str = "Min5"
    max_age_hours: int = 48
    pre_event_minutes: int = 15
    behavior_horizons_minutes: tuple[int, ...] = (5, 15, 30, 60)
    rest_base: str = DEFAULT_REST_BASE
    sources: tuple[tuple[str, str], ...] = DEFAULT_SOURCES


def _fetch_bytes(url: str, timeout: float = 12.0) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "User-Agent": "orderflow-edge-lab/1.0 research-news-monitor",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise NewsMonitorError(f"public news source returned HTTP {response.status}")
        return response.read(8_000_000)


def _fetch_json(url: str, timeout: float = 10.0) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise NewsMonitorError(f"MEXC public REST returned HTTP {response.status}")
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NewsMonitorError("MEXC public REST response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        raise NewsMonitorError(f"MEXC public REST response failed: {payload}")
    return payload


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_text(element: ET.Element, names: Iterable[str]) -> str | None:
    names_lower = {name.lower() for name in names}
    for child in element.iter():
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names_lower and child.text and child.text.strip():
            return child.text.strip()
    return None


def parse_feed(source_name: str, raw: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NewsMonitorError(f"{source_name}: feed is not valid XML") from exc
    entries = list(root.findall(".//item"))
    if not entries:
        entries = [item for item in root.iter() if item.tag.rsplit("}", 1)[-1].lower() == "entry"]
    output: list[dict[str, Any]] = []
    for entry in entries:
        title = _first_text(entry, ("title",))
        published = _parse_published(_first_text(entry, ("pubDate", "published", "updated", "date")))
        link = _first_text(entry, ("link", "guid", "id"))
        if not link:
            for child in entry.iter():
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"].strip()
                    break
        if not title or published is None:
            continue
        link = link or ""
        event_id = hashlib.sha256(
            f"{source_name}\n{link}\n{published.isoformat()}\n{title}".encode("utf-8")
        ).hexdigest()
        output.append(
            {
                "event_id": event_id,
                "source": source_name,
                "title": title,
                "url": link,
                "published_at": published.isoformat(),
                "published_epoch_seconds": int(published.timestamp()),
            }
        )
    return output


def _headline_matches(title: str, symbol: str) -> bool:
    base = symbol.upper().split("_", 1)[0]
    aliases = SYMBOL_ALIASES.get(base, ())
    if not aliases:
        aliases = (base,) if len(base) >= 4 else ()
    title_lower = title.lower()
    for alias in aliases:
        pattern = r"(?<![a-z0-9])" + re.escape(alias.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, title_lower):
            return True
    return False


def _kline_closes(payload: Mapping[str, Any]) -> dict[int, float]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise NewsMonitorError("kline data must be an object")
    times = data.get("time")
    closes = data.get("close")
    if not isinstance(times, list) or not isinstance(closes, list) or len(times) != len(closes):
        raise NewsMonitorError("kline time/close arrays are invalid")
    output: dict[int, float] = {}
    for raw_time, raw_close in zip(times, closes):
        try:
            ts = int(raw_time)
            close = float(raw_close)
        except (TypeError, ValueError):
            continue
        if ts > 0 and close > 0 and math.isfinite(close):
            output[ts] = close
    return output


def _first_at_or_after(series: Mapping[int, float], timestamp: int) -> tuple[int, float] | None:
    for ts in sorted(series):
        if ts >= timestamp:
            return ts, float(series[ts])
    return None


def _last_at_or_before(series: Mapping[int, float], timestamp: int) -> tuple[int, float] | None:
    candidate: tuple[int, float] | None = None
    for ts in sorted(series):
        if ts > timestamp:
            break
        candidate = (ts, float(series[ts]))
    return candidate


def _bps(start: float, end: float) -> float | None:
    if start <= 0 or end <= 0:
        return None
    value = (end / start - 1.0) * 10_000.0
    return value if math.isfinite(value) else None


def event_behavior(
    coin: Mapping[int, float],
    btc: Mapping[int, float],
    event_epoch_seconds: int,
    *,
    pre_event_minutes: int = 15,
    horizons_minutes: tuple[int, ...] = (5, 15, 30, 60),
) -> dict[str, Any]:
    coin_anchor = _first_at_or_after(coin, event_epoch_seconds)
    btc_anchor = _first_at_or_after(btc, event_epoch_seconds)
    if coin_anchor is None or btc_anchor is None:
        return {"status": "missing_event_anchor", "horizons": {}}
    anchor_ts = max(coin_anchor[0], btc_anchor[0])
    coin_anchor = _first_at_or_after(coin, anchor_ts)
    btc_anchor = _first_at_or_after(btc, anchor_ts)
    if coin_anchor is None or btc_anchor is None:
        return {"status": "missing_aligned_anchor", "horizons": {}}

    coin_pre = _last_at_or_before(coin, anchor_ts - pre_event_minutes * 60)
    btc_pre = _last_at_or_before(btc, anchor_ts - pre_event_minutes * 60)
    pre_coin_bps = _bps(coin_pre[1], coin_anchor[1]) if coin_pre else None
    pre_btc_bps = _bps(btc_pre[1], btc_anchor[1]) if btc_pre else None

    horizons: dict[str, Any] = {}
    for horizon in horizons_minutes:
        target = anchor_ts + int(horizon) * 60
        coin_future = _first_at_or_after(coin, target)
        btc_future = _first_at_or_after(btc, target)
        coin_return = _bps(coin_anchor[1], coin_future[1]) if coin_future else None
        btc_return = _bps(btc_anchor[1], btc_future[1]) if btc_future else None
        horizons[f"{int(horizon)}m"] = {
            "coin_return_bps": coin_return,
            "btc_return_bps": btc_return,
            "coin_minus_btc_return_bps": (
                coin_return - btc_return if coin_return is not None and btc_return is not None else None
            ),
            "complete": coin_return is not None and btc_return is not None,
        }

    return {
        "status": "ok",
        "event_anchor_epoch_seconds": anchor_ts,
        "anchor_delay_seconds": anchor_ts - event_epoch_seconds,
        "pre_event_minutes": pre_event_minutes,
        "pre_event_coin_return_bps": pre_coin_bps,
        "pre_event_btc_return_bps": pre_btc_bps,
        "horizons": horizons,
        "comparator_note": "coin_minus_btc_return_bps is a simple difference, not beta-adjusted abnormal return",
    }


def monitor_news(
    symbols: Iterable[str],
    config: NewsMonitorConfig = NewsMonitorConfig(),
    *,
    now_epoch_seconds: int | None = None,
    feed_payloads: Mapping[str, bytes] | None = None,
    candle_series: Mapping[str, Mapping[int, float]] | None = None,
) -> dict[str, Any]:
    symbol_list = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    if not symbol_list:
        raise NewsMonitorError("at least one symbol is required")
    if config.max_age_hours <= 0 or config.pre_event_minutes <= 0:
        raise NewsMonitorError("news-monitor time windows must be positive")
    if not config.behavior_horizons_minutes or any(value <= 0 for value in config.behavior_horizons_minutes):
        raise NewsMonitorError("behavior horizons must be positive")

    now = int(now_epoch_seconds if now_epoch_seconds is not None else datetime.now(timezone.utc).timestamp())
    cutoff = now - config.max_age_hours * 3600
    source_reports: list[dict[str, Any]] = []
    source_errors: list[dict[str, str]] = []
    events: dict[str, dict[str, Any]] = {}

    for source_name, source_url in config.sources:
        try:
            raw = feed_payloads[source_name] if feed_payloads is not None and source_name in feed_payloads else _fetch_bytes(source_url)
            parsed = parse_feed(source_name, raw)
            source_reports.append(
                {
                    "source": source_name,
                    "url": source_url,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "parsed_items": len(parsed),
                }
            )
            for event in parsed:
                published = int(event["published_epoch_seconds"])
                if published < cutoff or published > now + 300:
                    continue
                events.setdefault(str(event["event_id"]), event)
        except Exception as exc:
            source_errors.append({"source": source_name, "error_type": type(exc).__name__})

    matched: list[dict[str, Any]] = []
    for event in sorted(events.values(), key=lambda row: int(row["published_epoch_seconds"])):
        matches = [symbol for symbol in symbol_list if _headline_matches(str(event["title"]), symbol)]
        for symbol in matches:
            matched.append({**event, "symbol": symbol})

    needed_symbols = {config.context_symbol, *(row["symbol"] for row in matched)}
    series_cache: dict[str, Mapping[int, float]] = {}
    market_errors: list[dict[str, str]] = []
    if candle_series is not None:
        for symbol in needed_symbols:
            if symbol in candle_series:
                series_cache[symbol] = candle_series[symbol]
    else:
        base = config.rest_base.rstrip("/")
        start = cutoff - max(config.pre_event_minutes, 15) * 60 - 600
        end = now + max(config.behavior_horizons_minutes) * 60 + 600
        for symbol in sorted(needed_symbols):
            try:
                query = urlencode({"interval": config.interval, "start": start, "end": end})
                payload = _fetch_json(f"{base}/api/v1/contract/kline/{symbol}?{query}")
                series_cache[symbol] = _kline_closes(payload)
            except Exception as exc:
                market_errors.append({"symbol": symbol, "error_type": type(exc).__name__})

    enriched: list[dict[str, Any]] = []
    context = series_cache.get(config.context_symbol, {})
    for event in matched:
        symbol = str(event["symbol"])
        coin = series_cache.get(symbol, {})
        behavior = event_behavior(
            coin,
            context,
            int(event["published_epoch_seconds"]),
            pre_event_minutes=config.pre_event_minutes,
            horizons_minutes=config.behavior_horizons_minutes,
        )
        enriched.append({**event, "behavior": behavior})

    return {
        "schema_version": 1,
        "experiment": "public_coin_news_behavior_context",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "symbols": symbol_list,
            "context_symbol": config.context_symbol,
            "interval": config.interval,
            "max_age_hours": config.max_age_hours,
            "pre_event_minutes": config.pre_event_minutes,
            "behavior_horizons_minutes": list(config.behavior_horizons_minutes),
            "matching_scope": "headline/title only using conservative symbol aliases",
            "article_bodies_stored": False,
        },
        "sources": source_reports,
        "source_errors": source_errors,
        "market_data_errors": market_errors,
        "events": enriched,
        "event_count": len(enriched),
        "claims": {
            "research_only": True,
            "observational_context_not_causal_attribution": True,
            "news_is_strategy_filter": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "live_order_transmission_supported": False,
        },
    }

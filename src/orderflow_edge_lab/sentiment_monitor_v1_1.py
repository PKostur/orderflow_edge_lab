from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from orderflow_edge_lab.news_monitor import NewsMonitorConfig, monitor_news
from orderflow_edge_lab.sentiment_monitor import (
    SentimentMonitorError,
    _decayed_state,
    _event_clusters,
    _state_statistics,
    score_headline,
)


PROTOCOL_NAME = "sentiment-monitor-v1.1"


def _protocol_symbols(protocol: Mapping[str, Any]) -> tuple[list[str], set[str]]:
    universe = protocol.get("observation_universe", {})
    conditioning = [str(value).upper() for value in universe.get("strategy_conditioning_symbols", [])]
    context = [str(value).upper() for value in universe.get("context_only_symbols", [])]
    readiness = {str(value).upper() for value in universe.get("readiness_symbols", conditioning)}
    symbols = sorted(set(conditioning + context))
    if not symbols or not readiness:
        raise SentimentMonitorError("v1.1 requires a fixed observation and readiness universe")
    if not readiness.issubset(set(symbols)):
        raise SentimentMonitorError("readiness symbols must be inside the observation universe")
    return symbols, readiness


def summarize_sentiment_events_v1_1(
    events: list[dict[str, Any]],
    protocol: Mapping[str, Any],
    now_epoch_seconds: int,
) -> dict[str, Any]:
    _, readiness_symbols = _protocol_symbols(protocol)
    readiness = protocol["state_readiness"]
    dependence = protocol["dependence"]
    market = protocol["market_behavior"]
    state_aggregation = protocol["state_aggregation"]

    readiness_events = [event for event in events if str(event.get("symbol", "")).upper() in readiness_symbols]
    non_neutral = [event for event in readiness_events if event.get("sentiment", {}).get("label") != "neutral"]
    clusters = _event_clusters(readiness_events, int(dependence["event_cluster_gap_minutes"]))
    sources = sorted({str(event.get("source")) for event in readiness_events if event.get("source")})
    conditioning_symbols = sorted({str(event.get("symbol")) for event in readiness_events if event.get("symbol")})

    minimum_symbols = int(readiness.get("minimum_distinct_conditioning_symbols", 1))
    screen_ready = (
        len(readiness_events) >= int(readiness["minimum_scored_matched_events"])
        and len(non_neutral) >= int(readiness["minimum_non_neutral_events"])
        and len(clusters) >= int(readiness["minimum_independent_event_clusters"])
        and len(sources) >= int(readiness["minimum_distinct_sources"])
        and len(conditioning_symbols) >= minimum_symbols
    )
    return {
        "event_count": len(events),
        "readiness_event_count": len(readiness_events),
        "non_neutral_event_count": len(non_neutral),
        "distinct_sources": sources,
        "distinct_conditioning_symbols": conditioning_symbols,
        "independent_event_cluster_count": len(clusters),
        "event_clusters": clusters,
        "state_screen_ready": screen_ready,
        "readiness_symbols": sorted(readiness_symbols),
        "current_symbol_state": _decayed_state(
            events,
            now_epoch_seconds,
            half_life_minutes=int(state_aggregation["half_life_minutes"]),
            maximum_age_hours=int(state_aggregation["maximum_age_hours"]),
        ),
        "state_statistics": _state_statistics(readiness_events, market["horizons_minutes"]),
    }


def monitor_sentiment_v1_1(
    protocol: Mapping[str, Any],
    *,
    now_epoch_seconds: int | None = None,
    feed_payloads: Mapping[str, bytes] | None = None,
    candle_series: Mapping[str, Mapping[int, float]] | None = None,
) -> dict[str, Any]:
    if protocol.get("protocol_name") != PROTOCOL_NAME:
        raise SentimentMonitorError("unsupported v1.1 sentiment protocol")
    symbols, _ = _protocol_symbols(protocol)
    now = int(now_epoch_seconds if now_epoch_seconds is not None else datetime.now(timezone.utc).timestamp())
    boundary = int(datetime.fromisoformat(str(protocol["evidence_start_utc"]).replace("Z", "+00:00")).timestamp())
    market = protocol["market_behavior"]
    scoring = protocol["scoring"]
    sources = tuple((str(row["name"]), str(row["url"])) for row in protocol["sources"])

    news = monitor_news(
        symbols,
        NewsMonitorConfig(
            context_symbol=str(market["context_symbol"]),
            interval=str(market["interval"]),
            max_age_hours=int(market["max_age_hours"]),
            pre_event_minutes=int(market["pre_event_minutes"]),
            behavior_horizons_minutes=tuple(int(value) for value in market["horizons_minutes"]),
            sources=sources,
        ),
        now_epoch_seconds=now,
        feed_payloads=feed_payloads,
        candle_series=candle_series,
    )

    events: list[dict[str, Any]] = []
    for event in news["events"]:
        published = int(event["published_epoch_seconds"])
        if published < boundary:
            continue
        sentiment = score_headline(
            str(event["title"]),
            scoring["positive_phrase_weights"],
            scoring["negative_phrase_weights"],
            neutral_abs_score_below=float(scoring["neutral_abs_score_below"]),
        )
        events.append({**event, "sentiment": sentiment})
    events.sort(key=lambda row: (int(row["published_epoch_seconds"]), str(row["event_id"]), str(row["symbol"])))

    return {
        "schema_version": 1,
        "experiment": "public_headline_sentiment_context_v1_1",
        "protocol_name": PROTOCOL_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_start_utc": protocol["evidence_start_utc"],
        "observation_symbols": symbols,
        "sources": news["sources"],
        "source_errors": news["source_errors"],
        "market_data_errors": news["market_data_errors"],
        "events": events,
        "summary": summarize_sentiment_events_v1_1(events, protocol, now),
        "claims": {
            "research_only": True,
            "observational_only": True,
            "causal_effect_established": False,
            "sentiment_is_strategy_filter": False,
            "eligible_as_strategy_filter": False,
            "v1_evidence_reused": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "live_order_transmission_supported": False,
        },
    }


def merge_sentiment_ledgers_v1_1(
    prior: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    now_epoch_seconds: int | None = None,
) -> dict[str, Any]:
    if protocol.get("protocol_name") != PROTOCOL_NAME or current.get("protocol_name") != PROTOCOL_NAME:
        raise SentimentMonitorError("v1.1 ledger merge requires v1.1 protocol and current snapshot")
    if prior and prior.get("protocol_name") != PROTOCOL_NAME:
        raise SentimentMonitorError("refusing to merge sentiment evidence from another protocol version")

    now = int(now_epoch_seconds if now_epoch_seconds is not None else datetime.now(timezone.utc).timestamp())
    boundary = int(datetime.fromisoformat(str(protocol["evidence_start_utc"]).replace("Z", "+00:00")).timestamp())
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for payload in (prior or {}, current):
        for event in payload.get("events", []):
            if int(event.get("published_epoch_seconds", 0) or 0) < boundary:
                continue
            key = (str(event.get("event_id", "")), str(event.get("symbol", "")))
            if not all(key):
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(event)
                continue
            old_complete = sum(bool(row.get("complete")) for row in existing.get("behavior", {}).get("horizons", {}).values())
            new_complete = sum(bool(row.get("complete")) for row in event.get("behavior", {}).get("horizons", {}).values())
            if new_complete >= old_complete:
                merged[key] = dict(event)

    events = sorted(
        merged.values(),
        key=lambda row: (int(row["published_epoch_seconds"]), str(row["event_id"]), str(row["symbol"])),
    )
    return {
        "schema_version": 1,
        "experiment": "public_headline_sentiment_context_cumulative_v1_1",
        "protocol_name": PROTOCOL_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_start_utc": protocol["evidence_start_utc"],
        "events": events,
        "summary": summarize_sentiment_events_v1_1(events, protocol, now),
        "claims": dict(current["claims"]),
    }

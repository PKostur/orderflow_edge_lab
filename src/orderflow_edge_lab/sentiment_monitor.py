from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import statistics
from typing import Any, Iterable, Mapping

from orderflow_edge_lab.news_monitor import NewsMonitorConfig, monitor_news


class SentimentMonitorError(ValueError):
    pass


def _phrase_matches(text: str, phrase: str) -> list[tuple[int, int]]:
    pattern = r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])"
    return [match.span() for match in re.finditer(pattern, text.lower())]


def score_headline(
    title: str,
    positive_weights: Mapping[str, float],
    negative_weights: Mapping[str, float],
    *,
    neutral_abs_score_below: float = 0.10,
) -> dict[str, Any]:
    if neutral_abs_score_below < 0 or neutral_abs_score_below >= 1:
        raise SentimentMonitorError("neutral threshold must be in [0, 1)")

    weighted_phrases: list[tuple[str, float]] = []
    weighted_phrases.extend((str(key).lower(), float(value)) for key, value in positive_weights.items())
    weighted_phrases.extend((str(key).lower(), float(value)) for key, value in negative_weights.items())
    weighted_phrases.sort(key=lambda item: (-len(item[0]), item[0]))

    occupied: list[tuple[int, int]] = []
    matched: list[dict[str, Any]] = []
    raw = 0.0
    for phrase, weight in weighted_phrases:
        for start, end in _phrase_matches(title, phrase):
            if any(start < prior_end and end > prior_start for prior_start, prior_end in occupied):
                continue
            occupied.append((start, end))
            raw += weight
            matched.append({"phrase": phrase, "weight": weight, "span": [start, end]})

    score = math.tanh(raw / 3.0)
    if abs(score) < neutral_abs_score_below:
        label = "neutral"
    elif score > 0:
        label = "bullish"
    else:
        label = "bearish"
    return {
        "raw_score": raw,
        "score": score,
        "label": label,
        "confidence": abs(score),
        "matched_terms": matched,
    }


def _event_clusters(events: list[Mapping[str, Any]], gap_minutes: int) -> list[dict[str, Any]]:
    if gap_minutes <= 0:
        raise SentimentMonitorError("cluster gap must be positive")
    unique: dict[str, int] = {}
    for event in events:
        event_id = str(event.get("event_id", ""))
        timestamp = int(event.get("published_epoch_seconds", 0) or 0)
        if event_id and timestamp > 0:
            unique[event_id] = timestamp
    ordered = sorted(unique.items(), key=lambda item: (item[1], item[0]))
    clusters: list[dict[str, Any]] = []
    gap_seconds = gap_minutes * 60
    for event_id, timestamp in ordered:
        if not clusters or timestamp - int(clusters[-1]["end_epoch_seconds"]) > gap_seconds:
            clusters.append(
                {
                    "cluster_id": len(clusters) + 1,
                    "start_epoch_seconds": timestamp,
                    "end_epoch_seconds": timestamp,
                    "event_ids": [event_id],
                }
            )
        else:
            clusters[-1]["end_epoch_seconds"] = timestamp
            clusters[-1]["event_ids"].append(event_id)
    return clusters


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _state_statistics(events: list[Mapping[str, Any]], horizons: Iterable[int]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for horizon in horizons:
        key = f"{int(horizon)}m"
        signed_relative: list[float] = []
        relative: list[float] = []
        absolute_coin: list[float] = []
        for event in events:
            sentiment = event.get("sentiment", {})
            score = float(sentiment.get("score", 0.0) or 0.0)
            if sentiment.get("label") == "neutral" or score == 0:
                continue
            row = event.get("behavior", {}).get("horizons", {}).get(key, {})
            if not row.get("complete"):
                continue
            rel = row.get("coin_minus_btc_return_bps")
            coin = row.get("coin_return_bps")
            if rel is None or coin is None:
                continue
            rel_value = float(rel)
            coin_value = float(coin)
            if not math.isfinite(rel_value) or not math.isfinite(coin_value):
                continue
            relative.append(rel_value)
            signed_relative.append((1.0 if score > 0 else -1.0) * rel_value)
            absolute_coin.append(abs(coin_value))
        output[key] = {
            "non_neutral_complete_events": len(signed_relative),
            "mean_signed_relative_return_bps": _mean(signed_relative),
            "median_signed_relative_return_bps": _median(signed_relative),
            "directional_hit_rate": (
                sum(value > 0 for value in signed_relative) / len(signed_relative) if signed_relative else None
            ),
            "mean_future_coin_minus_btc_return_bps": _mean(relative),
            "mean_future_absolute_coin_return_bps": _mean(absolute_coin),
        }
    return output


def _decayed_state(
    events: list[Mapping[str, Any]],
    now_epoch_seconds: int,
    *,
    half_life_minutes: int,
    maximum_age_hours: int,
) -> dict[str, Any]:
    if half_life_minutes <= 0 or maximum_age_hours <= 0:
        raise SentimentMonitorError("sentiment decay windows must be positive")
    by_symbol: dict[str, list[tuple[float, float]]] = {}
    max_age_seconds = maximum_age_hours * 3600
    decay = math.log(2.0) / (half_life_minutes * 60.0)
    for event in events:
        timestamp = int(event.get("published_epoch_seconds", 0) or 0)
        age = now_epoch_seconds - timestamp
        if age < 0 or age > max_age_seconds:
            continue
        score = float(event.get("sentiment", {}).get("score", 0.0) or 0.0)
        symbol = str(event.get("symbol", ""))
        if not symbol or not math.isfinite(score):
            continue
        weight = math.exp(-decay * age)
        by_symbol.setdefault(symbol, []).append((score, weight))
    state: dict[str, Any] = {}
    for symbol, rows in sorted(by_symbol.items()):
        denominator = sum(weight for _, weight in rows)
        value = sum(score * weight for score, weight in rows) / denominator if denominator else 0.0
        state[symbol] = {
            "decayed_sentiment_score": value,
            "contributing_events": len(rows),
            "half_life_minutes": half_life_minutes,
            "maximum_age_hours": maximum_age_hours,
        }
    return state


def summarize_sentiment_events(events: list[dict[str, Any]], protocol: Mapping[str, Any], now_epoch_seconds: int) -> dict[str, Any]:
    dependence = protocol["dependence"]
    readiness = protocol["state_readiness"]
    market = protocol["market_behavior"]
    state_aggregation = protocol.get("state_aggregation", {"half_life_minutes": 90, "maximum_age_hours": 6})
    clusters = _event_clusters(events, int(dependence["event_cluster_gap_minutes"]))
    non_neutral = [event for event in events if event.get("sentiment", {}).get("label") != "neutral"]
    sources = sorted({str(event.get("source")) for event in events if event.get("source")})
    screen_ready = (
        len(events) >= int(readiness["minimum_scored_matched_events"])
        and len(non_neutral) >= int(readiness["minimum_non_neutral_events"])
        and len(clusters) >= int(readiness["minimum_independent_event_clusters"])
        and len(sources) >= int(readiness["minimum_distinct_sources"])
    )
    return {
        "event_count": len(events),
        "non_neutral_event_count": len(non_neutral),
        "distinct_sources": sources,
        "independent_event_cluster_count": len(clusters),
        "event_clusters": clusters,
        "state_screen_ready": screen_ready,
        "current_symbol_state": _decayed_state(
            events,
            now_epoch_seconds,
            half_life_minutes=int(state_aggregation["half_life_minutes"]),
            maximum_age_hours=int(state_aggregation["maximum_age_hours"]),
        ),
        "state_statistics": _state_statistics(events, market["horizons_minutes"]),
    }


def monitor_sentiment(
    symbols: Iterable[str],
    protocol: Mapping[str, Any],
    *,
    now_epoch_seconds: int | None = None,
    feed_payloads: Mapping[str, bytes] | None = None,
    candle_series: Mapping[str, Mapping[int, float]] | None = None,
) -> dict[str, Any]:
    if protocol.get("protocol_name") != "sentiment-monitor-v1":
        raise SentimentMonitorError("unsupported sentiment protocol")
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
    summary = summarize_sentiment_events(events, protocol, now)
    return {
        "schema_version": 1,
        "experiment": "public_headline_sentiment_context",
        "protocol_name": "sentiment-monitor-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_start_utc": protocol["evidence_start_utc"],
        "sources": news["sources"],
        "source_errors": news["source_errors"],
        "market_data_errors": news["market_data_errors"],
        "events": events,
        "summary": summary,
        "claims": {
            "research_only": True,
            "observational_only": True,
            "causal_effect_established": False,
            "sentiment_is_strategy_filter": False,
            "eligible_as_strategy_filter": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "live_order_transmission_supported": False,
        },
    }


def merge_sentiment_ledgers(
    prior: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    now_epoch_seconds: int | None = None,
) -> dict[str, Any]:
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
            old_complete = sum(
                bool(row.get("complete")) for row in existing.get("behavior", {}).get("horizons", {}).values()
            )
            new_complete = sum(bool(row.get("complete")) for row in event.get("behavior", {}).get("horizons", {}).values())
            if new_complete >= old_complete:
                merged[key] = dict(event)
    events = sorted(
        merged.values(),
        key=lambda row: (int(row["published_epoch_seconds"]), str(row["event_id"]), str(row["symbol"])),
    )
    return {
        "schema_version": 1,
        "experiment": "public_headline_sentiment_context_cumulative",
        "protocol_name": "sentiment-monitor-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_start_utc": protocol["evidence_start_utc"],
        "events": events,
        "summary": summarize_sentiment_events(events, protocol, now),
        "claims": dict(current["claims"]),
    }

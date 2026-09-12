from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CorrelationPanelError(ValueError):
    pass


DEFAULT_REST_BASE = "https://api.mexc.com"


@dataclass(frozen=True)
class CorrelationPanelConfig:
    context_symbol: str = "BTC_USDT"
    interval: str = "Min5"
    lookback_hours: int = 72
    min_samples: int = 200
    panel_size: int = 6
    high_positive_min: float = 0.65
    low_absolute_max: float = 0.25
    high_target: int = 2
    low_target: int = 2
    rest_base: str = DEFAULT_REST_BASE
    request_pause_seconds: float = 0.12


def _fetch_json(url: str, timeout: float = 10.0) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise CorrelationPanelError(f"MEXC public REST returned HTTP {response.status}")
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorrelationPanelError("MEXC public REST response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        raise CorrelationPanelError(f"MEXC public REST response failed: {payload}")
    return payload


def _kline_closes(payload: Mapping[str, Any]) -> dict[int, float]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise CorrelationPanelError("kline data must be an object")
    times = data.get("time")
    closes = data.get("close")
    if not isinstance(times, list) or not isinstance(closes, list) or len(times) != len(closes):
        raise CorrelationPanelError("kline time/close arrays are invalid")
    out: dict[int, float] = {}
    for raw_time, raw_close in zip(times, closes):
        try:
            ts = int(raw_time)
            close = float(raw_close)
        except (TypeError, ValueError):
            continue
        if ts > 0 and close > 0 and math.isfinite(close):
            out[ts] = close
    return out


def _aligned_returns(left: Mapping[int, float], right: Mapping[int, float]) -> tuple[list[float], list[float]]:
    common = sorted(set(left).intersection(right))
    left_returns: list[float] = []
    right_returns: list[float] = []
    for previous, current in zip(common, common[1:]):
        l0, l1 = float(left[previous]), float(left[current])
        r0, r1 = float(right[previous]), float(right[current])
        if l0 <= 0 or r0 <= 0:
            continue
        lr = l1 / l0 - 1.0
        rr = r1 / r0 - 1.0
        if math.isfinite(lr) and math.isfinite(rr):
            left_returns.append(lr)
            right_returns.append(rr)
    return left_returns, right_returns


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    centered_left = [value - mean_left for value in left]
    centered_right = [value - mean_right for value in right]
    variance_left = sum(value * value for value in centered_left)
    variance_right = sum(value * value for value in centered_right)
    if variance_left <= 0 or variance_right <= 0:
        return None
    covariance = sum(a * b for a, b in zip(centered_left, centered_right))
    value = covariance / math.sqrt(variance_left * variance_right)
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _bucket(correlation: float | None, config: CorrelationPanelConfig) -> str:
    if correlation is None:
        return "insufficient"
    if correlation >= config.high_positive_min:
        return "high_positive"
    if abs(correlation) <= config.low_absolute_max:
        return "low_absolute"
    if correlation < 0:
        return "negative_intermediate"
    return "positive_intermediate"


def select_panel(
    screen_report: Mapping[str, Any],
    correlations: Mapping[str, Mapping[str, Any]],
    config: CorrelationPanelConfig = CorrelationPanelConfig(),
) -> dict[str, Any]:
    selected_rows = screen_report.get("selected")
    if not isinstance(selected_rows, list) or not selected_rows:
        raise CorrelationPanelError("compatibility screen contains no selected candidates")
    if config.panel_size < 1 or config.high_target < 0 or config.low_target < 0:
        raise CorrelationPanelError("panel targets are invalid")
    if config.high_target + config.low_target > config.panel_size:
        raise CorrelationPanelError("high/low targets exceed panel size")

    candidates: list[dict[str, Any]] = []
    for item in selected_rows:
        if not isinstance(item, Mapping) or not item.get("symbol"):
            continue
        symbol = str(item["symbol"])
        evidence = correlations.get(symbol, {})
        corr_raw = evidence.get("correlation")
        samples_raw = evidence.get("samples", 0)
        try:
            corr = float(corr_raw) if corr_raw is not None else None
        except (TypeError, ValueError):
            corr = None
        try:
            samples = int(samples_raw)
        except (TypeError, ValueError):
            samples = 0
        if corr is not None and not math.isfinite(corr):
            corr = None
        row = dict(item)
        row.update(
            {
                "btc_correlation": corr,
                "btc_correlation_samples": samples,
                "btc_correlation_bucket": _bucket(corr if samples >= config.min_samples else None, config),
                "correlation_eligible": corr is not None and samples >= config.min_samples,
            }
        )
        candidates.append(row)

    eligible = [row for row in candidates if row["correlation_eligible"]]
    by_turnover = lambda row: float(row.get("amount24_usdt") or 0.0)
    high = sorted(
        [row for row in eligible if row["btc_correlation_bucket"] == "high_positive"],
        key=by_turnover,
        reverse=True,
    )
    low = sorted(
        [row for row in eligible if row["btc_correlation_bucket"] == "low_absolute"],
        key=by_turnover,
        reverse=True,
    )

    panel: list[dict[str, Any]] = []
    reasons: dict[str, str] = {}

    def add(rows: list[dict[str, Any]], limit: int, reason: str) -> None:
        for row in rows:
            if len([x for x in panel if reasons.get(str(x["symbol"])) == reason]) >= limit:
                break
            if any(existing["symbol"] == row["symbol"] for existing in panel):
                continue
            panel.append(row)
            reasons[str(row["symbol"])] = reason

    add(high, config.high_target, "high_positive_target")
    add(low, config.low_target, "low_absolute_target")

    remaining = [row for row in eligible if not any(existing["symbol"] == row["symbol"] for existing in panel)]
    remaining.sort(
        key=lambda row: (
            float(row["btc_correlation"] if row["btc_correlation"] is not None else 2.0),
            -by_turnover(row),
        )
    )
    while len(panel) < config.panel_size and remaining:
        row = remaining.pop(0)
        panel.append(row)
        reasons[str(row["symbol"])] = "diversity_fallback_lowest_remaining_correlation"

    for row in panel:
        row["panel_selection_reason"] = reasons[str(row["symbol"])]

    return {
        "schema_version": 1,
        "experiment": "btc_correlation_diversified_pair_panel",
        "source_screen_experiment": screen_report.get("experiment"),
        "selection_rule": {
            "panel_size": config.panel_size,
            "context_symbol": config.context_symbol,
            "interval": config.interval,
            "lookback_hours": config.lookback_hours,
            "minimum_correlation_samples": config.min_samples,
            "high_positive_min": config.high_positive_min,
            "low_absolute_max": config.low_absolute_max,
            "high_target": config.high_target,
            "low_target": config.low_target,
            "fallback": "fill remaining slots by lowest remaining BTC correlation, then higher turnover",
            "compatibility_screen_used_strategy_pnl": False,
            "correlation_selection_used_strategy_pnl": False,
        },
        "selected_symbols": [str(row["symbol"]) for row in panel],
        "selected": panel,
        "candidate_correlations": candidates,
        "bucket_counts": {
            bucket: sum(row["btc_correlation_bucket"] == bucket for row in eligible)
            for bucket in ("high_positive", "low_absolute", "negative_intermediate", "positive_intermediate")
        },
        "claims": {
            "research_only": True,
            "selection_uses_no_strategy_pnl": True,
            "transfer_evidence_is_not_untouched_oos": True,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }


def build_correlation_panel(
    screen_report: Mapping[str, Any],
    config: CorrelationPanelConfig = CorrelationPanelConfig(),
    *,
    now_epoch_seconds: int | None = None,
) -> dict[str, Any]:
    selected_rows = screen_report.get("selected")
    if not isinstance(selected_rows, list) or not selected_rows:
        raise CorrelationPanelError("compatibility screen contains no selected candidates")
    end = int(now_epoch_seconds if now_epoch_seconds is not None else time.time())
    start = end - config.lookback_hours * 3600
    base = config.rest_base.rstrip("/")

    def candles(symbol: str) -> dict[int, float]:
        query = urlencode({"interval": config.interval, "start": start, "end": end})
        payload = _fetch_json(f"{base}/api/v1/contract/kline/{symbol}?{query}")
        return _kline_closes(payload)

    context = candles(config.context_symbol)
    correlations: dict[str, dict[str, Any]] = {}
    for item in selected_rows:
        if not isinstance(item, Mapping) or not item.get("symbol"):
            continue
        symbol = str(item["symbol"])
        series = candles(symbol)
        left, right = _aligned_returns(series, context)
        correlations[symbol] = {"correlation": _pearson(left, right), "samples": len(left)}
        if config.request_pause_seconds > 0:
            time.sleep(config.request_pause_seconds)

    report = select_panel(screen_report, correlations, config)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["correlation_window"] = {"start_epoch_seconds": start, "end_epoch_seconds": end}
    return report

from __future__ import annotations

import json
import math
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import pandas as pd


class BybitHistoryError(ValueError):
    pass


_INTERVALS = {
    "8h": "480",
    "1d": "D",
}


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _symbol(value: str) -> str:
    return value.upper().replace("_", "")


def _mainnet_fallback_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.hostname != "api.bybit.com":
        return None
    replacement = parts.netloc.replace("api.bybit.com", "api.bytick.com", 1)
    return urlunsplit((parts.scheme, replacement, parts.path, parts.query, parts.fragment))


def _read_json(url: str, *, timeout: float) -> Any:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise BybitHistoryError(f"Bybit public REST returned HTTP {response.status}")
        return response.read(16_000_000)


def _get_json(url: str, *, timeout: float = 20.0) -> Any:
    attempted = [url]
    try:
        raw = _read_json(url, timeout=timeout)
    except HTTPError as exc:
        fallback = _mainnet_fallback_url(url)
        if exc.code != 403 or fallback is None:
            raise
        attempted.append(fallback)
        try:
            raw = _read_json(fallback, timeout=timeout)
        except HTTPError as fallback_exc:
            raise BybitHistoryError(
                "Bybit public REST mainnet endpoints returned HTTP 403: "
                + ", ".join(attempted)
            ) from fallback_exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BybitHistoryError("Bybit public REST response is not valid JSON") from exc
    if not isinstance(payload, dict) or int(payload.get("retCode", -1)) != 0:
        raise BybitHistoryError(f"Bybit public REST response failed: {payload}")
    return payload


def fetch_bybit_linear_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://api.bybit.com",
    limit: int = 1000,
    request_pause_seconds: float = 0.05,
) -> pd.DataFrame:
    if interval not in _INTERVALS:
        raise BybitHistoryError(f"unsupported interval: {interval}")
    if not 1 <= int(limit) <= 1000:
        raise BybitHistoryError("limit must be in [1, 1000]")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise BybitHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    cursor_end = end_ms - 1
    normalized = _symbol(symbol)
    base = rest_base.rstrip("/")
    rows: dict[int, dict[str, float | int]] = {}

    while cursor_end >= start_ms:
        query = urlencode(
            {
                "category": "linear",
                "symbol": normalized,
                "interval": _INTERVALS[interval],
                "start": start_ms,
                "end": cursor_end,
                "limit": int(limit),
            }
        )
        payload = _get_json(f"{base}/v5/market/kline?{query}")
        result = payload.get("result")
        items = result.get("list") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise BybitHistoryError(f"unexpected kline payload for {normalized}")
        if not items:
            break
        times: list[int] = []
        for item in items:
            if not isinstance(item, list) or len(item) < 6:
                continue
            try:
                ts = int(item[0])
                open_ = float(item[1])
                high = float(item[2])
                low = float(item[3])
                close = float(item[4])
                volume = float(item[5])
            except (TypeError, ValueError, IndexError):
                continue
            times.append(ts)
            if not (start_ms <= ts < end_ms):
                continue
            if min(open_, high, low, close) <= 0:
                continue
            if not all(math.isfinite(v) for v in (open_, high, low, close, volume)):
                continue
            rows[ts] = {
                "time": ts,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        if not times:
            break
        oldest = min(times)
        if oldest <= start_ms or len(items) < int(limit):
            break
        next_end = oldest - 1
        if next_end >= cursor_end:
            raise BybitHistoryError(f"kline pagination stalled for {normalized}")
        cursor_end = next_end
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)

    if not rows:
        raise BybitHistoryError(f"no Bybit linear candles for {normalized} {interval}")
    frame = pd.DataFrame([rows[key] for key in sorted(rows)])
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), unit="ms", utc=True)
    return frame.set_index("timestamp").sort_index()


def fetch_bybit_linear_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://api.bybit.com",
    limit: int = 200,
    request_pause_seconds: float = 0.05,
) -> pd.DataFrame:
    if not 1 <= int(limit) <= 200:
        raise BybitHistoryError("funding limit must be in [1, 200]")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise BybitHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    cursor_end = end_ms - 1
    normalized = _symbol(symbol)
    base = rest_base.rstrip("/")
    rows: dict[int, float] = {}

    while cursor_end >= start_ms:
        query = urlencode(
            {
                "category": "linear",
                "symbol": normalized,
                "endTime": cursor_end,
                "limit": int(limit),
            }
        )
        payload = _get_json(f"{base}/v5/market/funding/history?{query}")
        result = payload.get("result")
        items = result.get("list") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise BybitHistoryError(f"unexpected funding payload for {normalized}")
        if not items:
            break
        times: list[int] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                ts = int(item["fundingRateTimestamp"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            times.append(ts)
            if start_ms <= ts < end_ms and math.isfinite(rate):
                rows[ts] = rate
        if not times:
            break
        oldest = min(times)
        if oldest <= start_ms or len(items) < int(limit):
            break
        next_end = oldest - 1
        if next_end >= cursor_end:
            raise BybitHistoryError(f"funding pagination stalled for {normalized}")
        cursor_end = next_end
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)

    if not rows:
        return pd.DataFrame(
            columns=["funding_rate"],
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(list(rows), unit="ms", utc=True),
            "funding_rate": list(rows.values()),
        }
    )
    return frame.set_index("timestamp").sort_index()

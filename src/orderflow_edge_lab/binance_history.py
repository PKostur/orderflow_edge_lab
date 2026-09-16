from __future__ import annotations

import json
import math
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


class BinanceHistoryError(ValueError):
    pass


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _request_json(url: str, timeout: float = 20.0) -> Any:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise BinanceHistoryError(f"Binance public REST returned HTTP {response.status}")
        raw = response.read(32_000_000)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BinanceHistoryError("Binance public REST returned invalid JSON") from exc


def _symbol(value: str) -> str:
    return value.upper().replace("_", "")


def fetch_binance_usdm_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://fapi.binance.com",
    limit: int = 1500,
    request_pause_seconds: float = 0.05,
) -> pd.DataFrame:
    if interval not in {"1h", "8h", "1d"}:
        raise BinanceHistoryError(f"unsupported interval: {interval}")
    if not 1 <= int(limit) <= 1500:
        raise BinanceHistoryError("limit must be between 1 and 1500")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise BinanceHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    cursor = start_ms
    rows: dict[int, list[Any]] = {}
    base = rest_base.rstrip("/")
    normalized = _symbol(symbol)
    while cursor < end_ms:
        query = urlencode(
            {
                "symbol": normalized,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": int(limit),
            }
        )
        payload = _request_json(f"{base}/fapi/v1/klines?{query}")
        if not isinstance(payload, list):
            raise BinanceHistoryError(f"unexpected kline payload for {normalized}: {payload}")
        if not payload:
            break
        last_open = cursor
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                open_ms = int(row[0])
                o, h, l, c, v = (float(row[i]) for i in range(1, 6))
            except (TypeError, ValueError, IndexError):
                continue
            if not start_ms <= open_ms < end_ms:
                continue
            if min(o, h, l, c) <= 0 or not all(math.isfinite(x) for x in (o, h, l, c, v)):
                continue
            rows[open_ms] = row
            last_open = max(last_open, open_ms)
        if len(payload) < int(limit):
            break
        cursor = last_open + 1
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
    if not rows:
        raise BinanceHistoryError(f"no Binance USD-M klines for {normalized} {interval}")
    ordered = [rows[k] for k in sorted(rows)]
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([int(r[0]) for r in ordered], unit="ms", utc=True),
            "open": [float(r[1]) for r in ordered],
            "high": [float(r[2]) for r in ordered],
            "low": [float(r[3]) for r in ordered],
            "close": [float(r[4]) for r in ordered],
            "volume": [float(r[5]) for r in ordered],
        }
    ).set_index("timestamp").sort_index()
    if frame.index.has_duplicates:
        raise BinanceHistoryError(f"duplicate Binance kline timestamps for {normalized}")
    if len(frame) < 100:
        raise BinanceHistoryError(f"insufficient Binance kline history for {normalized}: {len(frame)}")
    return frame


def fetch_binance_usdm_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://fapi.binance.com",
    limit: int = 1000,
    request_pause_seconds: float = 0.05,
) -> pd.DataFrame:
    if not 1 <= int(limit) <= 1000:
        raise BinanceHistoryError("limit must be between 1 and 1000")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise BinanceHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    cursor = start_ms
    normalized = _symbol(symbol)
    base = rest_base.rstrip("/")
    rows: dict[int, float] = {}
    while cursor < end_ms:
        query = urlencode(
            {
                "symbol": normalized,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": int(limit),
            }
        )
        payload = _request_json(f"{base}/fapi/v1/fundingRate?{query}")
        if not isinstance(payload, list):
            raise BinanceHistoryError(f"unexpected funding payload for {normalized}: {payload}")
        if not payload:
            break
        last_time = cursor
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                funding_ms = int(item["fundingTime"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms <= funding_ms < end_ms and math.isfinite(rate):
                rows[funding_ms] = rate
                last_time = max(last_time, funding_ms)
        if len(payload) < int(limit):
            break
        cursor = last_time + 1
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
    if not rows:
        raise BinanceHistoryError(f"no Binance USD-M funding history for {normalized}")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(list(rows), unit="ms", utc=True),
            "funding_rate": list(rows.values()),
        }
    ).set_index("timestamp").sort_index()
    if frame.index.has_duplicates:
        raise BinanceHistoryError(f"duplicate Binance funding timestamps for {normalized}")
    if len(frame) < 100:
        raise BinanceHistoryError(f"insufficient Binance funding history for {normalized}: {len(frame)}")
    return frame

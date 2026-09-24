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


_INTERVAL_MS = {
    "8h": 8 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _symbol(value: str) -> str:
    return value.upper().replace("_", "")


def _get_json(url: str, *, timeout: float = 20.0) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "orderflow-edge-lab/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise BinanceHistoryError(
                f"Binance public REST returned HTTP {response.status}"
            )
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BinanceHistoryError("Binance public REST response is not valid JSON") from exc
    return payload


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
    if interval not in _INTERVAL_MS:
        raise BinanceHistoryError(f"unsupported interval: {interval}")
    if not 1 <= int(limit) <= 1500:
        raise BinanceHistoryError("limit must be in [1, 1500]")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise BinanceHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    step_ms = _INTERVAL_MS[interval]
    cursor = start_ms
    rows: dict[int, dict[str, float | int]] = {}
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
        payload = _get_json(f"{base}/fapi/v1/klines?{query}")
        if not isinstance(payload, list):
            raise BinanceHistoryError(f"unexpected kline payload for {normalized}")
        if not payload:
            break
        last_open: int | None = None
        for item in payload:
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
            last_open = ts if last_open is None else max(last_open, ts)
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
        if last_open is None:
            break
        next_cursor = last_open + step_ms
        if next_cursor <= cursor:
            raise BinanceHistoryError(f"kline pagination stalled for {normalized}")
        cursor = next_cursor
        if len(payload) < int(limit):
            break
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)

    if not rows:
        raise BinanceHistoryError(
            f"no Binance USD-M candles for {normalized} {interval}"
        )
    frame = pd.DataFrame([rows[key] for key in sorted(rows)])
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), unit="ms", utc=True)
    return frame.set_index("timestamp").sort_index()


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
        raise BinanceHistoryError("funding limit must be in [1, 1000]")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise BinanceHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    cursor = start_ms
    rows: dict[int, float] = {}
    normalized = _symbol(symbol)
    base = rest_base.rstrip("/")

    while cursor < end_ms:
        query = urlencode(
            {
                "symbol": normalized,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": int(limit),
            }
        )
        payload = _get_json(f"{base}/fapi/v1/fundingRate?{query}")
        if not isinstance(payload, list):
            raise BinanceHistoryError(f"unexpected funding payload for {normalized}")
        if not payload:
            break
        last_time: int | None = None
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                ts = int(item["fundingTime"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            last_time = ts if last_time is None else max(last_time, ts)
            if start_ms <= ts < end_ms and math.isfinite(rate):
                rows[ts] = rate
        if last_time is None:
            break
        next_cursor = last_time + 1
        if next_cursor <= cursor:
            raise BinanceHistoryError(f"funding pagination stalled for {normalized}")
        cursor = next_cursor
        if len(payload) < int(limit):
            break
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

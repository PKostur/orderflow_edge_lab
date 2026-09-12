from __future__ import annotations

import json
import math
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


class MexcHistoryError(ValueError):
    pass


_INTERVALS: dict[str, tuple[str, int]] = {
    "5m": ("Min5", 5 * 60),
    "15m": ("Min15", 15 * 60),
    "1h": ("Min60", 60 * 60),
    "4h": ("Hour4", 4 * 60 * 60),
    "8h": ("Hour8", 8 * 60 * 60),
    "1d": ("Day1", 24 * 60 * 60),
}


def _as_utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _request_json(url: str, timeout: float = 20.0) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise MexcHistoryError(f"MEXC public REST returned HTTP {response.status}")
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MexcHistoryError("MEXC public REST response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("success") is not True:
        raise MexcHistoryError(f"MEXC public REST response failed: {payload}")
    return payload


def _parse_chunk(payload: Mapping[str, Any]) -> list[dict[str, float | int]]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise MexcHistoryError("MEXC kline data must be an object")
    columns = {name: data.get(name) for name in ("time", "open", "high", "low", "close", "vol")}
    if not all(isinstance(value, list) for value in columns.values()):
        raise MexcHistoryError("MEXC kline arrays are missing")
    lengths = {len(value) for value in columns.values() if isinstance(value, list)}
    if len(lengths) != 1:
        raise MexcHistoryError("MEXC kline arrays have inconsistent lengths")
    rows: list[dict[str, float | int]] = []
    size = next(iter(lengths), 0)
    for index in range(size):
        try:
            ts = int(columns["time"][index])  # type: ignore[index]
            open_ = float(columns["open"][index])  # type: ignore[index]
            high = float(columns["high"][index])  # type: ignore[index]
            low = float(columns["low"][index])  # type: ignore[index]
            close = float(columns["close"][index])  # type: ignore[index]
            volume = float(columns["vol"][index])  # type: ignore[index]
        except (TypeError, ValueError, IndexError):
            continue
        if ts <= 0 or min(open_, high, low, close) <= 0:
            continue
        if not all(math.isfinite(value) for value in (open_, high, low, close, volume)):
            continue
        rows.append({"time": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return rows


def fetch_mexc_futures_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://api.mexc.com",
    chunk_bars: int = 950,
    request_pause_seconds: float = 0.85,
) -> pd.DataFrame:
    if interval not in _INTERVALS:
        raise MexcHistoryError(f"unsupported interval: {interval}")
    if chunk_bars < 100:
        raise MexcHistoryError("chunk_bars must be at least 100")
    mexc_interval, step_seconds = _INTERVALS[interval]
    start_ts = _as_utc(start)
    end_ts = _as_utc(end)
    if end_ts <= start_ts:
        raise MexcHistoryError("end must be after start")
    start_s = int(start_ts.timestamp())
    end_s = int(end_ts.timestamp())
    cursor = start_s
    rows_by_time: dict[int, dict[str, float | int]] = {}
    normalized_symbol = symbol.upper()
    if "_" not in normalized_symbol and normalized_symbol.endswith("USDT"):
        normalized_symbol = normalized_symbol[:-4] + "_USDT"
    base = rest_base.rstrip("/")

    while cursor < end_s:
        chunk_end = min(end_s - 1, cursor + step_seconds * (chunk_bars - 1))
        query = urlencode({"interval": mexc_interval, "start": cursor, "end": chunk_end})
        payload = _request_json(f"{base}/api/v1/contract/kline/{normalized_symbol}?{query}")
        chunk = _parse_chunk(payload)
        for row in chunk:
            ts = int(row["time"])
            if start_s <= ts < end_s:
                rows_by_time[ts] = row
        cursor = chunk_end + step_seconds
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)

    if not rows_by_time:
        raise MexcHistoryError(f"no MEXC historical candles for {normalized_symbol} {interval}")
    ordered = [rows_by_time[key] for key in sorted(rows_by_time)]
    frame = pd.DataFrame(ordered)
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
    frame = frame.set_index("timestamp").sort_index()
    if len(frame) < 200:
        raise MexcHistoryError(f"insufficient MEXC historical candles for {normalized_symbol} {interval}: {len(frame)}")
    return frame

from __future__ import annotations

import json
import math
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


class OkxHistoryError(ValueError):
    pass


_BAR = {
    "1d": "1Dutc",
}


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def okx_swap_instrument(symbol: str) -> str:
    normalized = symbol.upper().replace("-", "_")
    if normalized.endswith("_USDT"):
        base = normalized[:-5]
    elif normalized.endswith("USDT"):
        base = normalized[:-4].rstrip("_")
    else:
        raise OkxHistoryError(f"expected USDT symbol, got {symbol}")
    if not base:
        raise OkxHistoryError(f"invalid symbol: {symbol}")
    return f"{base}-USDT-SWAP"


def _get_json(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "orderflow-edge-lab/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise OkxHistoryError(
                f"OKX public REST returned HTTP {response.status}"
            )
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OkxHistoryError("OKX public REST response is not valid JSON") from exc
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise OkxHistoryError(f"OKX public REST response failed: {payload}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise OkxHistoryError("OKX public REST response data must be a list")
    return payload


def fetch_okx_swap_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://www.okx.com",
    limit: int = 100,
    request_pause_seconds: float = 0.25,
) -> pd.DataFrame:
    if interval not in _BAR:
        raise OkxHistoryError(f"unsupported interval: {interval}")
    if not 1 <= int(limit) <= 100:
        raise OkxHistoryError("OKX history-candle limit must be in [1, 100]")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise OkxHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    inst_id = okx_swap_instrument(symbol)
    base = rest_base.rstrip("/")
    cursor = end_ms
    rows: dict[int, dict[str, float | int]] = {}

    while cursor > start_ms:
        query = urlencode(
            {
                "instId": inst_id,
                "bar": _BAR[interval],
                "after": str(cursor),
                "limit": str(int(limit)),
            }
        )
        payload = _get_json(f"{base}/api/v5/market/history-candles?{query}")
        items = payload["data"]
        if not items:
            break

        times: list[int] = []
        for item in items:
            if not isinstance(item, list) or len(item) < 9:
                continue
            try:
                ts = int(item[0])
                open_ = float(item[1])
                high = float(item[2])
                low = float(item[3])
                close = float(item[4])
                volume = float(item[5])
                confirmed = str(item[8]) == "1"
            except (TypeError, ValueError, IndexError):
                continue
            times.append(ts)
            if not confirmed or not (start_ms <= ts < end_ms):
                continue
            if min(open_, high, low, close) <= 0.0:
                continue
            if not all(
                math.isfinite(value)
                for value in (open_, high, low, close, volume)
            ):
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
        if oldest >= cursor:
            raise OkxHistoryError(f"kline pagination stalled for {inst_id}")
        cursor = oldest
        if request_pause_seconds > 0.0:
            time.sleep(request_pause_seconds)

    if not rows:
        raise OkxHistoryError(f"no OKX swap candles for {inst_id} {interval}")
    frame = pd.DataFrame([rows[key] for key in sorted(rows)])
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), unit="ms", utc=True)
    return frame.set_index("timestamp").sort_index()


def fetch_okx_swap_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    rest_base: str = "https://www.okx.com",
    limit: int = 400,
    request_pause_seconds: float = 0.25,
) -> pd.DataFrame:
    if not 1 <= int(limit) <= 400:
        raise OkxHistoryError("OKX funding-history limit must be in [1, 400]")
    start_ts, end_ts = _utc(start), _utc(end)
    if end_ts <= start_ts:
        raise OkxHistoryError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    inst_id = okx_swap_instrument(symbol)
    base = rest_base.rstrip("/")
    cursor = end_ms
    rows: dict[int, float] = {}

    while cursor > start_ms:
        query = urlencode(
            {
                "instId": inst_id,
                "after": str(cursor),
                "limit": str(int(limit)),
            }
        )
        payload = _get_json(
            f"{base}/api/v5/public/funding-rate-history?{query}"
        )
        items = payload["data"]
        if not items:
            break

        times: list[int] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                ts = int(item["fundingTime"])
            except (KeyError, TypeError, ValueError):
                continue
            times.append(ts)
            raw_rate = item.get("realizedRate")
            if raw_rate in (None, ""):
                continue
            try:
                rate = float(raw_rate)
            except (TypeError, ValueError):
                continue
            if start_ms <= ts < end_ms and math.isfinite(rate):
                rows[ts] = rate

        if not times:
            break
        oldest = min(times)
        if oldest <= start_ms or len(items) < int(limit):
            break
        if oldest >= cursor:
            raise OkxHistoryError(f"funding pagination stalled for {inst_id}")
        cursor = oldest
        if request_pause_seconds > 0.0:
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

from __future__ import annotations

import json
import math
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


class BitgetPublicDataError(ValueError):
    pass


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _symbol(symbol: str) -> str:
    return symbol.upper().replace("_", "")


def _get_json(url: str, timeout: float = 30.0) -> Mapping[str, Any]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise BitgetPublicDataError(f"Bitget public REST returned HTTP {response.status}")
        raw = response.read(16_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BitgetPublicDataError("Bitget public REST returned invalid JSON") from exc
    if not isinstance(payload, Mapping) or str(payload.get("code")) != "00000":
        raise BitgetPublicDataError(f"Bitget public REST failed: {payload}")
    return payload


def fetch_bitget_usdt_futures_klines(
    symbol: str,
    start: str,
    end: str,
    *,
    request_pause_seconds: float = 0.10,
) -> pd.DataFrame:
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    if end_ms <= start_ms:
        raise BitgetPublicDataError("end must be after start")
    query = urlencode({
        "category": "USDT-FUTURES",
        "symbol": _symbol(symbol),
        "interval": "1D",
        "startTime": start_ms,
        "endTime": end_ms - 1,
        "type": "market",
        "limit": 1000,
    })
    payload = _get_json(f"https://api.bitget.com/api/v3/market/history-candles?{query}")
    items = payload.get("data")
    if not isinstance(items, list) or not items:
        raise BitgetPublicDataError(f"no Bitget USDT futures candles for {_symbol(symbol)}")
    rows: dict[int, list[Any]] = {}
    for row in items:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            ts = int(row[0])
            o, h, l, c, v = (float(row[i]) for i in range(1, 6))
        except (TypeError, ValueError, IndexError):
            continue
        if start_ms <= ts < end_ms and min(o, h, l, c) > 0 and all(math.isfinite(x) for x in (o, h, l, c, v)):
            rows[ts] = row
    if not rows:
        raise BitgetPublicDataError(f"no usable Bitget daily candles for {symbol}")
    ordered = [rows[key] for key in sorted(rows)]
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([int(r[0]) for r in ordered], unit="ms", utc=True),
        "open": [float(r[1]) for r in ordered],
        "high": [float(r[2]) for r in ordered],
        "low": [float(r[3]) for r in ordered],
        "close": [float(r[4]) for r in ordered],
        "volume": [float(r[5]) for r in ordered],
    }).set_index("timestamp").sort_index()
    if len(frame) < 20:
        raise BitgetPublicDataError(f"insufficient Bitget daily candles for {symbol}: {len(frame)}")
    if request_pause_seconds > 0:
        time.sleep(request_pause_seconds)
    return frame


def fetch_bitget_funding_history(
    symbol: str,
    start: str,
    end: str,
    *,
    request_pause_seconds: float = 0.10,
    max_pages: int = 60,
) -> pd.DataFrame:
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    rows: dict[int, float] = {}
    for page in range(1, int(max_pages) + 1):
        query = urlencode({
            "symbol": _symbol(symbol),
            "productType": "usdt-futures",
            "pageSize": 100,
            "pageNo": page,
        })
        payload = _get_json(f"https://api.bitget.com/api/v2/mix/market/history-fund-rate?{query}")
        items = payload.get("data")
        if not isinstance(items, list) or not items:
            break
        oldest = None
        for item in items:
            if not isinstance(item, Mapping):
                continue
            try:
                ts = int(item["fundingTime"])
                rate = float(item["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            oldest = ts if oldest is None else min(oldest, ts)
            if start_ms <= ts < end_ms and math.isfinite(rate):
                rows[ts] = rate
        if oldest is not None and oldest <= start_ms:
            break
        if len(items) < 100:
            break
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
    if not rows:
        return pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime(list(rows), unit="ms", utc=True),
        "funding_rate": list(rows.values()),
    })
    return frame.set_index("timestamp").sort_index()


def load_symbol_dataset_bitget(symbol: str, start: str, end: str) -> dict[str, pd.DataFrame]:
    warmup_start = (_utc(start) - pd.Timedelta(days=14)).isoformat()
    return {
        "mexc_prices": fetch_mexc_futures_klines(symbol, "1d", warmup_start, end),
        "binance_prices": fetch_bitget_usdt_futures_klines(symbol, warmup_start, end),
        "mexc_funding": fetch_mexc_funding_history(symbol, warmup_start, end),
        "binance_funding": fetch_bitget_funding_history(symbol, warmup_start, end),
    }

from __future__ import annotations

import json
import time
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

URL = "https://api.hyperliquid.xyz/info"
ALIAS = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}


class HyperliquidHistoryError(ValueError):
    pass


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _post(body: dict[str, Any], timeout: float = 30) -> Any:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(5):
        try:
            request = Request(
                URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "orderflow-edge-lab/1.0",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except Exception:
            # includes HTTP 429; back off and retry
            if attempt == 4:
                raise
            time.sleep(2.0 * (attempt + 1))


def hyperliquid_coin(symbol: str, names: set[str] | list[str]) -> str | None:
    base = symbol.upper()
    if base.endswith("_USDT"):
        base = base[:-5]
    elif base.endswith("USDT"):
        base = base[:-4].rstrip("_")
    base = ALIAS.get(base, base)
    available = set(names)
    if base in available:
        return base
    if "k" + base in available:
        return "k" + base
    return None


def fetch_hyperliquid_candles(
    coin: str, interval: str, start: str | pd.Timestamp, end: str | pd.Timestamp
) -> pd.DataFrame:
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    rows: dict[int, list[float]] = {}
    cursor = start_ms
    while cursor < end_ms:
        data = _post(
            {
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval, "startTime": cursor, "endTime": end_ms},
            }
        )
        if not data:
            break
        last = max(int(c["t"]) for c in data)
        for c in data:
            if int(c["T"]) < end_ms:
                rows[int(c["t"])] = [float(c[k]) for k in ("o", "h", "l", "c", "v")]
        if last + 1 <= cursor:
            break
        cursor = last + 1
    frame = pd.DataFrame.from_dict(
        rows, orient="index", columns=["open", "high", "low", "close", "volume"], dtype=float
    ).sort_index()
    frame.index = pd.to_datetime(frame.index, unit="ms", utc=True).rename("timestamp")
    return frame[frame["volume"] > 0.0]


def fetch_hyperliquid_funding(
    coin: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    request_pause_seconds: float = 0.15,
) -> pd.Series:
    start_ms = int(_utc(start).timestamp() * 1000)
    end_ms = int(_utc(end).timestamp() * 1000)
    rows: dict[int, float] = {}
    cursor = start_ms
    while cursor < end_ms:
        data = _post({"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms})
        if request_pause_seconds > 0.0:
            time.sleep(request_pause_seconds)
        if not data:
            break
        last = max(int(r["time"]) for r in data)
        for r in data:
            if int(r["time"]) < end_ms:
                rows[int(r["time"])] = float(r["fundingRate"])
        if last + 1 <= cursor:
            break
        cursor = last + 1
    series = pd.Series(rows, dtype=float).sort_index()
    series.index = pd.to_datetime(series.index, unit="ms", utc=True).rename("timestamp")
    return series

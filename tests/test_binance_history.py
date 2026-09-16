from __future__ import annotations

import pandas as pd

import orderflow_edge_lab.binance_history as bh


def test_binance_usdm_kline_normalization(monkeypatch) -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    for i in range(120):
        ts = int((start + pd.Timedelta(days=i)).timestamp() * 1000)
        px = 100.0 + i
        rows.append([ts, str(px), str(px + 2), str(px - 2), str(px + 1), "10.0"])
    monkeypatch.setattr(bh, "_request_json", lambda url, timeout=20.0: rows)
    frame = bh.fetch_binance_usdm_klines(
        "BTC_USDT",
        "1d",
        "2026-01-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
        request_pause_seconds=0.0,
    )
    assert len(frame) == 120
    assert frame.index.is_monotonic_increasing
    assert not frame.index.has_duplicates
    assert frame.index.tz is not None
    assert float(frame.iloc[0]["open"]) == 100.0
    assert float(frame.iloc[-1]["close"]) == 220.0


def test_binance_usdm_funding_normalization(monkeypatch) -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    items = []
    for i in range(120):
        ts = int((start + pd.Timedelta(hours=8 * i)).timestamp() * 1000)
        items.append({"symbol": "BTCUSDT", "fundingTime": ts, "fundingRate": str(0.0001 + i * 1e-8)})
    monkeypatch.setattr(bh, "_request_json", lambda url, timeout=20.0: items)
    frame = bh.fetch_binance_usdm_funding_history(
        "BTC_USDT",
        "2026-01-01T00:00:00Z",
        "2026-03-01T00:00:00Z",
        request_pause_seconds=0.0,
    )
    assert len(frame) == 120
    assert frame.index.is_monotonic_increasing
    assert not frame.index.has_duplicates
    assert float(frame.iloc[0]["funding_rate"]) == 0.0001

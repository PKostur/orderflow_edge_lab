from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .mexc_history import fetch_mexc_futures_klines
from .session_metrics import analyze_bar_sessions


@dataclass(frozen=True)
class MexcSessionStudyConfig:
    symbols: tuple[str, ...] = ("ENA_USDT", "BTC_USDT")
    interval: str = "15m"
    lookback_days: int = 30


def _frame_rows(frame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ts, row in frame.iterrows():
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    return rows


def run_mexc_session_study(
    start: str,
    end: str,
    cfg: MexcSessionStudyConfig = MexcSessionStudyConfig(),
) -> dict[str, Any]:
    symbol_reports: dict[str, Any] = {}
    for symbol in cfg.symbols:
        frame = fetch_mexc_futures_klines(symbol, cfg.interval, start, end)
        rows = _frame_rows(frame)
        symbol_reports[symbol] = {
            "bars": len(rows),
            "first_timestamp": rows[0]["timestamp"] if rows else None,
            "last_timestamp": rows[-1]["timestamp"] if rows else None,
            "session_metrics": analyze_bar_sessions(rows),
        }
    return {
        "schema_version": 1,
        "analysis": "mexc_futures_trading_sessions",
        "source": "MEXC public futures klines",
        "interval": cfg.interval,
        "start": start,
        "end": end,
        "symbols": symbol_reports,
        "claims": {
            "descriptive_only": True,
            "strategy_filter_authorized": False,
            "verified_out_of_sample_edge": False,
            "live_order_transmission_supported": False,
        },
    }

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


class OrderFlowBacktestError(ValueError):
    pass


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str = "ENA_USDT"
    context_symbol: str = "BTC_USDT"
    horizons_ms: tuple[int, ...] = (1_000, 5_000, 15_000, 30_000)
    fee_bps_round_trip: tuple[float, ...] = (0.0, 4.0, 8.0)
    min_trade_count: int = 5
    min_trade_flow_ratio: float = 0.25
    min_book_imbalance: float = 0.25
    min_microprice_edge: float = 0.20
    cooldown_ms: int = 2_000


def _load(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_ts: dict[str, int] = {}
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OrderFlowBacktestError(f"invalid JSON on line {line_no}") from exc
            if not isinstance(row, dict):
                raise OrderFlowBacktestError(f"line {line_no} is not an object")
            ts = row.get("exchange_ts_ms")
            symbol = row.get("symbol")
            if ts is None or not symbol:
                continue
            try:
                ts_i = int(ts)
            except (TypeError, ValueError) as exc:
                raise OrderFlowBacktestError(f"invalid timestamp on line {line_no}") from exc
            if symbol in last_ts and ts_i < last_ts[symbol]:
                raise OrderFlowBacktestError(f"timestamp regression for {symbol} on line {line_no}")
            last_ts[symbol] = ts_i
            row = dict(row)
            row["exchange_ts_ms"] = ts_i
            rows.append(row)
    if not rows:
        raise OrderFlowBacktestError("no timestamped feature rows")
    rows.sort(key=lambda r: (r["exchange_ts_ms"], str(r.get("symbol", "")), str(r.get("event_type", ""))))
    return rows


def _flow_ratio(row: dict[str, Any]) -> float | None:
    buy = row.get("rolling_buy_volume")
    sell = row.get("rolling_sell_volume")
    if buy is None or sell is None:
        return None
    total = float(buy) + float(sell)
    if total <= 0:
        return None
    return (float(buy) - float(sell)) / total


def _book_imbalance(row: dict[str, Any]) -> float | None:
    for key, value in row.items():
        if key.startswith("book_imbalance_") and value is not None:
            return float(value)
    return None


def _micro_edge(row: dict[str, Any]) -> float | None:
    bid, ask, micro = row.get("best_bid"), row.get("best_ask"), row.get("microprice")
    if bid is None or ask is None or micro is None:
        return None
    bid, ask, micro = float(bid), float(ask), float(micro)
    spread = ask - bid
    if spread <= 0:
        return None
    mid = (bid + ask) / 2.0
    return (micro - mid) / (spread / 2.0)


def _side_from_sign(value: float, threshold: float) -> int:
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0


def _latest_context(rows: list[dict[str, Any]], symbol: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for row in rows:
        if row.get("symbol") != symbol or row.get("event_type") != "trade":
            continue
        ratio = _flow_ratio(row)
        if ratio is None:
            continue
        side = _side_from_sign(ratio, 0.10)
        out.append((row["exchange_ts_ms"], side))
    return out


def _context_side(context: list[tuple[int, int]], ts: int) -> int:
    latest = 0
    for event_ts, side in context:
        if event_ts > ts:
            break
        latest = side
    return latest


def candidate_signals(rows: list[dict[str, Any]], cfg: BacktestConfig) -> list[dict[str, Any]]:
    context = _latest_context(rows, cfg.context_symbol)
    last_signal: dict[str, int] = {}
    signals: list[dict[str, Any]] = []
    for row in rows:
        if row.get("symbol") != cfg.symbol or row.get("event_type") != "trade":
            continue
        ts = row["exchange_ts_ms"]
        count = int(row.get("rolling_trade_count") or 0)
        flow = _flow_ratio(row)
        book = _book_imbalance(row)
        micro = _micro_edge(row)
        btc = _context_side(context, ts)
        families: list[tuple[str, int]] = []
        if count >= cfg.min_trade_count and flow is not None:
            families.append(("cvd", _side_from_sign(flow, cfg.min_trade_flow_ratio)))
        if book is not None:
            families.append(("book", _side_from_sign(book, cfg.min_book_imbalance)))
        if micro is not None:
            families.append(("microprice", _side_from_sign(micro, cfg.min_microprice_edge)))
        if count >= cfg.min_trade_count and flow is not None and book is not None and micro is not None:
            parts = [
                _side_from_sign(flow, cfg.min_trade_flow_ratio),
                _side_from_sign(book, cfg.min_book_imbalance),
                _side_from_sign(micro, cfg.min_microprice_edge),
            ]
            if parts[0] and parts[0] == parts[1] == parts[2]:
                families.append(("aligned", parts[0]))
                if btc == parts[0]:
                    families.append(("aligned_btc", parts[0]))
        for family, side in families:
            if side == 0:
                continue
            key = f"{family}:{side}"
            if ts - last_signal.get(key, -10**18) < cfg.cooldown_ms:
                continue
            bid, ask = row.get("best_bid"), row.get("best_ask")
            if bid is None or ask is None or float(ask) <= float(bid):
                continue
            signals.append({
                "family": family,
                "side": side,
                "signal_ts_ms": ts,
                "entry_price": float(ask) if side > 0 else float(bid),
                "signal_bid": float(bid),
                "signal_ask": float(ask),
                "flow_ratio": flow,
                "book_imbalance": book,
                "microprice_edge": micro,
                "btc_flow_side": btc,
            })
            last_signal[key] = ts
    return signals


def _quote_rows(rows: list[dict[str, Any]], symbol: str) -> list[tuple[int, float, float]]:
    out: list[tuple[int, float, float]] = []
    for row in rows:
        if row.get("symbol") != symbol:
            continue
        bid, ask = row.get("best_bid"), row.get("best_ask")
        if bid is None or ask is None:
            continue
        bid_f, ask_f = float(bid), float(ask)
        if math.isfinite(bid_f) and math.isfinite(ask_f) and 0 < bid_f < ask_f:
            out.append((row["exchange_ts_ms"], bid_f, ask_f))
    return out


def _first_quote_at_or_after(quotes: list[tuple[int, float, float]], target: int) -> tuple[int, float, float] | None:
    lo, hi = 0, len(quotes)
    while lo < hi:
        mid = (lo + hi) // 2
        if quotes[mid][0] < target:
            lo = mid + 1
        else:
            hi = mid
    return quotes[lo] if lo < len(quotes) else None


def evaluate(path: str | Path, cfg: BacktestConfig = BacktestConfig()) -> dict[str, Any]:
    rows = _load(path)
    signals = candidate_signals(rows, cfg)
    quotes = _quote_rows(rows, cfg.symbol)
    observations: list[dict[str, Any]] = []
    for signal in signals:
        for horizon in cfg.horizons_ms:
            quote = _first_quote_at_or_after(quotes, signal["signal_ts_ms"] + horizon)
            if quote is None:
                continue
            exit_ts, bid, ask = quote
            exit_price = bid if signal["side"] > 0 else ask
            gross = signal["side"] * (exit_price / signal["entry_price"] - 1.0) * 10_000.0
            base = {**signal, "horizon_ms": horizon, "exit_ts_ms": exit_ts, "exit_price": exit_price, "gross_bps": gross}
            for fee in cfg.fee_bps_round_trip:
                observations.append({**base, "fee_bps_round_trip": fee, "net_bps": gross - fee})

    groups: dict[tuple[str, int, float], list[dict[str, Any]]] = {}
    for row in observations:
        groups.setdefault((row["family"], row["horizon_ms"], row["fee_bps_round_trip"]), []).append(row)
    summary: list[dict[str, Any]] = []
    for (family, horizon, fee), group in sorted(groups.items()):
        nets = [float(x["net_bps"]) for x in group]
        gross = [float(x["gross_bps"]) for x in group]
        if not nets:
            continue
        mean = sum(nets) / len(nets)
        wins = sum(x > 0 for x in nets)
        summary.append({
            "family": family,
            "horizon_ms": horizon,
            "fee_bps_round_trip": fee,
            "observations": len(nets),
            "gross_mean_bps": sum(gross) / len(gross),
            "net_mean_bps": mean,
            "net_win_rate": wins / len(nets),
            "net_total_bps": sum(nets),
        })

    return {
        "schema_version": 1,
        "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "config": {
            "symbol": cfg.symbol,
            "context_symbol": cfg.context_symbol,
            "horizons_ms": list(cfg.horizons_ms),
            "fee_bps_round_trip": list(cfg.fee_bps_round_trip),
            "min_trade_count": cfg.min_trade_count,
            "min_trade_flow_ratio": cfg.min_trade_flow_ratio,
            "min_book_imbalance": cfg.min_book_imbalance,
            "min_microprice_edge": cfg.min_microprice_edge,
            "cooldown_ms": cfg.cooldown_ms,
        },
        "feature_rows": len(rows),
        "signals": len(signals),
        "summary": summary,
        "observations": observations,
        "claims": {
            "exploratory_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

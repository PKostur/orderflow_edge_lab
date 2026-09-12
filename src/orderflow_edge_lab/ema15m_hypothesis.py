from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class EMAHypothesisError(ValueError):
    pass


def _deps():
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise EMAHypothesisError("EMA historical test requires optional research dependencies: pip install numpy pandas") from exc
    return np, pd


def _utc(value, pd):
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _load_csv(path: str | Path, start, end, pd, np):
    d = pd.read_csv(path)
    required = ["timestamp", "open", "high", "low", "close"]
    if not set(required) <= set(d):
        raise EMAHypothesisError(f"{path}: required columns {required}")
    t = d.pop("timestamp")
    if pd.api.types.is_numeric_dtype(t):
        t = pd.to_datetime(t, unit="ms" if t.abs().median() > 1e11 else "s", utc=True)
    else:
        t = pd.to_datetime(t, utc=True, errors="raise")
    d.index = pd.DatetimeIndex(t)
    d = d[["open", "high", "low", "close"]].astype(float).sort_index()
    if d.index.has_duplicates:
        raise EMAHypothesisError(f"{path}: duplicate timestamps")
    d = d.loc[(d.index >= start) & (d.index < end)]
    expected = pd.date_range(start, end, freq="min", inclusive="left")
    if not d.index.equals(expected):
        missing = expected.difference(d.index)
        raise EMAHypothesisError(f"{path}: incomplete/misaligned minute data; missing {len(missing)}")
    if not np.isfinite(d.to_numpy()).all() or (d <= 0).any().any():
        raise EMAHypothesisError(f"{path}: invalid prices")
    return d


def _wilder(values, length: int, np):
    result = np.full(len(values), np.nan)
    if len(values) >= length:
        result[length - 1] = np.mean(values[:length])
        for i in range(length, len(values)):
            result[i] = (result[i - 1] * (length - 1) + values[i]) / length
    return result


def _features(ena, btc, pd, np, atr_length: int = 14):
    minute = pd.Timedelta(minutes=1)
    d = ena.copy()
    basis = d.close.rolling(20).mean()
    dev = 2 * d.close.rolling(20).std(ddof=0)
    d["lower"], d["upper"] = basis - dev, basis + dev
    prev = d.close.shift()
    tr = pd.concat([d.high - d.low, (d.high - prev).abs(), (d.low - prev).abs()], axis=1).max(axis=1)
    d["atr"] = _wilder(tr.to_numpy(), atr_length, np)
    close_times = d.index + minute
    scores = []
    for minutes, threshold in [(1, 0.02), (5, 0.05), (15, 0.10)]:
        grouped = btc.close.resample(f"{minutes}min", origin="epoch", closed="left", label="left")
        closes = grouped.last().where(grouped.count() == minutes)
        closes.index = closes.index + pd.Timedelta(minutes=minutes)
        moves = closes.pct_change(fill_method=None) * 100
        aligned = moves.reindex(close_times, method="ffill")
        values = aligned.to_numpy()
        scores.append(np.where(np.isfinite(values), (values > threshold).astype(int) - (values < -threshold).astype(int), np.nan))
    d["score"] = np.sum(scores, axis=0)
    d["correlation"] = np.log(ena.close).diff().rolling(60).corr(np.log(btc.close).diff())
    return d


def _add_ema15m_bias(d, pd, np):
    d = d.copy()
    minute = pd.Timedelta(minutes=1)
    availability = d.index + minute
    grouped = d.close.resample("15min", origin="epoch", closed="left", label="left")
    closes = grouped.last().where(grouped.count() == 15)
    ema20 = closes.ewm(span=20, adjust=False, min_periods=20).mean()
    ema50 = closes.ewm(span=50, adjust=False, min_periods=50).mean()
    bias = pd.Series(np.where(ema20 > ema50, 1, np.where(ema20 < ema50, -1, 0)), index=closes.index, dtype=float)
    bias = bias.where(ema20.notna() & ema50.notna())
    bias.index = bias.index + pd.Timedelta(minutes=15)
    d["ema15m_20_50_bias"] = bias.reindex(availability, method="ffill").to_numpy()
    return d


def _resolve(direction: int, low: float, high: float, stop: float, target: float):
    stop_hit = low <= stop if direction == 1 else high >= stop
    target_hit = high >= target if direction == 1 else low <= target
    if stop_hit:
        return -1.0, bool(target_hit)
    if target_hit:
        return 3.0, False
    return None, False


def _simulate(d, start, end, *, use_ema_filter: bool, tick_size: float, pd, np):
    minute = pd.Timedelta(minutes=1)
    active = None
    records = []
    candidates = 0
    subset = d.loc[(d.index >= start) & (d.index < end)]
    for t, row in subset.iterrows():
        if active is not None:
            outcome, ambiguous = _resolve(active["direction"], row.low, row.high, active["stop"], active["target"])
            if outcome is not None:
                records.append({**active, "exit_time": t + minute, "gross_r": outcome, "status": "resolved", "ambiguous": ambiguous})
                active = None
            continue
        if not np.isfinite(row.atr) or not np.isfinite(row.score):
            continue
        allow_long = not use_ema_filter or row.ema15m_20_50_bias == 1
        allow_short = not use_ema_filter or row.ema15m_20_50_bias == -1
        long = row.low < row.lower and row.close > row.lower and row.score >= 1 and allow_long
        short = row.high > row.upper and row.close < row.upper and -row.score >= 1 and allow_short
        if long == short:
            continue
        candidates += 1
        direction = 1 if long else -1
        stop = row.low - 0.10 * row.atr if long else row.high + 0.10 * row.atr
        risk = direction * (row.close - stop)
        if risk <= tick_size:
            continue
        active = {
            "entry_time": t + minute,
            "direction": direction,
            "entry": float(row.close),
            "stop": float(stop),
            "target": float(row.close + direction * 3 * risk),
            "stop_pct": float(100 * risk / row.close),
        }
    if active is not None:
        risk = abs(active["entry"] - active["stop"])
        mtm = active["direction"] * (subset.iloc[-1].close - active["entry"]) / risk
        records.append({**active, "exit_time": end, "gross_r": float(mtm), "status": "expired", "ambiguous": False})
    return records, candidates


def _metrics(records, cost_pct: float):
    np, _ = _deps()
    resolved = [row for row in records if row["status"] == "resolved"]
    if not resolved:
        return {"trades": 0, "net_pf": None, "net_exp_r": None, "net_r": 0.0, "max_closed_trade_drawdown_r": 0.0}
    gross = np.array([float(row["gross_r"]) for row in resolved])
    stop_pct = np.array([float(row["stop_pct"]) for row in resolved])
    friction = cost_pct / stop_pct
    net = gross - friction
    profit = net[net > 0].sum()
    loss = -net[net < 0].sum()
    curve = np.r_[0, np.cumsum(net)]
    return {
        "trades": int(len(net)),
        "net_pf": float(profit / loss) if loss else ("INF" if profit else None),
        "gross_exp_r": float(gross.mean()),
        "net_exp_r": float(net.mean()),
        "net_r": float(net.sum()),
        "avg_cost_r": float(friction.mean()),
        "max_closed_trade_drawdown_r": float((np.maximum.accumulate(curve) - curve).max()),
    }


def evaluate_ema15m_hypothesis(
    ena_csv: str | Path,
    btc_csv: str | Path,
    *,
    start: str = "2026-08-09",
    split: str = "2026-08-18",
    end: str = "2026-08-28",
    tick_size: float = 0.00001,
    atr_length: int = 14,
    costs_pct: tuple[float, ...] = (0.0, 0.04, 0.06, 0.08),
) -> dict[str, Any]:
    np, pd = _deps()
    start_t, split_t, end_t = (_utc(value, pd) for value in (start, split, end))
    if not start_t < split_t < end_t:
        raise EMAHypothesisError("require start < split < end")
    warm = start_t - pd.Timedelta(days=1)
    ena = _load_csv(ena_csv, warm, end_t, pd, np)
    btc = _load_csv(btc_csv, warm, end_t, pd, np)
    d = _add_ema15m_bias(_features(ena, btc, pd, np, atr_length), pd, np)
    if d.loc[d.index >= start_t, "ema15m_20_50_bias"].isna().any():
        raise EMAHypothesisError("EMA50 warm-up incomplete")
    results = []
    ledgers = {}
    for variant, use_filter in (("baseline", False), ("ema15m_20_50", True)):
        ledgers[variant] = []
        for period, a, b in (("discovery", start_t, split_t), ("validation", split_t, end_t)):
            records, candidates = _simulate(d, a, b, use_ema_filter=use_filter, tick_size=tick_size, pd=pd, np=np)
            ledgers[variant].extend({"period": period, **row} for row in records)
            for cost_pct in costs_pct:
                results.append({
                    "variant": variant,
                    "period": period,
                    "cost_pct_round_trip": cost_pct,
                    "candidates": candidates,
                    "expired": sum(row["status"] == "expired" for row in records),
                    **_metrics(records, cost_pct),
                })
    return {
        "schema_version": 1,
        "experiment": "historical_15m_ema20_50_hypothesis",
        "hypothesis_status": "user-recalled indicator result not independently verified from prior TradingView artifacts; tested here as a new hypothesis",
        "ema_rule": "completed 15-minute EMA20 > EMA50 permits longs; EMA20 < EMA50 permits shorts; no unclosed 15-minute candle is used",
        "base_strategy": "preserved ENA Bollinger20x2 + BTC 1m/5m/15m direction score, ATR14 structural stop, 3R target, one position, stop-first tie handling",
        "execution_model": "signal-close entry; exits begin on next 1-minute bar; historical bar model, not order-book execution",
        "start": str(start_t),
        "split": str(split_t),
        "end": str(end_t),
        "ena_sha256": hashlib.sha256(Path(ena_csv).read_bytes()).hexdigest(),
        "btc_sha256": hashlib.sha256(Path(btc_csv).read_bytes()).hexdigest(),
        "costs_pct_round_trip": list(costs_pct),
        "results": results,
        "ledgers": ledgers,
        "claims": {
            "development_data_already_inspected": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

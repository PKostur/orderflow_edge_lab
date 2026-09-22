from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import generate_target_position


class EvidenceSessionAuditError(ValueError):
    pass


def _load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        raise EvidenceSessionAuditError(f"{path}: missing timestamp")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise EvidenceSessionAuditError(f"{path}: missing columns {sorted(missing)}")
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=sorted(required))
    if frame.empty:
        raise EvidenceSessionAuditError(f"{path}: no valid rows")
    return frame


def load_interval_frames(data_dir: str | Path, interval: str) -> dict[str, pd.DataFrame]:
    root = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(root.glob(f"*_{interval}.csv")):
        symbol = path.name[: -len(f"_{interval}.csv")]
        frames[symbol] = _load_frame(path)
    if not frames:
        raise EvidenceSessionAuditError(f"no {interval} frames in {root}")
    return frames


def _bucket_name(hour: int, buckets: list[Mapping[str, Any]]) -> str:
    for bucket in buckets:
        start = int(bucket["start_utc_hour"])
        end = int(bucket["end_utc_hour"])
        if start <= hour < end:
            return str(bucket["name"])
    raise EvidenceSessionAuditError(f"hour {hour} is outside declared session buckets")


def _extract_trades(
    frame: pd.DataFrame,
    *,
    symbol: str,
    family: str,
    params: Mapping[str, Any],
    round_trip_cost_bps: float,
    buckets: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    target = generate_target_position(frame, family, params).reindex(frame.index).fillna(0.0).clip(-1.0, 1.0)
    position = target.shift(1).fillna(0.0)
    opens = frame["open"].astype(float)
    trades: list[dict[str, Any]] = []
    i = 0
    n = len(frame)
    rt_cost = float(round_trip_cost_bps) / 10_000.0

    while i < n - 1:
        side = float(position.iloc[i])
        if side == 0.0:
            i += 1
            continue
        j = i
        compounded = 1.0
        while j < n - 1 and float(position.iloc[j]) == side:
            compounded *= 1.0 + side * (float(opens.iloc[j + 1]) / float(opens.iloc[j]) - 1.0)
            j += 1

        entry_price = float(opens.iloc[i])
        held = frame.iloc[i:j]
        if side > 0:
            mfe = max(0.0, float(held["high"].max()) / entry_price - 1.0) if len(held) else 0.0
            mae = min(0.0, float(held["low"].min()) / entry_price - 1.0) if len(held) else 0.0
        else:
            mfe = max(0.0, 1.0 - float(held["low"].min()) / entry_price) if len(held) else 0.0
            mae = min(0.0, 1.0 - float(held["high"].max()) / entry_price) if len(held) else 0.0

        gross = compounded - 1.0
        net = gross - rt_cost
        entry = frame.index[i]
        trades.append(
            {
                "symbol": symbol,
                "entry": entry.isoformat(),
                "exit": frame.index[j].isoformat(),
                "entry_epoch_ns": int(entry.value),
                "entry_year": int(entry.year),
                "entry_hour_utc": int(entry.hour),
                "session_bucket": _bucket_name(int(entry.hour), buckets),
                "side": int(side),
                "bars_held": int(j - i),
                "gross_bps": gross * 10_000.0,
                "net_bps": net * 10_000.0,
                "mfe_bps": mfe * 10_000.0,
                "mae_bps": mae * 10_000.0,
            }
        )
        i = j
    return trades


def _pf(values: list[float]) -> float | str | None:
    positive = sum(v for v in values if v > 0.0)
    negative = -sum(v for v in values if v < 0.0)
    if negative > 0.0:
        return positive / negative
    return "INF" if positive > 0.0 else None


def _max_drawdown(values: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return worst


def _summarize(
    rows: list[dict[str, Any]],
    *,
    fold_start: pd.Timestamp,
    fold_days: int,
) -> dict[str, Any]:
    if not rows:
        return {"trades": 0}
    rows = sorted(rows, key=lambda r: (int(r["entry_epoch_ns"]), str(r["symbol"])))
    values = [float(r["net_bps"]) for r in rows]
    winners = [v for v in values if v > 0.0]
    losers = [v for v in values if v <= 0.0]

    symbol_ev: dict[str, list[float]] = defaultdict(list)
    fold_ev: dict[int, list[float]] = defaultdict(list)
    year_ev: dict[int, list[float]] = defaultdict(list)
    timestamp_net: dict[int, float] = defaultdict(float)
    for row in rows:
        value = float(row["net_bps"])
        symbol_ev[str(row["symbol"])].append(value)
        entry = pd.Timestamp(row["entry"])
        fold = int((entry - fold_start) / pd.Timedelta(days=int(fold_days)))
        fold_ev[fold].append(value)
        year_ev[int(row["entry_year"])].append(value)
        timestamp_net[int(row["entry_epoch_ns"])] += value

    symbol_means = [statistics.fmean(v) for v in symbol_ev.values()]
    fold_means = [statistics.fmean(v) for _, v in sorted(fold_ev.items())]
    years = {str(year): statistics.fmean(vals) for year, vals in sorted(year_ev.items())}
    path_values = [value for _, value in sorted(timestamp_net.items())]

    mfe = [float(r["mfe_bps"]) for r in rows]
    mae = [float(r["mae_bps"]) for r in rows]
    positive_total = sum(winners)
    ranked_winners = sorted(winners, reverse=True)

    return {
        "trades": len(rows),
        "cumulative_net_bps": sum(values),
        "net_expectancy_bps": statistics.fmean(values),
        "median_net_bps": statistics.median(values),
        "win_rate": len(winners) / len(values),
        "average_net_win_bps": statistics.fmean(winners) if winners else None,
        "average_net_loss_bps": statistics.fmean(losers) if losers else None,
        "profit_factor": _pf(values),
        "timestamp_cluster_max_drawdown_bps": _max_drawdown(path_values),
        "median_mfe_bps": statistics.median(mfe),
        "median_mae_bps": statistics.median(mae),
        "mean_mfe_bps": statistics.fmean(mfe),
        "mean_mae_bps": statistics.fmean(mae),
        "median_bars_held": statistics.median(int(r["bars_held"]) for r in rows),
        "symbols": len(symbol_means),
        "positive_symbol_fraction": sum(v > 0.0 for v in symbol_means) / len(symbol_means),
        "folds": len(fold_means),
        "median_120d_fold_expectancy_bps": statistics.median(fold_means),
        "positive_120d_fold_fraction": sum(v > 0.0 for v in fold_means) / len(fold_means),
        "year_expectancy_bps": years,
        "largest_positive_trade_share": (
            ranked_winners[0] / positive_total if ranked_winners and positive_total > 0.0 else None
        ),
        "top_three_positive_trade_share": (
            sum(ranked_winners[:3]) / positive_total if ranked_winners and positive_total > 0.0 else None
        ),
    }


def run_evidence_session_audit(
    config: Mapping[str, Any],
    *,
    data_dirs: Mapping[str, str | Path],
) -> dict[str, Any]:
    period = config["source_period"]
    start = pd.Timestamp(period["start"])
    end = pd.Timestamp(period["end_exclusive"])
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")

    fold_days = int(config["economics"]["fold_days"])
    cost = float(config["economics"]["round_trip_cost_bps"])
    buckets = list(config["session_buckets"])
    cache: dict[str, dict[str, pd.DataFrame]] = {}
    reports: list[dict[str, Any]] = []

    for variant in config["variants"]:
        interval = str(variant["interval"])
        if interval not in data_dirs:
            raise EvidenceSessionAuditError(f"missing data directory for {interval}")
        if interval not in cache:
            cache[interval] = load_interval_frames(data_dirs[interval], interval)
        trades: list[dict[str, Any]] = []
        for symbol, source in cache[interval].items():
            frame = source.loc[(source.index >= start) & (source.index < end)].copy()
            trades.extend(
                _extract_trades(
                    frame,
                    symbol=symbol,
                    family=str(variant["family"]),
                    params=variant["parameters"],
                    round_trip_cost_bps=cost,
                    buckets=buckets,
                )
            )

        baseline = _summarize(trades, fold_start=start, fold_days=fold_days)
        by_bucket = []
        for bucket in buckets:
            name = str(bucket["name"])
            subset = [r for r in trades if r["session_bucket"] == name]
            summary = _summarize(subset, fold_start=start, fold_days=fold_days)
            by_bucket.append(
                {
                    "session_bucket": name,
                    **summary,
                    "expectancy_delta_vs_all_bps": (
                        float(summary["net_expectancy_bps"]) - float(baseline["net_expectancy_bps"])
                        if summary.get("trades", 0) and baseline.get("trades", 0)
                        else None
                    ),
                }
            )

        by_entry_hour = []
        for hour in sorted({int(r["entry_hour_utc"]) for r in trades}):
            subset = [r for r in trades if int(r["entry_hour_utc"]) == hour]
            by_entry_hour.append(
                {
                    "entry_hour_utc": hour,
                    **_summarize(subset, fold_start=start, fold_days=fold_days),
                }
            )

        reports.append(
            {
                "audit_id": variant["audit_id"],
                "family": variant["family"],
                "interval": interval,
                "parameters": variant["parameters"],
                "round_trip_cost_bps": cost,
                "all_sessions": baseline,
                "by_session_bucket": by_bucket,
                "by_entry_hour_utc": by_entry_hour,
            }
        )

    return {
        "schema_version": 1,
        "analysis": "evidence_v2_session_audit_v1",
        "protocol_name": config["protocol_name"],
        "source_workflow_run_id": config["source_workflow_run_id"],
        "source_period": config["source_period"],
        "selection_rule": config["selection_rule"],
        "session_buckets": config["session_buckets"],
        "reports": reports,
        "claims": config["claims"],
    }


def load_config(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceSessionAuditError("config must be a JSON object")
    return payload

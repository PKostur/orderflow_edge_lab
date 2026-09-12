from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import generate_target_position


class EnaMeanReversionRiskError(ValueError):
    pass


@dataclass(frozen=True)
class RiskExperimentConfig:
    family: str = "bb_mean_reversion"
    period: int = 40
    std: float = 2.0
    rsi_period: int = 14
    rsi_low: float = 25.0
    rsi_high: float = 75.0
    max_hold: int = 20
    atr_period: int = 14
    round_trip_cost_bps: float = 20.0
    fold_days: int = 21
    stop_atr_multiples: tuple[float, ...] = (1.0, 1.5, 2.0)
    target_r_multiples: tuple[float, ...] = (1.0, 2.0, 3.0)
    reference_stop_atr_multiple: float = 1.5
    minimum_trades: int = 30
    minimum_folds: int = 6
    minimum_positive_fold_fraction: float = 0.60
    minimum_tail_loss_reduction_fraction: float = 0.70

    @property
    def signal_parameters(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "std": self.std,
            "rsi_period": self.rsi_period,
            "rsi_low": self.rsi_low,
            "rsi_high": self.rsi_high,
            "max_hold": self.max_hold,
        }


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous_close = frame["close"].astype(float).shift(1)
    true_range = pd.concat(
        [
            (frame["high"].astype(float) - frame["low"].astype(float)).abs(),
            (frame["high"].astype(float) - previous_close).abs(),
            (frame["low"].astype(float) - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(int(period), min_periods=int(period)).mean()


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise EnaMeanReversionRiskError(f"missing OHLC columns: {missing}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise EnaMeanReversionRiskError("frame index must be a DatetimeIndex")
    out = frame.copy().sort_index()
    if out.index.has_duplicates:
        raise EnaMeanReversionRiskError("duplicate timestamps are not allowed")
    if not out.index.is_monotonic_increasing:
        raise EnaMeanReversionRiskError("timestamps must be monotonic")
    for column in required:
        values = pd.to_numeric(out[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise EnaMeanReversionRiskError(f"non-finite values in {column}")
        if (values <= 0).any():
            raise EnaMeanReversionRiskError(f"non-positive values in {column}")
        out[column] = values.astype(float)
    if ((out["high"] < out[["open", "close"]].max(axis=1)) | (out["low"] > out[["open", "close"]].min(axis=1))).any():
        raise EnaMeanReversionRiskError("invalid OHLC envelope")
    return out


def _trade_stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in trades]
    if not returns:
        return {
            "trades": 0,
            "expectancy_bps": None,
            "profit_factor": None,
            "win_rate": None,
            "compounded_return": None,
            "max_trade_loss_bps": None,
            "max_trade_gain_bps": None,
            "trade_equity_max_drawdown": None,
        }
    gains = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    if losses > 0:
        profit_factor: float | str | None = gains / losses
    elif gains > 0:
        profit_factor = "INF"
    else:
        profit_factor = None
    equity = np.cumprod(1.0 + np.asarray(returns, dtype=float))
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1.0
    return {
        "trades": len(returns),
        "expectancy_bps": float(np.mean(returns) * 10_000.0),
        "profit_factor": profit_factor,
        "win_rate": float(np.mean(np.asarray(returns) > 0)),
        "compounded_return": float(equity[-1] - 1.0),
        "max_trade_loss_bps": float(min(returns) * 10_000.0),
        "max_trade_gain_bps": float(max(returns) * 10_000.0),
        "trade_equity_max_drawdown": float(drawdowns.min()),
    }


def _pf_float(value: Any) -> float | None:
    if value == "INF":
        return math.inf
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def simulate_overlay(
    frame: pd.DataFrame,
    config: RiskExperimentConfig,
    *,
    stop_atr_multiple: float | None,
    target_r_multiple: float | None = None,
) -> list[dict[str, Any]]:
    frame = _validate_frame(frame)
    if stop_atr_multiple is None and target_r_multiple is not None:
        raise EnaMeanReversionRiskError("target R requires a stop ATR multiple")
    if stop_atr_multiple is not None and stop_atr_multiple <= 0:
        raise EnaMeanReversionRiskError("stop ATR multiple must be positive")
    if target_r_multiple is not None and target_r_multiple <= 0:
        raise EnaMeanReversionRiskError("target R multiple must be positive")

    target = generate_target_position(frame, config.family, config.signal_parameters)
    desired = target.shift(1).fillna(0.0).clip(-1.0, 1.0)
    signal_atr = _atr(frame, config.atr_period).shift(1)
    cost_fraction = config.round_trip_cost_bps / 10_000.0

    trades: list[dict[str, Any]] = []
    side = 0
    locked_side = 0
    entry_index: int | None = None
    entry_price: float | None = None
    atr_at_entry: float | None = None
    risk_distance: float | None = None
    mae = 0.0
    mfe = 0.0

    def close_trade(exit_index: int, exit_price: float, reason: str) -> None:
        nonlocal side, entry_index, entry_price, atr_at_entry, risk_distance, mae, mfe
        if side == 0 or entry_index is None or entry_price is None or atr_at_entry is None:
            raise EnaMeanReversionRiskError("attempted to close an incomplete trade")
        gross = side * (float(exit_price) / entry_price - 1.0)
        trades.append(
            {
                "entry_time": frame.index[entry_index].isoformat(),
                "exit_time": frame.index[exit_index].isoformat(),
                "side": "long" if side > 0 else "short",
                "entry_price": entry_price,
                "exit_price": float(exit_price),
                "exit_reason": reason,
                "gross_return": float(gross),
                "net_return": float(gross - cost_fraction),
                "atr_at_entry": atr_at_entry,
                "stop_atr_multiple": stop_atr_multiple,
                "target_r_multiple": target_r_multiple,
                "mae_bps": float(mae * 10_000.0),
                "mfe_bps": float(mfe * 10_000.0),
                "mae_atr": float(mae * entry_price / atr_at_entry),
                "mfe_atr": float(mfe * entry_price / atr_at_entry),
            }
        )
        side = 0
        entry_index = None
        entry_price = None
        atr_at_entry = None
        risk_distance = None
        mae = 0.0
        mfe = 0.0

    for index, (_, row) in enumerate(frame.iterrows()):
        requested = int(desired.iloc[index])
        if locked_side and requested != locked_side:
            locked_side = 0

        # Desired position was generated using the previous completed bar.
        # Signal-state exits/reversals therefore execute at this bar's open.
        if side and requested != side:
            previous_side = side
            close_trade(index, float(row["open"]), "signal_exit")
            if requested == -previous_side:
                locked_side = 0

        if side == 0 and requested and requested != locked_side:
            candidate_atr = signal_atr.iloc[index]
            if pd.notna(candidate_atr) and float(candidate_atr) > 0:
                side = requested
                entry_index = index
                entry_price = float(row["open"])
                atr_at_entry = float(candidate_atr)
                risk_distance = (
                    atr_at_entry * float(stop_atr_multiple)
                    if stop_atr_multiple is not None
                    else None
                )
                mae = 0.0
                mfe = 0.0

        if side == 0 or entry_price is None or atr_at_entry is None:
            continue

        if side > 0:
            adverse = float(row["low"]) / entry_price - 1.0
            favorable = float(row["high"]) / entry_price - 1.0
        else:
            adverse = -(float(row["high"]) / entry_price - 1.0)
            favorable = -(float(row["low"]) / entry_price - 1.0)
        mae = min(mae, adverse)
        mfe = max(mfe, favorable)

        if risk_distance is None:
            continue

        stop_price = entry_price - side * risk_distance
        target_price = (
            entry_price + side * risk_distance * float(target_r_multiple)
            if target_r_multiple is not None
            else None
        )
        stop_hit = (
            float(row["low"]) <= stop_price
            if side > 0
            else float(row["high"]) >= stop_price
        )
        target_hit = False
        if target_price is not None:
            target_hit = (
                float(row["high"]) >= target_price
                if side > 0
                else float(row["low"]) <= target_price
            )

        # OHLC cannot identify intrabar ordering. Fail conservatively:
        # if stop and target are both inside one bar, assume stop first.
        if stop_hit or target_hit:
            exit_side = side
            if stop_hit:
                close_trade(index, stop_price, "stop")
            else:
                close_trade(index, float(target_price), f"target_{target_r_multiple:g}R")
            locked_side = exit_side

    if side and entry_price is not None:
        close_trade(len(frame) - 1, float(frame["close"].iloc[-1]), "end_of_data")
    return trades


def _fold_ranges(index: pd.DatetimeIndex, fold_days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not len(index):
        return []
    cursor = index.min().normalize()
    end = index.max()
    delta = pd.Timedelta(days=int(fold_days))
    ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    while cursor < end:
        nxt = cursor + delta
        ranges.append((cursor, nxt))
        cursor = nxt
    return ranges


def summarize_variant(
    frame: pd.DataFrame,
    config: RiskExperimentConfig,
    *,
    stop_atr_multiple: float | None,
    target_r_multiple: float | None = None,
) -> dict[str, Any]:
    full_trades = simulate_overlay(
        frame,
        config,
        stop_atr_multiple=stop_atr_multiple,
        target_r_multiple=target_r_multiple,
    )
    full = _trade_stats(full_trades)

    folds: list[dict[str, Any]] = []
    for start, end in _fold_ranges(frame.index, config.fold_days):
        window = frame[(frame.index >= start) & (frame.index < end)]
        if len(window) < 100:
            continue
        trades = simulate_overlay(
            window,
            config,
            stop_atr_multiple=stop_atr_multiple,
            target_r_multiple=target_r_multiple,
        )
        stats = _trade_stats(trades)
        if stats["trades"] <= 0:
            continue
        folds.append({"fold_start": start.isoformat(), "fold_end": end.isoformat(), **stats})

    fold_expectancies = [
        float(row["expectancy_bps"])
        for row in folds
        if row.get("expectancy_bps") is not None
    ]
    fold_pfs = [
        value
        for value in (_pf_float(row.get("profit_factor")) for row in folds)
        if value is not None
    ]
    positive_fold_fraction = (
        sum(value > 0 for value in fold_expectancies) / len(fold_expectancies)
        if fold_expectancies
        else None
    )
    return {
        "stop_atr_multiple": stop_atr_multiple,
        "target_r_multiple": target_r_multiple,
        "full_period": full,
        "fold_observations": len(folds),
        "positive_fold_fraction": positive_fold_fraction,
        "median_fold_expectancy_bps": (
            float(median(fold_expectancies)) if fold_expectancies else None
        ),
        "median_fold_profit_factor": float(median(fold_pfs)) if fold_pfs else None,
        "folds": folds,
        "trades": full_trades,
    }


def _excursion_summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {}
    mae_atr = [float(row["mae_atr"]) for row in trades]
    mfe_atr = [float(row["mfe_atr"]) for row in trades]
    winners = [row for row in trades if float(row["net_return"]) > 0]
    losers = [row for row in trades if float(row["net_return"]) <= 0]

    def group(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"trades": 0}
        mae = [float(row["mae_atr"]) for row in rows]
        mfe = [float(row["mfe_atr"]) for row in rows]
        return {
            "trades": len(rows),
            "median_mae_atr": float(median(mae)),
            "mean_mae_atr": float(np.mean(mae)),
            "median_mfe_atr": float(median(mfe)),
            "mean_mfe_atr": float(np.mean(mfe)),
        }

    return {
        "all": group(trades),
        "winners": group(winners),
        "losers": group(losers),
        "mfe_reach_fraction": {
            "1R": float(np.mean(np.asarray(mfe_atr) >= 1.0)),
            "2R": float(np.mean(np.asarray(mfe_atr) >= 2.0)),
            "3R": float(np.mean(np.asarray(mfe_atr) >= 3.0)),
        },
        "mae_breach_fraction": {
            "1ATR": float(np.mean(np.asarray(mae_atr) <= -1.0)),
            "1.5ATR": float(np.mean(np.asarray(mae_atr) <= -1.5)),
            "2ATR": float(np.mean(np.asarray(mae_atr) <= -2.0)),
            "3ATR": float(np.mean(np.asarray(mae_atr) <= -3.0)),
        },
    }


def _tail_loss_reduction(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> float | None:
    base_loss = baseline.get("max_trade_loss_bps")
    candidate_loss = candidate.get("max_trade_loss_bps")
    if base_loss is None or candidate_loss is None:
        return None
    base_abs = abs(min(float(base_loss), 0.0))
    candidate_abs = abs(min(float(candidate_loss), 0.0))
    if base_abs <= 0:
        return None
    return 1.0 - candidate_abs / base_abs


def _passes_basic_variant_gate(row: Mapping[str, Any], config: RiskExperimentConfig) -> tuple[bool, list[str]]:
    full = row.get("full_period", {})
    failures: list[str] = []
    trades = int(full.get("trades") or 0)
    expectancy = full.get("expectancy_bps")
    pf = _pf_float(full.get("profit_factor"))
    folds = int(row.get("fold_observations") or 0)
    positive_fraction = row.get("positive_fold_fraction")
    fold_expectancy = row.get("median_fold_expectancy_bps")
    fold_pf = row.get("median_fold_profit_factor")
    checks = [
        (trades >= config.minimum_trades, f"trades {trades}/{config.minimum_trades}"),
        (expectancy is not None and float(expectancy) > 0, f"full_expectancy_bps {expectancy}"),
        (pf is not None and pf > 1.0, f"full_profit_factor {pf}"),
        (folds >= config.minimum_folds, f"folds {folds}/{config.minimum_folds}"),
        (
            positive_fraction is not None
            and float(positive_fraction) >= config.minimum_positive_fold_fraction,
            f"positive_fold_fraction {positive_fraction}",
        ),
        (
            fold_expectancy is not None and float(fold_expectancy) > 0,
            f"median_fold_expectancy_bps {fold_expectancy}",
        ),
        (
            fold_pf is not None and float(fold_pf) > 1.0,
            f"median_fold_profit_factor {fold_pf}",
        ),
    ]
    for passed, reason in checks:
        if not passed:
            failures.append(reason)
    return not failures, failures


def analyze_risk_experiment(
    frame: pd.DataFrame,
    config: RiskExperimentConfig = RiskExperimentConfig(),
    *,
    source_name: str | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    frame = _validate_frame(frame)
    baseline = summarize_variant(frame, config, stop_atr_multiple=None)
    variants: list[dict[str, Any]] = []

    for stop in config.stop_atr_multiples:
        variants.append(
            summarize_variant(frame, config, stop_atr_multiple=float(stop), target_r_multiple=None)
        )
        for target_r in config.target_r_multiples:
            variants.append(
                summarize_variant(
                    frame,
                    config,
                    stop_atr_multiple=float(stop),
                    target_r_multiple=float(target_r),
                )
            )

    for row in variants:
        eligible, failures = _passes_basic_variant_gate(row, config)
        row["development_gate_eligible"] = eligible
        row["development_gate_fail_reasons"] = failures

    reference = next(
        (
            row
            for row in variants
            if row["stop_atr_multiple"] == config.reference_stop_atr_multiple
            and row["target_r_multiple"] is None
        ),
        None,
    )
    if reference is None:
        raise EnaMeanReversionRiskError("reference stop variant is absent from trial grid")

    reference_eligible, reference_failures = _passes_basic_variant_gate(reference, config)
    tail_reduction = _tail_loss_reduction(
        baseline["full_period"],
        reference["full_period"],
    )
    if (
        tail_reduction is None
        or tail_reduction < config.minimum_tail_loss_reduction_fraction
    ):
        reference_failures.append(f"tail_loss_reduction_fraction {tail_reduction}")

    neighbor_rows = [
        row
        for row in variants
        if row["target_r_multiple"] is None
        and row["stop_atr_multiple"] != config.reference_stop_atr_multiple
    ]
    neighbor_positive = 0
    for row in neighbor_rows:
        full = row["full_period"]
        pf = _pf_float(full.get("profit_factor"))
        if (
            full.get("expectancy_bps") is not None
            and float(full["expectancy_bps"]) > 0
            and pf is not None
            and pf > 1.0
        ):
            neighbor_positive += 1
    if neighbor_positive < len(neighbor_rows):
        reference_failures.append(
            f"positive_full_period_stop_neighbors {neighbor_positive}/{len(neighbor_rows)}"
        )

    reference_ready = reference_eligible and not reference_failures
    return {
        "schema_version": 1,
        "experiment": "ena-mean-reversion-risk-v1",
        "symbol": "ENA_USDT",
        "interval": "1h",
        "source": {
            "name": source_name,
            "sha256": source_sha256,
            "rows": len(frame),
            "start": frame.index.min().isoformat(),
            "end": frame.index.max().isoformat(),
        },
        "signal": {
            "family": config.family,
            "parameters": config.signal_parameters,
            "signal_timing": "completed bar; desired position shifted one bar and executed at next bar open",
        },
        "economics": {"round_trip_cost_bps": config.round_trip_cost_bps},
        "risk_trial_grid": {
            "stop_atr_multiples": list(config.stop_atr_multiples),
            "target_r_multiples": list(config.target_r_multiples),
            "reference_stop_atr_multiple": config.reference_stop_atr_multiple,
            "reference_target": "original mid-band/time exit",
            "same_bar_stop_target_rule": "stop_first",
            "post_risk_exit_rule": "remain flat until frozen signal state resets or reverses",
        },
        "baseline": baseline,
        "baseline_excursions": _excursion_summary(baseline["trades"]),
        "variants": variants,
        "reference_risk_variant": {
            "stop_atr_multiple": config.reference_stop_atr_multiple,
            "target_r_multiple": None,
            "tail_loss_reduction_fraction_vs_baseline": tail_reduction,
            "positive_full_period_stop_neighbors": neighbor_positive,
            "total_stop_neighbors": len(neighbor_rows),
            "development_freeze_ready": reference_ready,
            "fail_reasons": reference_failures,
        },
        "claims": {
            "development_only": True,
            "historical_period_already_inspected": True,
            "profitable_edge_established": False,
            "untouched_oos_completed": False,
            "forward_paper_shadow_started": False,
            "live_order_transmission_supported": False,
        },
    }


def load_ohlcv_csv(path: str | Path) -> tuple[pd.DataFrame, str]:
    source = Path(path)
    raw = source.read_bytes()
    frame = pd.read_csv(source)
    if "timestamp" not in frame.columns:
        raise EnaMeanReversionRiskError("CSV must contain timestamp")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.set_index("timestamp")
    return _validate_frame(frame), sha256(raw).hexdigest()


def write_report(report: Mapping[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")

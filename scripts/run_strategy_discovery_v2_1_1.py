from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    for c in ["open", "high", "low", "close", "volume"]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close", "volume"])


def rolling_z(x: pd.Series, window: int) -> pd.Series:
    w = max(20, int(window))
    mu = x.rolling(w, min_periods=max(10, w // 2)).mean()
    sd = x.rolling(w, min_periods=max(10, w // 2)).std(ddof=0)
    return (x - mu) / sd.replace(0.0, np.nan)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = frame["close"].shift(1)
    tr = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - pc).abs(),
            (frame["low"] - pc).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def expand_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def session_vwap(frame: pd.DataFrame) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    day = frame.index.floor("D")
    pv = typical * frame["volume"]
    cum_pv = pv.groupby(day).cumsum()
    cum_v = frame["volume"].groupby(day).cumsum().replace(0.0, np.nan)
    return cum_pv / cum_v


def opening_range(frame: pd.DataFrame, opening_bars: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    day = pd.Series(frame.index.floor("D"), index=frame.index)
    order = frame.groupby(day).cumcount()
    in_open = order < int(opening_bars)
    high = frame["high"].where(in_open).groupby(day).transform("max")
    low = frame["low"].where(in_open).groupby(day).transform("min")
    active = order >= int(opening_bars)
    return high, low, active


def aligned_pair(frame: pd.DataFrame, btc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = frame.index.intersection(btc.index)
    return frame.loc[idx].copy(), btc.loc[idx].copy()


def score_family(
    frame: pd.DataFrame,
    btc: pd.DataFrame,
    family: str,
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series]:
    frame, btc = aligned_pair(frame, btc)
    close = frame["close"]
    btc_close = btc["close"]
    a = atr(frame)
    eligible = pd.Series(True, index=frame.index)

    if family.startswith("session_vwap_"):
        vwap = session_vwap(frame)
        raw = (close - vwap) / a.replace(0.0, np.nan)
        raw = raw if family.endswith("trend") else -raw
        eligible &= raw.abs() >= float(params["threshold"])
        return raw, eligible

    if family.startswith("opening_range_"):
        high, low, active = opening_range(frame, int(params["opening_bars"]))
        dist = pd.Series(0.0, index=frame.index)
        dist = dist.mask(close > high, (close - high) / a.replace(0.0, np.nan))
        dist = dist.mask(close < low, (close - low) / a.replace(0.0, np.nan))
        if family.endswith("reversal"):
            dist = -dist
        eligible &= active & (dist.abs() >= float(params["threshold_atr"])) & (dist != 0)
        return dist, eligible

    ret1 = close.pct_change()
    if family.startswith("volume_shock_"):
        lookback = int(params["return_lookback"])
        ret = close.pct_change(lookback)
        ret_z = ret / (
            ret1.rolling(96, min_periods=48).std(ddof=0) * math.sqrt(lookback)
        ).replace(0.0, np.nan)
        volume_z = rolling_z(np.log1p(frame["volume"]), 96)
        raw = ret_z if family.endswith("continuation") else -ret_z
        eligible &= volume_z >= float(params["volume_z"])
        return raw, eligible

    if family.startswith("range_expansion_"):
        pc = close.shift(1)
        tr = pd.concat(
            [
                (frame["high"] - frame["low"]).abs(),
                (frame["high"] - pc).abs(),
                (frame["low"] - pc).abs(),
            ],
            axis=1,
        ).max(axis=1)
        range_z = rolling_z(tr / close.replace(0.0, np.nan), 96)
        direction = np.sign(close.pct_change()).replace(0.0, np.nan)
        raw = direction * range_z.clip(lower=0.0)
        if family.endswith("fade"):
            raw = -raw
        eligible &= range_z >= float(params["range_z"])
        return raw, eligible

    if family.startswith("btc_relative_strength_"):
        lookback = int(params["lookback"])
        relative_return = close.pct_change(lookback) - btc_close.pct_change(lookback)
        z = rolling_z(relative_return, 96)
        raw = z if family.endswith("momentum") else -z
        eligible &= z.abs() >= float(params["threshold_z"])
        return raw, eligible

    asset_return = close.pct_change()
    btc_return = btc_close.pct_change()
    if family.startswith("beta_residual_"):
        beta_window = int(params["beta_window"])
        min_periods = max(30, beta_window // 2)
        beta = asset_return.rolling(beta_window, min_periods=min_periods).cov(btc_return) / (
            btc_return.rolling(beta_window, min_periods=min_periods).var().replace(0.0, np.nan)
        )
        residual = asset_return - beta * btc_return
        lookback = int(params["residual_lookback"])
        aggregate = residual.rolling(lookback, min_periods=lookback).sum()
        residual_vol = residual.rolling(beta_window, min_periods=min_periods).std(ddof=0)
        z = aggregate / (residual_vol * math.sqrt(lookback)).replace(0.0, np.nan)
        raw = z if family.endswith("momentum") else -z
        eligible &= z.abs() >= float(params["threshold_z"])
        return raw, eligible

    if family.startswith("rolling_beta_spread_"):
        window = int(params["regression_window"])
        min_periods = max(30, window // 2)
        log_asset = np.log(close)
        log_btc = np.log(btc_close)
        beta = log_asset.rolling(window, min_periods=min_periods).cov(log_btc) / (
            log_btc.rolling(window, min_periods=min_periods).var().replace(0.0, np.nan)
        )
        alpha = (
            log_asset.rolling(window, min_periods=min_periods).mean()
            - beta * log_btc.rolling(window, min_periods=min_periods).mean()
        )
        residual = log_asset - alpha - beta * log_btc
        z = rolling_z(residual, window)
        raw = z if family.endswith("momentum") else -z
        eligible &= z.abs() >= float(params["threshold_z"])
        return raw, eligible

    raise ValueError(f"unknown family {family}")


def forward_return(frame: pd.DataFrame, hold_bars: int) -> pd.Series:
    entry = frame["open"].shift(-1)
    exit_price = frame["open"].shift(-(1 + int(hold_bars)))
    return exit_price / entry - 1.0


def causal_exit_timestamp(frame: pd.DataFrame, hold_bars: int) -> pd.Series:
    timestamps = pd.Series(frame.index, index=frame.index)
    return timestamps.shift(-(1 + int(hold_bars)))


def fold_labels(index: pd.DatetimeIndex, start: pd.Timestamp, fold_days: int) -> pd.Series:
    delta = (index - start) / pd.Timedelta(days=fold_days)
    return pd.Series(np.floor(delta).astype(int), index=index)


def causal_observation_frame(
    frame: pd.DataFrame,
    score: pd.Series,
    eligible: pd.Series,
    hold_bars: int,
    global_start: pd.Timestamp,
    fold_days: int,
) -> pd.DataFrame:
    folds = fold_labels(frame.index, global_start, fold_days)
    exit_ts = causal_exit_timestamp(frame, hold_bars)
    exit_fold = folds.shift(-(1 + int(hold_bars)))
    data = pd.DataFrame(
        {
            "score": score,
            "eligible": eligible,
            "fwd": forward_return(frame, hold_bars),
            "fold": folds,
            "exit_fold": exit_fold,
            "exit_ts": exit_ts,
        },
        index=frame.index,
    )
    mask = (
        data["eligible"].fillna(False)
        & data["score"].notna()
        & data["fwd"].notna()
        & data["exit_ts"].notna()
        & data["exit_fold"].notna()
        & (data["fold"] >= 0)
        & (data["fold"] == data["exit_fold"])
    )
    data = data.loc[mask].copy()
    if not data.empty:
        if not (data["exit_ts"] > data.index).all():
            raise RuntimeError("causal exit timestamp must be after signal timestamp")
        if not (data["fold"] == data["exit_fold"]).all():
            raise RuntimeError("cross-fold causal observation leaked through boundary filter")
    return data


def spearman(x: Iterable[float], y: Iterable[float]) -> float:
    a = pd.Series(list(x), dtype=float)
    b = pd.Series(list(y), dtype=float)
    mask = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 8:
        return float("nan")
    ar = a[mask].rank(method="average")
    br = b[mask].rank(method="average")
    return float(ar.corr(br))


def profit_factor(values: list[float], all_win_sentinel: float) -> float:
    positive = sum(v for v in values if v > 0)
    negative = -sum(v for v in values if v < 0)
    if negative <= 0:
        return float(all_win_sentinel) if positive > 0 else 0.0
    return float(positive / negative)


def median_finite(values: list[float]) -> float:
    finite = [v for v in values if np.isfinite(v)]
    return float(np.median(finite)) if finite else float("nan")


def run(config: dict[str, Any], data_dir: Path, interval: str) -> dict[str, Any]:
    context_symbol = str(config["data"]["context_symbol"])
    symbols = [str(s) for s in config["data"]["symbols"] if str(s) != context_symbol]
    btc = load_frame(data_dir / f"{context_symbol}_{interval}.csv")
    frames = {symbol: load_frame(data_dir / f"{symbol}_{interval}.csv") for symbol in symbols}
    global_start = max([btc.index.min()] + [frame.index.min() for frame in frames.values()])
    fold_days = int(config["dependence_and_trials"]["calendar_fold_days"])
    costs = [float(x) for x in config["economics"]["round_trip_cost_bps"]]
    primary_cost = float(config["economics"]["primary_cost_bps"])
    all_win_sentinel = float(config["reliability_amendment"]["finite_all_win_profit_factor_sentinel"])

    state_trials: list[dict[str, Any]] = []
    translations: list[dict[str, Any]] = []

    for family, spec in config["families"].items():
        for params in expand_grid(spec["grid"]):
            hold_bars = int(params["hold_bars"])
            observations: list[dict[str, Any]] = []
            per_symbol: dict[str, pd.DataFrame] = {}

            for symbol, raw_frame in frames.items():
                frame, btc_frame = aligned_pair(raw_frame, btc)
                score, eligible = score_family(frame, btc_frame, family, params)
                data = causal_observation_frame(
                    frame,
                    score,
                    eligible,
                    hold_bars,
                    global_start,
                    fold_days,
                )
                per_symbol[symbol] = data
                for row in data.itertuples():
                    observations.append(
                        {
                            "symbol": symbol,
                            "timestamp": row.Index,
                            "fold": int(row.fold),
                            "score": float(row.score),
                            "fwd": float(row.fwd),
                        }
                    )

            pooled = pd.DataFrame(observations)
            if pooled.empty:
                continue

            fold_rhos: list[float] = []
            for _, group in pooled.groupby("fold"):
                rho = spearman(group["score"], group["fwd"])
                if np.isfinite(rho):
                    fold_rhos.append(float(rho))

            median_rho = median_finite(fold_rhos)
            positive_fold_fraction = (
                float(np.mean([rho > 0 for rho in fold_rhos])) if fold_rhos else 0.0
            )
            state_pass = bool(
                len(fold_rhos) >= int(config["dependence_and_trials"]["minimum_folds"])
                and median_rho > float(config["state_screen"]["median_spearman_gt"])
                and positive_fold_fraction
                >= float(config["state_screen"]["minimum_positive_fold_fraction"])
            )
            state_trials.append(
                {
                    "family": family,
                    "interval": interval,
                    "params": params,
                    "folds": len(fold_rhos),
                    "median_fold_spearman": median_rho,
                    "positive_fold_fraction": positive_fold_fraction,
                    "eligible_observations": len(pooled),
                    "state_pass": state_pass,
                }
            )
            if not state_pass:
                continue

            for cost in costs:
                fold_trades: dict[int, list[float]] = {}
                reversed_fold: dict[int, list[float]] = {}
                symbol_trades: dict[str, list[float]] = {symbol: [] for symbol in symbols}

                for symbol, data in per_symbol.items():
                    if data.empty:
                        continue
                    next_allowed: pd.Timestamp | None = None
                    for ts, row in data.sort_index().iterrows():
                        if next_allowed is not None and ts < next_allowed:
                            continue
                        side = 1.0 if float(row["score"]) > 0 else -1.0
                        gross_bps = side * float(row["fwd"]) * 10_000.0
                        fold = int(row["fold"])
                        net_bps = gross_bps - cost
                        fold_trades.setdefault(fold, []).append(net_bps)
                        reversed_fold.setdefault(fold, []).append(-gross_bps - cost)
                        symbol_trades[symbol].append(net_bps)
                        next_allowed = pd.Timestamp(row["exit_ts"])

                fold_expectancies = [float(np.mean(v)) for v in fold_trades.values() if v]
                fold_profit_factors = [
                    profit_factor(v, all_win_sentinel) for v in fold_trades.values() if v
                ]
                reversed_expectancies = [
                    float(np.mean(v)) for v in reversed_fold.values() if v
                ]
                symbol_expectancies = [
                    float(np.mean(v)) for v in symbol_trades.values() if v
                ]
                total_trades = sum(len(v) for v in fold_trades.values())

                row = {
                    "family": family,
                    "interval": interval,
                    "params": params,
                    "cost_bps": cost,
                    "folds": len(fold_expectancies),
                    "total_trades": total_trades,
                    "median_fold_net_expectancy_bps": median_finite(fold_expectancies),
                    "median_fold_profit_factor": median_finite(fold_profit_factors),
                    "positive_fold_fraction": (
                        float(np.mean([x > 0 for x in fold_expectancies]))
                        if fold_expectancies
                        else 0.0
                    ),
                    "positive_symbol_fraction": (
                        float(np.mean([x > 0 for x in symbol_expectancies]))
                        if symbol_expectancies
                        else 0.0
                    ),
                    "reversed_median_net_expectancy_bps": median_finite(
                        reversed_expectancies
                    ),
                }
                row["original_beats_reversed"] = bool(
                    row["median_fold_net_expectancy_bps"]
                    > row["reversed_median_net_expectancy_bps"]
                )
                row["economic_pass"] = bool(
                    cost == primary_cost
                    and total_trades
                    >= int(config["dependence_and_trials"]["minimum_total_trades"])
                    and len(fold_expectancies)
                    >= int(config["dependence_and_trials"]["minimum_folds"])
                    and row["median_fold_net_expectancy_bps"]
                    > float(config["screening_gate"]["median_fold_net_expectancy_bps_gt"])
                    and row["median_fold_profit_factor"]
                    > float(config["screening_gate"]["median_fold_profit_factor_gt"])
                    and row["positive_fold_fraction"]
                    >= float(config["screening_gate"]["minimum_positive_fold_fraction"])
                    and row["positive_symbol_fraction"]
                    >= float(config["screening_gate"]["minimum_positive_symbol_fraction"])
                    and row["original_beats_reversed"]
                )
                translations.append(row)

    primary = [row for row in translations if float(row["cost_bps"]) == primary_cost]
    primary.sort(
        key=lambda row: (
            row["economic_pass"],
            row["median_fold_net_expectancy_bps"],
        ),
        reverse=True,
    )
    state_sorted = sorted(
        state_trials,
        key=lambda row: (row["state_pass"], row["median_fold_spearman"]),
        reverse=True,
    )

    return {
        "schema_version": 1,
        "protocol_name": config["protocol_name"],
        "interval": interval,
        "symbols": symbols,
        "state_trial_count": len(state_trials),
        "state_pass_count": sum(bool(row["state_pass"]) for row in state_trials),
        "translation_count": len(translations),
        "economic_pass_count_primary": sum(bool(row["economic_pass"]) for row in primary),
        "top_state": state_sorted[:30],
        "primary_cost_leaderboard": primary[:60],
        "all_state_trials": state_trials,
        "all_translations": translations,
        "reliability": {
            "same_fold_exit_enforced": True,
            "non_overlap_uses_actual_exit_timestamp": True,
            "finite_all_win_profit_factor_sentinel": all_win_sentinel,
            "superseded_v2_1_results_used": False,
        },
        "claims": {
            "development_screening_only": True,
            "profitable_edge_established": False,
            "verified_oos": False,
            "live_enabled": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--interval", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.interval not in config["data"]["intervals"]:
        raise SystemExit("interval not frozen")
    result = run(config, Path(args.data_dir), args.interval)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "protocol": result["protocol_name"],
                "interval": result["interval"],
                "state_trials": result["state_trial_count"],
                "state_pass": result["state_pass_count"],
                "translations": result["translation_count"],
                "economic_pass_primary": result["economic_pass_count_primary"],
                "top_state": result["top_state"][:5],
                "top_primary": result["primary_cost_leaderboard"][:5],
                "reliability": result["reliability"],
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

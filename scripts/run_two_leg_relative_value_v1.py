from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


FINITE_PF = 1_000_000.0


def _spearman(x: pd.Series, y: pd.Series) -> float:
    pair = pd.concat([x, y], axis=1).dropna()
    if len(pair) < 20:
        return float("nan")
    return float(pair.iloc[:, 0].rank().corr(pair.iloc[:, 1].rank()))


def _profit_factor(net_bps: np.ndarray) -> float:
    wins = float(net_bps[net_bps > 0].sum())
    losses = float(-net_bps[net_bps < 0].sum())
    if losses <= 0:
        return FINITE_PF if wins > 0 else 0.0
    return wins / losses


def _fold_ids(index: pd.DatetimeIndex, start: pd.Timestamp, days: int) -> pd.Series:
    elapsed_days = (index - start).total_seconds() / 86400.0
    return pd.Series(np.floor(elapsed_days / days).astype(int), index=index)


def _rolling_log_price_state(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    alt_log = np.log(frame["alt_close"])
    btc_log = np.log(frame["btc_close"])
    beta = alt_log.rolling(window).cov(btc_log) / btc_log.rolling(window).var()
    alpha = alt_log.rolling(window).mean() - beta * btc_log.rolling(window).mean()
    residual = alt_log - alpha - beta * btc_log
    mean = residual.rolling(window).mean()
    std = residual.rolling(window).std(ddof=0)
    z = (residual - mean) / std.replace(0.0, np.nan)
    return pd.DataFrame({"beta": beta, "spread": residual, "z": z}, index=frame.index)


def _rolling_return_state(frame: pd.DataFrame, window: int, residual_lookback: int) -> pd.DataFrame:
    alt_ret = np.log(frame["alt_close"]).diff()
    btc_ret = np.log(frame["btc_close"]).diff()
    beta = alt_ret.rolling(window).cov(btc_ret) / btc_ret.rolling(window).var()
    residual = alt_ret - beta * btc_ret
    score = residual.rolling(residual_lookback).sum()
    std = score.rolling(window).std(ddof=0)
    z = score / std.replace(0.0, np.nan)
    return pd.DataFrame({"beta": beta, "spread": score, "z": z}, index=frame.index)


def _align(alt: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    joined = pd.DataFrame(
        {
            "alt_open": alt["open"],
            "alt_close": alt["close"],
            "btc_open": btc["open"],
            "btc_close": btc["close"],
        }
    ).join(
        pd.DataFrame({"btc_open": btc["open"], "btc_close": btc["close"]}),
        how="inner",
        rsuffix="_dup",
    )
    if "btc_open_dup" in joined:
        joined = joined.drop(columns=["btc_open_dup", "btc_close_dup"])
    return joined.dropna().sort_index()


def _build_aligned(alt: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    idx = alt.index.intersection(btc.index)
    return pd.DataFrame(
        {
            "alt_open": alt.loc[idx, "open"],
            "alt_close": alt.loc[idx, "close"],
            "btc_open": btc.loc[idx, "open"],
            "btc_close": btc.loc[idx, "close"],
        },
        index=idx,
    ).dropna()


def _state_rows(
    symbol: str,
    aligned: pd.DataFrame,
    state: pd.DataFrame,
    threshold: float,
    hold_bars: int,
    fold_days: int,
    global_start: pd.Timestamp,
    beta_cap: float,
    family: str,
    window: int,
    residual_lookback: int | None,
) -> list[dict[str, Any]]:
    work = aligned.join(state)
    work["fold"] = _fold_ids(work.index, global_start, fold_days)
    work["future_spread_change"] = work["spread"].shift(-hold_bars) - work["spread"]
    work["mean_reversion_score"] = -work["z"]
    work["continuation_score"] = work["z"]
    eligible = (
        work["beta"].gt(0.0)
        & work["beta"].le(beta_cap)
        & np.isfinite(work["beta"])
        & work["z"].abs().ge(threshold)
    )
    rows: list[dict[str, Any]] = []
    for fold, chunk in work.loc[eligible].groupby("fold"):
        rho_reversion = _spearman(chunk["mean_reversion_score"], chunk["future_spread_change"])
        rho_continuation = _spearman(chunk["continuation_score"], chunk["future_spread_change"])
        rows.append(
            {
                "symbol": symbol,
                "family": family,
                "window": window,
                "residual_lookback": residual_lookback,
                "threshold": threshold,
                "hold_bars": hold_bars,
                "fold": int(fold),
                "n_state": int(len(chunk)),
                "rho_reversion": rho_reversion,
                "rho_continuation": rho_continuation,
            }
        )
    return rows


def _state_summary(rows: pd.DataFrame, min_positive_fold_fraction: float) -> dict[str, Any]:
    valid = rows[np.isfinite(rows["rho_reversion"])].copy()
    if valid.empty:
        return {"state_pass": False, "median_rho": float("nan"), "positive_fold_fraction": 0.0, "n_scored_folds": 0}
    by_fold = valid.groupby("fold", as_index=False)["rho_reversion"].median()
    median_rho = float(by_fold["rho_reversion"].median())
    positive_fraction = float((by_fold["rho_reversion"] > 0).mean())
    return {
        "state_pass": bool(median_rho > 0.0 and positive_fraction >= min_positive_fold_fraction),
        "median_rho": median_rho,
        "positive_fold_fraction": positive_fraction,
        "n_scored_folds": int(len(by_fold)),
    }


def _trades_for_variant(
    symbol: str,
    aligned: pd.DataFrame,
    state: pd.DataFrame,
    threshold: float,
    hold_bars: int,
    fold_days: int,
    global_start: pd.Timestamp,
    beta_cap: float,
    cost_bps: float,
    exit_rule: str,
) -> list[dict[str, Any]]:
    work = aligned.join(state)
    work["fold"] = _fold_ids(work.index, global_start, fold_days)
    rows: list[dict[str, Any]] = []
    i = 0
    while i < len(work) - 2:
        row = work.iloc[i]
        beta = float(row["beta"]) if pd.notna(row["beta"]) else float("nan")
        z = float(row["z"]) if pd.notna(row["z"]) else float("nan")
        if not (math.isfinite(beta) and 0.0 < beta <= beta_cap and math.isfinite(z) and abs(z) >= threshold):
            i += 1
            continue
        entry_i = i + 1
        max_exit_i = min(i + 1 + hold_bars, len(work) - 1)
        if int(work.iloc[entry_i]["fold"]) != int(row["fold"]):
            i += 1
            continue
        exit_i = max_exit_i
        if exit_rule == "spread_cross_zero_or_time":
            sign0 = 1 if z > 0 else -1
            for j in range(entry_i, max_exit_i + 1):
                zj = work.iloc[j]["z"]
                if pd.notna(zj) and math.isfinite(float(zj)) and int(np.sign(float(zj))) != sign0:
                    exit_i = j
                    break
        if int(work.iloc[exit_i]["fold"]) != int(row["fold"]):
            i += 1
            continue
        entry = work.iloc[entry_i]
        exit_ = work.iloc[exit_i]
        if min(float(entry["alt_open"]), float(entry["btc_open"]), float(exit_["alt_open"]), float(exit_["btc_open"])) <= 0:
            i += 1
            continue
        alt_raw = float(exit_["alt_open"] / entry["alt_open"] - 1.0)
        btc_raw = float(exit_["btc_open"] / entry["btc_open"] - 1.0)
        alt_weight = 1.0 / (1.0 + abs(beta))
        btc_weight = abs(beta) / (1.0 + abs(beta))
        alt_dir = -1.0 if z > 0 else 1.0
        btc_dir = -alt_dir
        gross = alt_dir * alt_weight * alt_raw + btc_dir * btc_weight * btc_raw
        reversed_gross = -gross
        single_leg_gross = alt_dir * alt_raw
        weighted_cost_bps = cost_bps * (alt_weight + btc_weight)
        net_bps = gross * 10000.0 - weighted_cost_bps
        reversed_net_bps = reversed_gross * 10000.0 - weighted_cost_bps
        single_leg_net_bps = single_leg_gross * 10000.0 - cost_bps
        rows.append(
            {
                "symbol": symbol,
                "signal_time": work.index[i].isoformat(),
                "entry_time": work.index[entry_i].isoformat(),
                "exit_time": work.index[exit_i].isoformat(),
                "fold": int(row["fold"]),
                "beta": beta,
                "z": z,
                "alt_weight": alt_weight,
                "btc_weight": btc_weight,
                "gross_bps": gross * 10000.0,
                "net_bps": net_bps,
                "reversed_net_bps": reversed_net_bps,
                "single_leg_net_bps": single_leg_net_bps,
                "cost_bps": weighted_cost_bps,
            }
        )
        i = exit_i + 1
    return rows


def _economic_summary(trades: pd.DataFrame, min_positive_fold_fraction: float, min_positive_symbol_fraction: float, min_trades: int) -> dict[str, Any]:
    if trades.empty:
        return {"economic_pass": False, "n_trades": 0}
    fold = trades.groupby("fold").agg(net=("net_bps", "mean"), reversed=("reversed_net_bps", "mean"), single=("single_leg_net_bps", "mean"))
    symbol = trades.groupby("symbol")["net_bps"].mean()
    fold_pf = trades.groupby("fold")["net_bps"].apply(lambda x: _profit_factor(x.to_numpy(float)))
    result = {
        "n_trades": int(len(trades)),
        "median_fold_net_expectancy_bps": float(fold["net"].median()),
        "median_fold_profit_factor": float(fold_pf.median()),
        "positive_fold_fraction": float((fold["net"] > 0).mean()),
        "positive_symbol_fraction": float((symbol > 0).mean()),
        "median_fold_reversed_expectancy_bps": float(fold["reversed"].median()),
        "median_fold_single_leg_expectancy_bps": float(fold["single"].median()),
    }
    result["economic_pass"] = bool(
        result["n_trades"] >= min_trades
        and result["median_fold_net_expectancy_bps"] > 0.0
        and result["median_fold_profit_factor"] > 1.0
        and result["positive_fold_fraction"] >= min_positive_fold_fraction
        and result["positive_symbol_fraction"] >= min_positive_symbol_fraction
        and result["median_fold_net_expectancy_bps"] > result["median_fold_reversed_expectancy_bps"]
        and result["median_fold_net_expectancy_bps"] > result["median_fold_single_leg_expectancy_bps"]
    )
    return result


def run(config_path: Path, output_dir: Path) -> dict[str, Any]:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    data_cfg = cfg["data"]
    dep = cfg["dependence_and_trials"]
    beta_cap = float(cfg["portfolio_construction"]["beta_cap"])
    start = pd.Timestamp(data_cfg["development_start"], tz="UTC")
    end = pd.Timestamp(data_cfg["development_end_exclusive"], tz="UTC")
    btc = fetch_mexc_futures_klines(data_cfg["context_symbol"], data_cfg["interval"], str(start), str(end))
    alt_frames = {
        symbol: fetch_mexc_futures_klines(symbol, data_cfg["interval"], str(start), str(end))
        for symbol in data_cfg["tradable_alt_symbols"]
    }

    state_records: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []
    for family, family_cfg in cfg["spread_definitions"].items():
        windows = family_cfg["regression_windows"]
        lookbacks = family_cfg.get("residual_lookbacks", [None])
        for window, lookback, threshold, exit_cfg in itertools.product(
            windows,
            lookbacks,
            cfg["portfolio_construction"]["entry_threshold_z"],
            cfg["portfolio_construction"]["exit_rules"],
        ):
            hold_bars = int(exit_cfg.get("hold_bars", exit_cfg.get("max_hold_bars")))
            key = {
                "family": family,
                "window": int(window),
                "residual_lookback": lookback,
                "threshold": float(threshold),
                "hold_bars": hold_bars,
                "exit_rule": str(exit_cfg["type"]),
            }
            variants.append(key)
            for symbol, alt in alt_frames.items():
                aligned = _build_aligned(alt, btc)
                if family == "rolling_log_price_residual":
                    state = _rolling_log_price_state(aligned, int(window))
                else:
                    state = _rolling_return_state(aligned, int(window), int(lookback))
                state_records.extend(
                    _state_rows(
                        symbol,
                        aligned,
                        state,
                        float(threshold),
                        hold_bars,
                        int(dep["calendar_fold_days"]),
                        start,
                        beta_cap,
                        family,
                        int(window),
                        lookback,
                    )
                )

    state_df = pd.DataFrame(state_records)
    state_summaries: list[dict[str, Any]] = []
    economic_summaries: list[dict[str, Any]] = []
    primary_cost = float(cfg["economics"]["primary_round_trip_cost_bps_per_leg"])
    for variant in variants:
        mask = (
            (state_df["family"] == variant["family"])
            & (state_df["window"] == variant["window"])
            & (state_df["threshold"] == variant["threshold"])
            & (state_df["hold_bars"] == variant["hold_bars"])
        )
        if variant["residual_lookback"] is None:
            mask &= state_df["residual_lookback"].isna()
        else:
            mask &= state_df["residual_lookback"] == variant["residual_lookback"]
        summary = _state_summary(state_df.loc[mask], float(dep["minimum_positive_fold_fraction"]))
        state_summaries.append({**variant, **summary})
        if not summary["state_pass"]:
            continue
        all_trades: list[dict[str, Any]] = []
        for symbol, alt in alt_frames.items():
            aligned = _build_aligned(alt, btc)
            if variant["family"] == "rolling_log_price_residual":
                state = _rolling_log_price_state(aligned, int(variant["window"]))
            else:
                state = _rolling_return_state(aligned, int(variant["window"]), int(variant["residual_lookback"]))
            all_trades.extend(
                _trades_for_variant(
                    symbol,
                    aligned,
                    state,
                    float(variant["threshold"]),
                    int(variant["hold_bars"]),
                    int(dep["calendar_fold_days"]),
                    start,
                    beta_cap,
                    primary_cost,
                    str(variant["exit_rule"]),
                )
            )
        trade_df = pd.DataFrame(all_trades)
        econ = _economic_summary(
            trade_df,
            float(dep["minimum_positive_fold_fraction"]),
            float(dep["minimum_positive_symbol_fraction"]),
            int(dep["minimum_total_portfolio_trades"]),
        )
        economic_summaries.append({**variant, "cost_bps_per_leg": primary_cost, **econ})

    output_dir.mkdir(parents=True, exist_ok=True)
    state_df.to_csv(output_dir / "state_fold_rows.csv", index=False)
    pd.DataFrame(state_summaries).to_csv(output_dir / "state_summary.csv", index=False)
    pd.DataFrame(economic_summaries).to_csv(output_dir / "economic_summary_primary_cost.csv", index=False)
    result = {
        "protocol_name": cfg["protocol_name"],
        "base_research_commit": cfg["base_research_commit"],
        "state_variants": len(state_summaries),
        "state_passes": int(sum(bool(x["state_pass"]) for x in state_summaries)),
        "economic_variants_evaluated": len(economic_summaries),
        "economic_passes": int(sum(bool(x.get("economic_pass")) for x in economic_summaries)),
        "primary_cost_bps_per_leg": primary_cost,
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
        "live_order_transmission_supported": False,
    }
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/two_leg_relative_value_v1.json")
    parser.add_argument("--output-dir", default="research/two_leg_relative_value_v1")
    args = parser.parse_args()
    result = run(Path(args.config), Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

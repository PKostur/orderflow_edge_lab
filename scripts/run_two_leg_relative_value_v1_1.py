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
PERMUTATIONS = 2_000
PERMUTATION_SEED = 20260914


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


def _build_aligned(alt: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    idx = alt.index.intersection(btc.index)
    return pd.DataFrame(
        {
            "alt_open": alt.loc[idx, "open"],
            "alt_close": alt.loc[idx, "close"],
            "alt_volume": alt.loc[idx, "volume"],
            "btc_open": btc.loc[idx, "open"],
            "btc_close": btc.loc[idx, "close"],
            "btc_volume": btc.loc[idx, "volume"],
        },
        index=idx,
    ).dropna().sort_index()


def _common_features(frame: pd.DataFrame, beta: pd.Series, spread: pd.Series, z: pd.Series, window: int) -> pd.DataFrame:
    alt_ret = np.log(frame["alt_close"]).diff()
    btc_ret = np.log(frame["btc_close"]).diff()
    alt_rv = alt_ret.rolling(24).std(ddof=0)
    btc_rv = btc_ret.rolling(24).std(ddof=0)
    rel_vol = (frame["alt_volume"] / frame["alt_volume"].rolling(24).median()).replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame(
        {
            "beta": beta,
            "beta_change": beta.diff(),
            "spread": spread,
            "z": z,
            "btc_realized_volatility": btc_rv,
            "alt_realized_volatility": alt_rv,
            "relative_volume": rel_vol,
        },
        index=frame.index,
    )


def _rolling_log_price_state(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    alt_log = np.log(frame["alt_close"])
    btc_log = np.log(frame["btc_close"])
    beta = alt_log.rolling(window).cov(btc_log) / btc_log.rolling(window).var()
    alpha = alt_log.rolling(window).mean() - beta * btc_log.rolling(window).mean()
    residual = alt_log - alpha - beta * btc_log
    mean = residual.rolling(window).mean()
    std = residual.rolling(window).std(ddof=0)
    z = (residual - mean) / std.replace(0.0, np.nan)
    return _common_features(frame, beta, residual, z, window)


def _rolling_return_state(frame: pd.DataFrame, window: int, residual_lookback: int) -> pd.DataFrame:
    alt_ret = np.log(frame["alt_close"]).diff()
    btc_ret = np.log(frame["btc_close"]).diff()
    beta = alt_ret.rolling(window).cov(btc_ret) / btc_ret.rolling(window).var()
    residual_ret = alt_ret - beta * btc_ret
    spread = residual_ret.rolling(residual_lookback).sum()
    std = spread.rolling(window).std(ddof=0)
    z = spread / std.replace(0.0, np.nan)
    return _common_features(frame, beta, spread, z, window)


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
    future_spread = work["spread"].shift(-hold_bars)
    future_beta = work["beta"].shift(-hold_bars)
    future_fold = work["fold"].shift(-hold_bars)
    work["future_spread_change"] = future_spread - work["spread"]
    work["future_spread_abs_change"] = work["future_spread_change"].abs()
    work["future_beta_abs_change"] = (future_beta - work["beta"]).abs()
    work["mean_reversion_score"] = -work["z"]
    work["continuation_score"] = work["z"]
    eligible = (
        work["beta"].gt(0.0)
        & work["beta"].le(beta_cap)
        & np.isfinite(work["beta"])
        & work["z"].abs().ge(threshold)
        & future_fold.eq(work["fold"])
    )
    rows: list[dict[str, Any]] = []
    for fold, chunk in work.loc[eligible].groupby("fold"):
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
                "rho_reversion": _spearman(chunk["mean_reversion_score"], chunk["future_spread_change"]),
                "rho_continuation": _spearman(chunk["continuation_score"], chunk["future_spread_change"]),
                "rho_expansion": _spearman(chunk["z"].abs(), chunk["future_spread_abs_change"]),
                "rho_beta_instability": _spearman(chunk["beta_change"].abs(), chunk["future_beta_abs_change"]),
            }
        )
    return rows


def _state_summary(rows: pd.DataFrame, dep: dict[str, Any]) -> dict[str, Any]:
    valid = rows[np.isfinite(rows["rho_reversion"])].copy()
    if valid.empty:
        return {"state_pass": False, "median_rho": float("nan"), "positive_fold_fraction": 0.0, "n_scored_folds": 0, "n_scored_symbols": 0}
    by_fold = valid.groupby("fold", as_index=False)["rho_reversion"].median()
    by_symbol = valid.groupby("symbol", as_index=False)["rho_reversion"].median()
    median_rho = float(by_fold["rho_reversion"].median())
    positive_fraction = float((by_fold["rho_reversion"] > 0).mean())
    n_folds = int(len(by_fold))
    n_symbols = int(len(by_symbol))
    return {
        "state_pass": bool(
            median_rho > 0.0
            and positive_fraction >= float(dep["minimum_positive_fold_fraction"])
            and n_folds >= int(dep["minimum_folds"])
            and n_symbols >= int(dep["minimum_symbols"])
        ),
        "median_rho": median_rho,
        "positive_fold_fraction": positive_fraction,
        "n_scored_folds": n_folds,
        "n_scored_symbols": n_symbols,
        "median_symbol_rho": float(by_symbol["rho_reversion"].median()),
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
    cost_bps_per_leg: float,
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
        time_exit_i = i + 1 + hold_bars
        if time_exit_i >= len(work):
            break
        if int(work.iloc[entry_i]["fold"]) != int(row["fold"]) or int(work.iloc[time_exit_i]["fold"]) != int(row["fold"]):
            i += 1
            continue
        exit_i = time_exit_i
        if exit_rule == "spread_cross_zero_or_time":
            sign0 = 1 if z > 0 else -1
            for observed_i in range(entry_i, time_exit_i):
                observed_z = work.iloc[observed_i]["z"]
                if pd.notna(observed_z) and math.isfinite(float(observed_z)) and int(np.sign(float(observed_z))) != sign0:
                    candidate_exit_i = observed_i + 1
                    if candidate_exit_i <= time_exit_i:
                        exit_i = candidate_exit_i
                    break
        if int(work.iloc[exit_i]["fold"]) != int(row["fold"]):
            i += 1
            continue
        entry = work.iloc[entry_i]
        exit_ = work.iloc[exit_i]
        prices = [entry["alt_open"], entry["btc_open"], exit_["alt_open"], exit_["btc_open"]]
        if any(pd.isna(x) or float(x) <= 0 for x in prices):
            i += 1
            continue
        alt_raw = float(exit_["alt_open"] / entry["alt_open"] - 1.0)
        btc_raw = float(exit_["btc_open"] / entry["btc_open"] - 1.0)
        alt_weight = 1.0 / (1.0 + abs(beta))
        btc_weight = abs(beta) / (1.0 + abs(beta))
        alt_dir = -1.0 if z > 0 else 1.0
        btc_dir = -alt_dir
        gross_bps = (alt_dir * alt_weight * alt_raw + btc_dir * btc_weight * btc_raw) * 10000.0
        reversed_gross_bps = -gross_bps
        single_leg_gross_bps = alt_dir * alt_raw * 10000.0
        beta1_gross_bps = (alt_dir * 0.5 * alt_raw + btc_dir * 0.5 * btc_raw) * 10000.0
        portfolio_cost_bps = cost_bps_per_leg * (alt_weight + btc_weight)
        beta1_cost_bps = cost_bps_per_leg
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
                "gross_bps": gross_bps,
                "cost_bps": portfolio_cost_bps,
                "net_bps": gross_bps - portfolio_cost_bps,
                "reversed_net_bps": reversed_gross_bps - portfolio_cost_bps,
                "single_leg_net_bps": single_leg_gross_bps - cost_bps_per_leg,
                "beta1_net_bps": beta1_gross_bps - beta1_cost_bps,
            }
        )
        i = exit_i + 1
    return rows


def _permutation_control(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"permutation_p": float("nan"), "permutation_p95_median_fold_bps": float("nan")}
    observed = float(trades.groupby("fold")["net_bps"].mean().median())
    rng = np.random.default_rng(PERMUTATION_SEED)
    null = np.empty(PERMUTATIONS, dtype=float)
    gross = trades["gross_bps"].to_numpy(float)
    costs = trades["cost_bps"].to_numpy(float)
    folds = trades["fold"].to_numpy(int)
    groups = trades.groupby(["symbol", "fold"]).indices
    for k in range(PERMUTATIONS):
        sign = np.ones(len(trades), dtype=float)
        for idx in groups.values():
            arr = np.asarray(idx, dtype=int)
            sign[arr] = rng.choice(np.array([-1.0, 1.0]), size=len(arr), replace=True)
        perm_net = gross * sign - costs
        fold_means = [float(perm_net[folds == f].mean()) for f in np.unique(folds)]
        null[k] = float(np.median(fold_means))
    p = float((1.0 + np.sum(null >= observed)) / (PERMUTATIONS + 1.0))
    return {"permutation_p": p, "permutation_p95_median_fold_bps": float(np.quantile(null, 0.95))}


def _economic_summary(trades: pd.DataFrame, dep: dict[str, Any]) -> dict[str, Any]:
    if trades.empty:
        return {"base_economic_pass": False, "n_trades": 0}
    fold = trades.groupby("fold").agg(
        net=("net_bps", "mean"),
        reversed=("reversed_net_bps", "mean"),
        single=("single_leg_net_bps", "mean"),
        beta1=("beta1_net_bps", "mean"),
    )
    symbol = trades.groupby("symbol")["net_bps"].mean()
    fold_pf = trades.groupby("fold")["net_bps"].apply(lambda x: _profit_factor(x.to_numpy(float)))
    result: dict[str, Any] = {
        "n_trades": int(len(trades)),
        "n_folds": int(len(fold)),
        "n_symbols": int(len(symbol)),
        "median_fold_net_expectancy_bps": float(fold["net"].median()),
        "median_fold_profit_factor": float(fold_pf.median()),
        "positive_fold_fraction": float((fold["net"] > 0).mean()),
        "positive_symbol_fraction": float((symbol > 0).mean()),
        "median_fold_reversed_expectancy_bps": float(fold["reversed"].median()),
        "median_fold_single_leg_expectancy_bps": float(fold["single"].median()),
        "median_fold_beta1_expectancy_bps": float(fold["beta1"].median()),
    }
    result.update(_permutation_control(trades))
    result["base_economic_pass"] = bool(
        result["n_trades"] >= int(dep["minimum_total_portfolio_trades"])
        and result["n_folds"] >= int(dep["minimum_folds"])
        and result["n_symbols"] >= int(dep["minimum_symbols"])
        and result["median_fold_net_expectancy_bps"] > 0.0
        and result["median_fold_profit_factor"] > 1.0
        and result["positive_fold_fraction"] >= float(dep["minimum_positive_fold_fraction"])
        and result["positive_symbol_fraction"] >= float(dep["minimum_positive_symbol_fraction"])
        and result["median_fold_net_expectancy_bps"] > result["median_fold_reversed_expectancy_bps"]
        and result["median_fold_net_expectancy_bps"] > result["median_fold_single_leg_expectancy_bps"]
        and result["permutation_p"] < 0.05
    )
    return result


def _association_rows(symbol: str, state: pd.DataFrame) -> list[dict[str, Any]]:
    features = ["z", "beta", "beta_change", "btc_realized_volatility", "alt_realized_volatility", "relative_volume"]
    clean = state[features].replace([np.inf, -np.inf], np.nan)
    corr = clean.corr(method="spearman")
    rows: list[dict[str, Any]] = []
    for i, left in enumerate(features):
        for right in features[i + 1 :]:
            value = corr.loc[left, right] if left in corr.index and right in corr.columns else np.nan
            rows.append({"symbol": symbol, "feature_a": left, "feature_b": right, "abs_spearman": abs(float(value)) if pd.notna(value) else float("nan")})
    return rows


def _is_neighbor(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["family"] != b["family"] or a["exit_rule"] != b["exit_rule"]:
        return False
    keys = ["window", "residual_lookback", "threshold", "hold_bars"]
    return sum(a.get(k) != b.get(k) for k in keys) == 1


def run(config_path: Path, output_dir: Path) -> dict[str, Any]:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    data_cfg = cfg["data"]
    dep = cfg["dependence_and_trials"]
    beta_cap = float(cfg["portfolio_construction"]["beta_cap"])
    start = pd.Timestamp(data_cfg["development_start"], tz="UTC")
    end = pd.Timestamp(data_cfg["development_end_exclusive"], tz="UTC")
    btc = fetch_mexc_futures_klines(data_cfg["context_symbol"], data_cfg["interval"], str(start), str(end))
    alt_frames = {symbol: fetch_mexc_futures_klines(symbol, data_cfg["interval"], str(start), str(end)) for symbol in data_cfg["tradable_alt_symbols"]}

    state_records: list[dict[str, Any]] = []
    association_records: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []
    state_cache: dict[tuple[str, str, int, int | None], tuple[pd.DataFrame, pd.DataFrame]] = {}

    for family, family_cfg in cfg["spread_definitions"].items():
        windows = family_cfg["regression_windows"]
        lookbacks = family_cfg.get("residual_lookbacks", [None])
        for window, lookback in itertools.product(windows, lookbacks):
            for symbol, alt in alt_frames.items():
                aligned = _build_aligned(alt, btc)
                state = _rolling_log_price_state(aligned, int(window)) if family == "rolling_log_price_residual" else _rolling_return_state(aligned, int(window), int(lookback))
                state_cache[(symbol, family, int(window), lookback)] = (aligned, state)
                association_records.extend(_association_rows(symbol, state))
        for window, lookback, threshold, exit_cfg in itertools.product(windows, lookbacks, cfg["portfolio_construction"]["entry_threshold_z"], cfg["portfolio_construction"]["exit_rules"]):
            hold_bars = int(exit_cfg.get("hold_bars", exit_cfg.get("max_hold_bars")))
            variant = {"family": family, "window": int(window), "residual_lookback": lookback, "threshold": float(threshold), "hold_bars": hold_bars, "exit_rule": str(exit_cfg["type"])}
            variants.append(variant)
            for symbol in alt_frames:
                aligned, state = state_cache[(symbol, family, int(window), lookback)]
                state_records.extend(_state_rows(symbol, aligned, state, float(threshold), hold_bars, int(dep["calendar_fold_days"]), start, beta_cap, family, int(window), lookback))

    state_df = pd.DataFrame(state_records)
    state_summaries: list[dict[str, Any]] = []
    economic_summaries: list[dict[str, Any]] = []
    for variant in variants:
        mask = (state_df["family"] == variant["family"]) & (state_df["window"] == variant["window"]) & (state_df["threshold"] == variant["threshold"]) & (state_df["hold_bars"] == variant["hold_bars"])
        mask &= state_df["residual_lookback"].isna() if variant["residual_lookback"] is None else state_df["residual_lookback"].eq(variant["residual_lookback"])
        state_summary = _state_summary(state_df.loc[mask], dep)
        state_summaries.append({**variant, **state_summary})
        if not state_summary["state_pass"]:
            continue
        for cost in cfg["economics"]["round_trip_cost_bps_per_leg"]:
            all_trades: list[dict[str, Any]] = []
            for symbol in alt_frames:
                aligned, state = state_cache[(symbol, variant["family"], int(variant["window"]), variant["residual_lookback"])]
                all_trades.extend(_trades_for_variant(symbol, aligned, state, float(variant["threshold"]), int(variant["hold_bars"]), int(dep["calendar_fold_days"]), start, beta_cap, float(cost), str(variant["exit_rule"])))
            trade_df = pd.DataFrame(all_trades)
            econ = _economic_summary(trade_df, dep)
            economic_summaries.append({**variant, "cost_bps_per_leg": float(cost), **econ})

    econ_df = pd.DataFrame(economic_summaries)
    primary_cost = float(cfg["economics"]["primary_round_trip_cost_bps_per_leg"])
    if not econ_df.empty:
        primary = econ_df[econ_df["cost_bps_per_leg"].eq(primary_cost)].copy()
        support: dict[int, int] = {}
        for idx, row in primary.iterrows():
            current = row.to_dict()
            count = 0
            for jdx, other in primary.iterrows():
                if idx == jdx or not bool(other.get("base_economic_pass", False)):
                    continue
                if _is_neighbor(current, other.to_dict()):
                    count += 1
            support[idx] = count
        econ_df["parameter_neighborhood_support"] = 0
        for idx, count in support.items():
            econ_df.loc[idx, "parameter_neighborhood_support"] = count
        econ_df["economic_pass"] = econ_df["base_economic_pass"].fillna(False) & econ_df["cost_bps_per_leg"].eq(primary_cost) & econ_df["parameter_neighborhood_support"].gt(0)
    else:
        econ_df = pd.DataFrame()

    assoc_df = pd.DataFrame(association_records)
    assoc_summary = assoc_df.groupby(["feature_a", "feature_b"], as_index=False)["abs_spearman"].median() if not assoc_df.empty else pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_df.to_csv(output_dir / "state_fold_rows.csv", index=False)
    pd.DataFrame(state_summaries).to_csv(output_dir / "state_summary.csv", index=False)
    econ_df.to_csv(output_dir / "economic_summary_all_costs.csv", index=False)
    assoc_df.to_csv(output_dir / "feature_association_by_symbol.csv", index=False)
    assoc_summary.to_csv(output_dir / "feature_association_median.csv", index=False)
    result = {
        "protocol_name": cfg["protocol_name"],
        "implementation_amendment": "two-leg-relative-value-v1.1-amendment",
        "base_research_commit": cfg["base_research_commit"],
        "state_variants": len(state_summaries),
        "state_passes": int(sum(bool(x["state_pass"]) for x in state_summaries)),
        "economic_variants_evaluated": int(len(econ_df)),
        "primary_cost_base_passes": int(((econ_df.get("cost_bps_per_leg", pd.Series(dtype=float)) == primary_cost) & econ_df.get("base_economic_pass", pd.Series(dtype=bool)).fillna(False)).sum()) if not econ_df.empty else 0,
        "economic_passes_after_neighborhood_gate": int(econ_df.get("economic_pass", pd.Series(dtype=bool)).fillna(False).sum()) if not econ_df.empty else 0,
        "primary_cost_bps_per_leg": primary_cost,
        "permutations_per_economic_variant": PERMUTATIONS,
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
    print(json.dumps(run(Path(args.config), Path(args.output_dir)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import math
import runpy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load_source_namespace() -> dict[str, Any]:
    adapter = runpy.run_path(str(Path(__file__).with_name("run_strategy_discovery_v2_1_3.py")))
    ns = adapter.get("namespace")
    if not isinstance(ns, dict):
        raise RuntimeError("v2.1.3 adapter did not expose its patched namespace")
    required = {"load_frame", "aligned_pair", "score_family", "fold_labels", "pf"}
    missing = sorted(required.difference(ns))
    if missing:
        raise RuntimeError(f"missing v2.1.3 source functions: {missing}")
    return ns


def source_frames(data_dir: Path, interval: str, ns: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.Timestamp]:
    load_frame = ns["load_frame"]
    btc = load_frame(data_dir / f"BTC_USDT_{interval}.csv")
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(data_dir.glob(f"*_{interval}.csv")):
        symbol = path.name[: -len(f"_{interval}.csv")]
        if symbol == "BTC_USDT":
            continue
        frames[symbol] = load_frame(path)
    if len(frames) != 9:
        raise RuntimeError(f"expected 9 conditioning symbols, found {len(frames)}")
    global_start = max([btc.index.min()] + [f.index.min() for f in frames.values()])
    return btc, frames, global_start


def exact_trades(
    *,
    data_dir: Path,
    interval: str,
    family: str,
    params: dict[str, Any],
    cost_bps: float,
    ns: dict[str, Any],
) -> pd.DataFrame:
    aligned_pair = ns["aligned_pair"]
    score_family = ns["score_family"]
    fold_labels = ns["fold_labels"]

    btc, frames, global_start = source_frames(data_dir, interval, ns)
    hold = int(params["hold_bars"])
    rows: list[dict[str, Any]] = []

    for symbol, f0 in frames.items():
        f, b = aligned_pair(f0, btc)
        score, eligible = score_family(f, b, family, params)
        entry = f["open"].shift(-1)
        exit_px = f["open"].shift(-(1 + hold))
        fwd = exit_px / entry - 1.0
        exits = pd.Series(f.index, index=f.index).shift(-(1 + hold))
        folds = fold_labels(f.index, global_start, 21)

        exit_folds = pd.Series(np.nan, index=f.index, dtype=float)
        exit_mask = exits.notna()
        if exit_mask.any():
            delta = (pd.DatetimeIndex(exits.loc[exit_mask]) - global_start) / pd.Timedelta(days=21)
            exit_folds.loc[exit_mask] = np.floor(delta).astype(int)

        d = pd.DataFrame(
            {
                "score": score,
                "eligible": eligible,
                "entry_px": entry,
                "exit_px": exit_px,
                "fwd": fwd,
                "fold": folds,
                "exit_fold": exit_folds,
                "exit_ts": exits,
            },
            index=f.index,
        )
        d = d[
            d["eligible"]
            & d["score"].notna()
            & d["fwd"].notna()
            & d["exit_ts"].notna()
            & (d["fold"] >= 0)
            & (d["exit_fold"] == d["fold"])
        ]

        next_allowed = pd.Timestamp.min.tz_localize("UTC")
        for signal_ts, row in d.iterrows():
            if signal_ts < next_allowed:
                continue
            side = 1.0 if float(row["score"]) > 0 else -1.0
            gross_bps = side * float(row["fwd"]) * 10000.0
            entry_pos = f.index.get_loc(signal_ts) + 1
            if not isinstance(entry_pos, int):
                raise RuntimeError("unexpected non-scalar entry position")
            entry_ts = f.index[entry_pos]
            exit_ts = pd.Timestamp(row["exit_ts"])
            path = f.loc[(f.index >= entry_ts) & (f.index < exit_ts)]
            ep = float(row["entry_px"])

            if path.empty:
                mae = float("nan")
                mfe = float("nan")
            elif side > 0:
                mae = float((path["low"] / ep - 1.0).min())
                mfe = float((path["high"] / ep - 1.0).max())
            else:
                mae = float((1.0 - path["high"] / ep).min())
                mfe = float((1.0 - path["low"] / ep).max())

            rows.append(
                {
                    "symbol": symbol,
                    "signal_ts": signal_ts,
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "fold": int(row["fold"]),
                    "side": int(side),
                    "score": float(row["score"]),
                    "entry_px": ep,
                    "exit_px": float(row["exit_px"]),
                    "gross_bps": gross_bps,
                    "net_bps": gross_bps - float(cost_bps),
                    "mae_pct": mae,
                    "mfe_pct": mfe,
                }
            )
            next_allowed = exit_ts

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["signal_ts", "symbol"]).reset_index(drop=True)


def profit_factor(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    pos = float(arr[arr > 0].sum())
    neg = float(-arr[arr < 0].sum())
    if neg <= 0:
        return 1_000_000.0 if pos > 0 else 0.0
    return pos / neg


def candidate_robustness(trades: pd.DataFrame, trim_fraction: float) -> dict[str, Any]:
    values = np.sort(trades["net_bps"].to_numpy(dtype=float))
    k = int(len(values) * trim_fraction)
    trimmed = values[k : len(values) - k] if k > 0 and 2 * k < len(values) else values

    symbol_means = trades.groupby("symbol")["net_bps"].mean()
    fold_means = trades.groupby("fold")["net_bps"].mean()
    side_rows = []
    for side, g in trades.groupby("side"):
        side_rows.append(
            {
                "side": int(side),
                "trades": int(len(g)),
                "mean_net_bps": float(g["net_bps"].mean()),
                "median_net_bps": float(g["net_bps"].median()),
                "win_rate": float((g["net_bps"] > 0).mean()),
            }
        )

    leave_symbol = {}
    for symbol in sorted(trades["symbol"].unique()):
        g = trades[trades["symbol"] != symbol]
        fm = g.groupby("fold")["net_bps"].mean()
        leave_symbol[symbol] = {
            "mean_net_bps": float(g["net_bps"].mean()),
            "median_fold_net_bps": float(fm.median()),
            "positive_fold_fraction": float((fm > 0).mean()),
        }

    leave_fold = {}
    for fold in sorted(int(x) for x in trades["fold"].unique()):
        g = trades[trades["fold"] != fold]
        fm = g.groupby("fold")["net_bps"].mean()
        leave_fold[str(fold)] = {
            "mean_net_bps": float(g["net_bps"].mean()),
            "median_fold_net_bps": float(fm.median()),
            "positive_fold_fraction": float((fm > 0).mean()),
        }

    top_n = max(1, int(len(trades) * trim_fraction))
    total = float(trades["net_bps"].sum())
    top_sum = float(trades.nlargest(top_n, "net_bps")["net_bps"].sum())

    return {
        "trades": int(len(trades)),
        "mean_net_bps": float(trades["net_bps"].mean()),
        "median_trade_net_bps": float(trades["net_bps"].median()),
        "profit_factor": float(profit_factor(trades["net_bps"])),
        "win_rate": float((trades["net_bps"] > 0).mean()),
        "median_fold_net_bps": float(fold_means.median()),
        "positive_fold_fraction": float((fold_means > 0).mean()),
        "positive_symbol_fraction": float((symbol_means > 0).mean()),
        "trim_fraction_each_tail": float(trim_fraction),
        "trimmed_mean_net_bps": float(trimmed.mean()),
        "top_fraction_trade_count": int(top_n),
        "top_fraction_sum_share_of_total": (top_sum / total) if abs(total) > 1e-12 else None,
        "best_symbol": str(symbol_means.idxmax()),
        "best_symbol_mean_net_bps": float(symbol_means.max()),
        "worst_symbol": str(symbol_means.idxmin()),
        "worst_symbol_mean_net_bps": float(symbol_means.min()),
        "best_fold": int(fold_means.idxmax()),
        "best_fold_mean_net_bps": float(fold_means.max()),
        "worst_fold": int(fold_means.idxmin()),
        "worst_fold_mean_net_bps": float(fold_means.min()),
        "side_decomposition": side_rows,
        "leave_one_symbol_out": leave_symbol,
        "leave_one_fold_out": leave_fold,
    }


def exact_portfolio_replay(trades: pd.DataFrame, leverage: float, enforce_mae_breach: bool) -> dict[str, Any]:
    symbols = sorted(str(x) for x in trades["symbol"].unique())
    sleeves = {s: 1.0 / len(symbols) for s in symbols}
    alive = {s: True for s in symbols}
    equity_points: list[float] = []
    breach_rows: list[dict[str, Any]] = []

    for _, group in trades.sort_values("exit_ts").groupby("exit_ts", sort=True):
        for _, row in group.iterrows():
            symbol = str(row["symbol"])
            if not alive[symbol]:
                continue
            if enforce_mae_breach and float(row["mae_pct"]) <= -1.0 / float(leverage):
                sleeves[symbol] = 0.0
                alive[symbol] = False
                breach_rows.append(
                    {
                        "symbol": symbol,
                        "entry_ts": pd.Timestamp(row["entry_ts"]).isoformat(),
                        "exit_ts": pd.Timestamp(row["exit_ts"]).isoformat(),
                        "mae_pct": float(row["mae_pct"]),
                    }
                )
                continue

            factor = 1.0 + float(leverage) * float(row["net_bps"]) / 10000.0
            if factor <= 0:
                sleeves[symbol] = 0.0
                alive[symbol] = False
                breach_rows.append(
                    {
                        "symbol": symbol,
                        "entry_ts": pd.Timestamp(row["entry_ts"]).isoformat(),
                        "exit_ts": pd.Timestamp(row["exit_ts"]).isoformat(),
                        "mae_pct": float(row["mae_pct"]),
                        "reason": "exit_return_exhausted_sleeve",
                    }
                )
            else:
                sleeves[symbol] *= factor
        equity_points.append(sum(sleeves.values()))

    eq = pd.Series(equity_points, dtype=float)
    max_dd = float((eq / eq.cummax() - 1.0).min()) if not eq.empty else 0.0
    return {
        "terminal_equity_multiple": float(sum(sleeves.values())),
        "max_drawdown_exit_marked": max_dd,
        "surviving_symbol_sleeves": int(sum(1 for x in alive.values() if x)),
        "breach_count": int(len(breach_rows)),
        "breaches": breach_rows,
    }


def fold_symbol_factors(trades: pd.DataFrame, leverage: float, enforce_mae_breach: bool) -> tuple[list[str], list[int], np.ndarray]:
    symbols = sorted(str(x) for x in trades["symbol"].unique())
    folds = sorted(int(x) for x in trades["fold"].unique())
    mat = np.ones((len(folds), len(symbols)), dtype=float)

    for i, fold in enumerate(folds):
        for j, symbol in enumerate(symbols):
            g = trades[(trades["fold"] == fold) & (trades["symbol"] == symbol)].sort_values("exit_ts")
            factor = 1.0
            for _, row in g.iterrows():
                if enforce_mae_breach and float(row["mae_pct"]) <= -1.0 / float(leverage):
                    factor = 0.0
                    break
                m = 1.0 + float(leverage) * float(row["net_bps"]) / 10000.0
                if m <= 0:
                    factor = 0.0
                    break
                factor *= m
            mat[i, j] = factor
    return symbols, folds, mat


def bootstrap_terminal(
    trades: pd.DataFrame,
    leverage: float,
    *,
    epochs: int,
    seed: int,
    enforce_mae_breach: bool,
) -> dict[str, Any]:
    symbols, folds, mat = fold_symbol_factors(trades, leverage, enforce_mae_breach)
    rng = np.random.default_rng(seed)
    draw_idx = rng.integers(0, len(folds), size=(int(epochs), len(folds)))
    selected = mat[draw_idx, :]
    sleeve_multipliers = selected.prod(axis=1)
    terminal = sleeve_multipliers.mean(axis=1)

    return {
        "epochs": int(epochs),
        "dependence_clusters_per_epoch": int(len(folds)),
        "symbol_sleeves": int(len(symbols)),
        "median_terminal_equity_multiple": float(np.median(terminal)),
        "p05_terminal_equity_multiple": float(np.quantile(terminal, 0.05)),
        "p95_terminal_equity_multiple": float(np.quantile(terminal, 0.95)),
        "probability_terminal_below_start": float(np.mean(terminal < 1.0)),
        "probability_terminal_below_half": float(np.mean(terminal < 0.5)),
        "probability_terminal_at_least_double": float(np.mean(terminal >= 2.0)),
    }


def leverage_diagnostic(
    trades: pd.DataFrame,
    leverage: float,
    *,
    epochs: int,
    seed: int,
) -> dict[str, Any]:
    fold_means = trades.groupby("fold")["net_bps"].mean()
    mae_breach_mask = trades["mae_pct"] <= -1.0 / float(leverage)
    exit_only = exact_portfolio_replay(trades, leverage, enforce_mae_breach=False)
    breach_bound = exact_portfolio_replay(trades, leverage, enforce_mae_breach=True)
    boot = bootstrap_terminal(trades, leverage, epochs=epochs, seed=seed, enforce_mae_breach=False)
    boot_breach = bootstrap_terminal(trades, leverage, epochs=epochs, seed=seed + 1_000_000, enforce_mae_breach=True)

    return {
        "leverage": float(leverage),
        "scaled_mean_trade_net_bps_on_equity": float(leverage * trades["net_bps"].mean()),
        "scaled_median_fold_net_bps_on_equity": float(leverage * fold_means.median()),
        "profit_factor_invariant_under_linear_scaling": float(profit_factor(trades["net_bps"])),
        "positive_fold_fraction_invariant": float((fold_means > 0).mean()),
        "mae_wipeout_bound_underlying_pct": float(-1.0 / float(leverage)),
        "mae_bound_breach_trades": int(mae_breach_mask.sum()),
        "mae_bound_breach_fraction": float(mae_breach_mask.mean()),
        "exact_exit_portfolio": exit_only,
        "mae_breach_bound_portfolio": breach_bound,
        "bootstrap_exit_only": boot,
        "bootstrap_mae_breach_bound": boot_breach,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--data-1h", required=True)
    p.add_argument("--data-15m", required=True)
    p.add_argument("--output", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ns = load_source_namespace()

    result: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": config["protocol_name"],
        "status": config["status"],
        "source_protocol": config["source_protocol"],
        "source_workflow_run_id": config["source_workflow_run_id"],
        "source_head_sha": config["source_head_sha"],
        "selection": {
            "outcome_dependent": True,
            "can_support_edge_claim": False,
            "rule": config["selection"]["rule"],
        },
        "bootstrap": config["bootstrap"],
        "candidates": [],
        "claims": config["claims"],
    }

    data_dirs = {"1h": Path(args.data_1h), "15m": Path(args.data_15m)}
    cost = float(config["economics"]["source_round_trip_cost_bps"])
    epochs = int(config["bootstrap"]["epochs"])
    base_seed = int(config["bootstrap"]["seed"])
    trim = float(config["robustness"]["trim_fraction_each_tail"])

    for candidate_index, candidate in enumerate(config["selection"]["candidates"]):
        interval = candidate["interval"]
        trades = exact_trades(
            data_dir=data_dirs[interval],
            interval=interval,
            family=candidate["family"],
            params=candidate["params"],
            cost_bps=cost,
            ns=ns,
        )
        if len(trades) != int(candidate["expected_total_trades"]):
            raise RuntimeError(
                f"{candidate['label']}: source trade count changed: {len(trades)} != {candidate['expected_total_trades']}"
            )
        fold_median = float(trades.groupby("fold")["net_bps"].mean().median())
        if not math.isclose(fold_median, float(candidate["expected_median_fold_net_bps"]), rel_tol=0.0, abs_tol=1e-10):
            raise RuntimeError(
                f"{candidate['label']}: source median fold net changed: {fold_median} != {candidate['expected_median_fold_net_bps']}"
            )

        row = {
            "label": candidate["label"],
            "interval": interval,
            "family": candidate["family"],
            "params": candidate["params"],
            "source_trade_count_verified": True,
            "source_median_fold_net_verified": True,
            "robustness": candidate_robustness(trades, trim),
            "leverage_tests": [],
        }
        for leverage in config["economics"]["leverage_multipliers"]:
            row["leverage_tests"].append(
                leverage_diagnostic(
                    trades,
                    float(leverage),
                    epochs=epochs,
                    seed=base_seed + candidate_index * 10_000 + int(leverage) * 101,
                )
            )
        result["candidates"].append(row)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "protocol_name": result["protocol_name"],
                "candidate_count": len(result["candidates"]),
                "bootstrap_epochs_each": epochs,
                "source_trade_counts_verified": all(c["source_trade_count_verified"] for c in result["candidates"]),
                "claims": result["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

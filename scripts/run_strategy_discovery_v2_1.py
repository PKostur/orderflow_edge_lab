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
    tr = pd.concat([(frame["high"] - frame["low"]).abs(), (frame["high"] - pc).abs(), (frame["low"] - pc).abs()], axis=1).max(axis=1)
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
    h = frame["high"].where(in_open).groupby(day).transform("max")
    l = frame["low"].where(in_open).groupby(day).transform("min")
    active = order >= int(opening_bars)
    return h, l, active


def aligned_pair(frame: pd.DataFrame, btc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = frame.index.intersection(btc.index)
    return frame.loc[idx].copy(), btc.loc[idx].copy()


def score_family(frame: pd.DataFrame, btc: pd.DataFrame, family: str, p: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    frame, btc = aligned_pair(frame, btc)
    close = frame["close"]
    btc_close = btc["close"]
    a = atr(frame)
    eligible = pd.Series(True, index=frame.index)

    if family.startswith("session_vwap_"):
        vwap = session_vwap(frame)
        raw = (close - vwap) / a.replace(0.0, np.nan)
        raw = raw if family.endswith("trend") else -raw
        eligible &= raw.abs() >= float(p["threshold"])
        return raw, eligible

    if family.startswith("opening_range_"):
        hi, lo, active = opening_range(frame, int(p["opening_bars"]))
        dist = pd.Series(0.0, index=frame.index)
        dist = dist.mask(close > hi, (close - hi) / a.replace(0.0, np.nan))
        dist = dist.mask(close < lo, (close - lo) / a.replace(0.0, np.nan))
        if family.endswith("reversal"):
            dist = -dist
        eligible &= active & (dist.abs() >= float(p["threshold_atr"])) & (dist != 0)
        return dist, eligible

    ret1 = close.pct_change()
    if family.startswith("volume_shock_"):
        lb = int(p["return_lookback"])
        r = close.pct_change(lb)
        rz = r / (ret1.rolling(96, min_periods=48).std(ddof=0) * math.sqrt(lb)).replace(0.0, np.nan)
        vz = rolling_z(np.log1p(frame["volume"]), 96)
        raw = rz if family.endswith("continuation") else -rz
        eligible &= vz >= float(p["volume_z"])
        return raw, eligible

    if family.startswith("range_expansion_"):
        pc = close.shift(1)
        tr = pd.concat([(frame["high"] - frame["low"]).abs(), (frame["high"] - pc).abs(), (frame["low"] - pc).abs()], axis=1).max(axis=1)
        rz = rolling_z(tr / close.replace(0.0, np.nan), 96)
        direction = np.sign(close.pct_change()).replace(0.0, np.nan)
        raw = direction * rz.clip(lower=0.0)
        if family.endswith("fade"):
            raw = -raw
        eligible &= rz >= float(p["range_z"])
        return raw, eligible

    if family.startswith("btc_relative_strength_"):
        lb = int(p["lookback"])
        rel = close.pct_change(lb) - btc_close.pct_change(lb)
        z = rolling_z(rel, 96)
        raw = z if family.endswith("momentum") else -z
        eligible &= z.abs() >= float(p["threshold_z"])
        return raw, eligible

    ar = close.pct_change()
    br = btc_close.pct_change()
    if family.startswith("beta_residual_"):
        bw = int(p["beta_window"])
        beta = ar.rolling(bw, min_periods=max(30, bw // 2)).cov(br) / br.rolling(bw, min_periods=max(30, bw // 2)).var().replace(0.0, np.nan)
        resid = ar - beta * br
        lb = int(p["residual_lookback"])
        agg = resid.rolling(lb, min_periods=lb).sum()
        z = agg / (resid.rolling(bw, min_periods=max(30, bw // 2)).std(ddof=0) * math.sqrt(lb)).replace(0.0, np.nan)
        raw = z if family.endswith("momentum") else -z
        eligible &= z.abs() >= float(p["threshold_z"])
        return raw, eligible

    if family.startswith("rolling_beta_spread_"):
        w = int(p["regression_window"])
        la = np.log(close)
        lb = np.log(btc_close)
        beta = la.rolling(w, min_periods=max(30, w // 2)).cov(lb) / lb.rolling(w, min_periods=max(30, w // 2)).var().replace(0.0, np.nan)
        alpha = la.rolling(w, min_periods=max(30, w // 2)).mean() - beta * lb.rolling(w, min_periods=max(30, w // 2)).mean()
        resid = la - alpha - beta * lb
        z = rolling_z(resid, w)
        raw = z if family.endswith("momentum") else -z
        eligible &= z.abs() >= float(p["threshold_z"])
        return raw, eligible

    raise ValueError(f"unknown family {family}")


def forward_return(frame: pd.DataFrame, hold: int) -> pd.Series:
    entry = frame["open"].shift(-1)
    exit_ = frame["open"].shift(-(1 + int(hold)))
    return exit_ / entry - 1.0


def fold_labels(index: pd.DatetimeIndex, start: pd.Timestamp, fold_days: int) -> pd.Series:
    delta = (index - start) / pd.Timedelta(days=fold_days)
    return pd.Series(np.floor(delta).astype(int), index=index)


def spearman(x: Iterable[float], y: Iterable[float]) -> float:
    a = pd.Series(list(x), dtype=float)
    b = pd.Series(list(y), dtype=float)
    mask = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 8:
        return float("nan")
    ar = a[mask].rank(method="average")
    br = b[mask].rank(method="average")
    return float(ar.corr(br))


def pf(values: list[float]) -> float:
    pos = sum(v for v in values if v > 0)
    neg = -sum(v for v in values if v < 0)
    if neg <= 0:
        return float("inf") if pos > 0 else 0.0
    return pos / neg


def median_finite(vals: list[float]) -> float:
    arr = [v for v in vals if np.isfinite(v)]
    return float(np.median(arr)) if arr else float("nan")


def run(config: dict[str, Any], data_dir: Path, interval: str) -> dict[str, Any]:
    symbols = [s for s in config["data"]["symbols"] if s != config["data"]["context_symbol"]]
    btc = load_frame(data_dir / f"{config['data']['context_symbol']}_{interval}.csv")
    frames = {s: load_frame(data_dir / f"{s}_{interval}.csv") for s in symbols}
    global_start = max([btc.index.min()] + [f.index.min() for f in frames.values()])
    fold_days = int(config["dependence_and_trials"]["calendar_fold_days"])
    costs = [float(x) for x in config["economics"]["round_trip_cost_bps"]]
    primary_cost = float(config["economics"]["primary_cost_bps"])
    state_trials: list[dict[str, Any]] = []
    translations: list[dict[str, Any]] = []

    for family, spec in config["families"].items():
        for params in expand_grid(spec["grid"]):
            hold = int(params["hold_bars"])
            obs: list[dict[str, Any]] = []
            per_symbol: dict[str, pd.DataFrame] = {}
            for symbol, f0 in frames.items():
                f, b = aligned_pair(f0, btc)
                score, eligible = score_family(f, b, family, params)
                fr = forward_return(f, hold)
                folds = fold_labels(f.index, global_start, fold_days)
                d = pd.DataFrame({"score": score, "eligible": eligible, "fwd": fr, "fold": folds}, index=f.index)
                d = d[d["eligible"] & d["score"].notna() & d["fwd"].notna() & (d["fold"] >= 0)]
                per_symbol[symbol] = d
                for row in d.itertuples():
                    obs.append({"symbol": symbol, "timestamp": row.Index, "fold": int(row.fold), "score": float(row.score), "fwd": float(row.fwd)})
            od = pd.DataFrame(obs)
            if od.empty:
                continue
            fold_rhos: list[float] = []
            for _, g in od.groupby("fold"):
                rho = spearman(g["score"], g["fwd"])
                if np.isfinite(rho):
                    fold_rhos.append(float(rho))
            med_rho = median_finite(fold_rhos)
            pos_frac = float(np.mean([r > 0 for r in fold_rhos])) if fold_rhos else 0.0
            state_pass = (
                len(fold_rhos) >= int(config["dependence_and_trials"]["minimum_folds"])
                and med_rho > 0
                and pos_frac >= float(config["state_screen"]["minimum_positive_fold_fraction"])
            )
            state_trials.append({
                "family": family, "interval": interval, "params": params, "folds": len(fold_rhos),
                "median_fold_spearman": med_rho, "positive_fold_fraction": pos_frac,
                "eligible_observations": len(od), "state_pass": bool(state_pass)
            })
            if not state_pass:
                continue

            for cost in costs:
                fold_trades: dict[int, list[float]] = {}
                symbol_trades: dict[str, list[float]] = {s: [] for s in symbols}
                reversed_fold: dict[int, list[float]] = {}
                for symbol, d in per_symbol.items():
                    if d.empty:
                        continue
                    next_allowed = pd.Timestamp.min.tz_localize("UTC")
                    for ts, row in d.iterrows():
                        if ts < next_allowed:
                            continue
                        side = 1.0 if row["score"] > 0 else -1.0
                        gross = side * float(row["fwd"]) * 10000.0
                        fold = int(row["fold"])
                        net = gross - cost
                        fold_trades.setdefault(fold, []).append(net)
                        reversed_fold.setdefault(fold, []).append(-gross - cost)
                        symbol_trades[symbol].append(net)
                        pos = frames[symbol].index.searchsorted(ts)
                        exit_pos = min(pos + hold, len(frames[symbol].index) - 1)
                        next_allowed = frames[symbol].index[exit_pos]
                fold_exps = [float(np.mean(v)) for v in fold_trades.values() if v]
                fold_pfs = [pf(v) for v in fold_trades.values() if v]
                rev_exps = [float(np.mean(v)) for v in reversed_fold.values() if v]
                symbol_exps = [float(np.mean(v)) for v in symbol_trades.values() if v]
                total = sum(len(v) for v in fold_trades.values())
                row = {
                    "family": family, "interval": interval, "params": params, "cost_bps": cost,
                    "folds": len(fold_exps), "total_trades": total,
                    "median_fold_net_expectancy_bps": median_finite(fold_exps),
                    "median_fold_profit_factor": median_finite(fold_pfs),
                    "positive_fold_fraction": float(np.mean([x > 0 for x in fold_exps])) if fold_exps else 0.0,
                    "positive_symbol_fraction": float(np.mean([x > 0 for x in symbol_exps])) if symbol_exps else 0.0,
                    "reversed_median_net_expectancy_bps": median_finite(rev_exps),
                }
                row["original_beats_reversed"] = row["median_fold_net_expectancy_bps"] > row["reversed_median_net_expectancy_bps"]
                row["economic_pass"] = bool(
                    cost == primary_cost
                    and total >= int(config["dependence_and_trials"]["minimum_total_trades"])
                    and len(fold_exps) >= int(config["dependence_and_trials"]["minimum_folds"])
                    and row["median_fold_net_expectancy_bps"] > 0
                    and row["median_fold_profit_factor"] > 1
                    and row["positive_fold_fraction"] >= float(config["screening_gate"]["minimum_positive_fold_fraction"])
                    and row["positive_symbol_fraction"] >= float(config["screening_gate"]["minimum_positive_symbol_fraction"])
                    and row["original_beats_reversed"]
                )
                translations.append(row)

    primary = [r for r in translations if float(r["cost_bps"]) == primary_cost]
    primary.sort(key=lambda r: (r["economic_pass"], r["median_fold_net_expectancy_bps"]), reverse=True)
    state_sorted = sorted(state_trials, key=lambda r: (r["state_pass"], r["median_fold_spearman"]), reverse=True)
    return {
        "schema_version": 1, "protocol_name": config["protocol_name"], "interval": interval,
        "symbols": symbols, "state_trial_count": len(state_trials), "state_pass_count": sum(x["state_pass"] for x in state_trials),
        "translation_count": len(translations), "economic_pass_count_primary": sum(x["economic_pass"] for x in primary),
        "top_state": state_sorted[:30], "primary_cost_leaderboard": primary[:60],
        "all_state_trials": state_trials, "all_translations": translations,
        "claims": {"development_screening_only": True, "profitable_edge_established": False, "verified_oos": False, "live_enabled": False}
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--interval", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.interval not in config["data"]["intervals"]:
        raise SystemExit("interval not frozen")
    result = run(config, Path(args.data_dir), args.interval)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({
        "protocol": result["protocol_name"], "interval": result["interval"], "state_trials": result["state_trial_count"],
        "state_pass": result["state_pass_count"], "translations": result["translation_count"],
        "economic_pass_primary": result["economic_pass_count_primary"], "top_state": result["top_state"][:5],
        "top_primary": result["primary_cost_leaderboard"][:5]
    }, indent=2))


if __name__ == "__main__":
    main()

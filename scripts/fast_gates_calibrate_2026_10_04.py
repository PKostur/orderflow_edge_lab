"""Calibrate the fast-gates-v1 thresholds (config/fast_gates_v1.json) from data before 2026-10-05 only.

G1: pre-start paper replay (2026-04-05 to now) vs the theoretical V_ALL book, current MEXC contract specs.
G2: stationary block bootstrap of the development S4 series rescaled to the holdout Sharpe.
Usage: python scripts/fast_gates_calibrate_2026_10_04.py artifacts/fast_gates/calibration.json
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights, simulate
from orderflow_edge_lab.paper_account import fetch_specs, replay
from orderflow_edge_lab.trend_portfolio_forward import completed_bars

GATES = json.load(open("config/fast_gates_v1.json", encoding="utf-8"))
BCFG = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
PCFG = json.load(open("config/paper_account_blend_v1.json", encoding="utf-8"))
FORWARD_START = pd.Timestamp(GATES["prospective_start_utc"])
REPLAY_START = pd.Timestamp("2026-04-05", tz="UTC")
WARM = "2025-07-01T00:00:00Z"
CACHE = os.path.join(os.environ["TEMP"], "fast_gates_mexc_recent.pkl")


def g2(seed: int = 20261004, paths: int = 20000, horizon: int = 180, block: float = 20.0, target_sharpe: float = 1.39) -> dict:
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
    legs = leg_returns(BCFG, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs, vol_window=int(BCFG["blend"]["vol_window_days"]), min_obs=int(BCFG["blend"]["min_obs"]))
    s4 = s4[s4.index < pd.Timestamp("2026-09-12", tz="UTC")].to_numpy()
    sd = s4.std(ddof=1)
    x = s4 - s4.mean() + target_sharpe * sd / np.sqrt(365.0)
    rng = np.random.default_rng(seed)
    n = len(x)
    idx = np.empty((paths, horizon), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, paths)
    new_block = rng.random((paths, horizon)) < 1.0 / block
    jumps = rng.integers(0, n, (paths, horizon))
    for t in range(1, horizon):
        idx[:, t] = np.where(new_block[:, t], jumps[:, t], (idx[:, t - 1] + 1) % n)
    r = x[idx]
    eq = np.cumprod(1.0 + r, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((paths, 1)), eq], axis=1), axis=1)[:, 1:]
    mdd = (eq / peak - 1.0).min(axis=1)
    logeq = np.concatenate([np.zeros((paths, 1)), np.log(eq)], axis=1)
    roll60 = np.exp(logeq[:, 60:] - logeq[:, :-60]) - 1.0  # windows ending day 60..180
    min60 = roll60.min(axis=1)
    return {"dev_days": int(n), "dev_daily_sd": float(sd), "dev_sharpe_raw": float(s4.mean() / sd * np.sqrt(365)),
            "target_sharpe": target_sharpe, "paths": paths, "horizon_days": horizon, "mean_block_days": block, "seed": seed,
            "max_drawdown_p025": float(np.quantile(mdd, 0.025)), "max_drawdown_p50": float(np.quantile(mdd, 0.5)),
            "min_rolling_60d_p025": float(np.quantile(min60, 0.025)), "min_rolling_60d_p50": float(np.quantile(min60, 0.5)),
            "either_rule_false_alarm": float(np.mean((mdd < np.quantile(mdd, 0.025)) | (min60 < np.quantile(min60, 0.025))))}


def g1() -> dict:
    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
    as_of = pd.Timestamp.now(tz="UTC")
    if as_of >= FORWARD_START:
        raise SystemExit("calibration must run before the gate start")
    if os.path.exists(CACHE):
        frames, funding, specs = pickle.load(open(CACHE, "rb"))
    else:
        def load(s):
            try:
                return (s, fetch_mexc_futures_klines(s, "8h", WARM, as_of.isoformat()),
                        fetch_mexc_funding_history(s, WARM, as_of.isoformat())["funding_rate"])
            except Exception:
                return s, None, None
        with ThreadPoolExecutor(4) as ex:
            got = list(ex.map(load, BCFG["symbols"]))
        frames = {s: f for s, f, _ in got if f is not None}
        funding = {s: fu for s, f, fu in got if f is not None}
        specs = {s: v for s, v in fetch_specs().items() if s in frames}
        pickle.dump((frames, funding, specs), open(CACHE, "wb"))
    clean = {s: completed_bars(f, as_of) for s, f in frames.items()}
    clean = {s: f for s, f in clean.items() if len(f) >= 250}
    legs = leg_returns(BCFG, clean, funding)
    b = BCFG["blend"]
    lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    agg = coin_targets(BCFG, clean, funding, lw)
    open8 = pd.DataFrame({s: f["open"].astype(float) for s, f in clean.items()}).sort_index()
    led = replay(agg, open8, funding, specs, start=REPLAY_START, initial=float(PCFG["account"]["initial_equity"]))
    eq = pd.Series({pd.Timestamp(c["date"]).floor("D"): c["equity"] for c in led["curve"]}, dtype=float)
    paper = eq.pct_change().dropna()
    v_all, _ = simulate(agg, clean, funding, None, float(BCFG["economics"]["round_trip_cost_bps"]))
    common = paper.index.intersection(v_all.index)
    diff = (paper.loc[common] - v_all.loc[common]).dropna()
    out = {"replay_start": REPLAY_START.isoformat(), "as_of": as_of.isoformat(), "coins": len(clean), "days": int(len(diff)),
           "paper_vs_v_all_correlation": float(paper.loc[common].corr(v_all.loc[common])),
           "mean_daily_diff": float(diff.mean()), "te_annualized": float(diff.std(ddof=1) * np.sqrt(365.0)),
           "paper_total_return": float((1 + paper.loc[common]).prod() - 1), "v_all_total_return": float((1 + v_all.loc[common]).prod() - 1),
           "fees_total": led["totals"]["fees"], "funding_total": led["totals"]["funding"]}
    for n in GATES["gates"]["G1_implementation"]["checkpoints_days"]:
        out[f"sd_rolling_{n}d_sum"] = float(diff.rolling(n).sum().dropna().std(ddof=1))
    return out


def main(out_path: str) -> int:
    res = {"G1_implementation": g1(), "G2_breakage_alarm": g2()}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps(res, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "artifacts/fast_gates/calibration.json"))

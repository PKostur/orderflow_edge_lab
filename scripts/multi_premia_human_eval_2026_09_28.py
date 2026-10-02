"""Evaluate multi-premia-human-v1 (config/multi_premia_human_v1.json). Descriptive.

Reuses the cached multi-premia-v1 data (same coins, window, funding proxy).
"""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy
from orderflow_edge_lab.xs_premia import (
    carry_score, daily_funding_panel, daily_open_panel, momentum_score, quantile_weights, run_xs,
)

cfg = json.load(open("config/multi_premia_human_v1.json", encoding="utf-8"))
frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
COST = 20.0
LAG = pd.Timedelta(hours=8)

# --- legs exactly as multi-premia-v1 (books for the blend weights) ---
strat = vol_sized_strategy(core_strategy({"DON8": {"lookback": 55}, "EMA8": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}, exit_window=None),
                           window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)
cols, targets = {}, {}
for s, f in frames.items():
    r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=COST), return_equity=True, funding=fund[s])
    cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
    targets[s] = strat.generate_target(f, {}, None)
s1 = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
s1 = s1[s1.index >= s1[s1 != 0].index[0]]
opens = daily_open_panel(frames)
fp = daily_funding_panel(fund, opens.index)
mom, car = momentum_score(opens, 30), carry_score(fp, 7)
s2 = run_xs(opens, fp, mom, rebalance_days=7, q=0.25, cost_bps=COST)["returns"]
s3 = run_xs(opens, fp, car, rebalance_days=7, q=0.25, cost_bps=COST)["returns"]
s2.index, s3.index = s2.index + pd.Timedelta(days=1), s3.index + pd.Timedelta(days=1)
books = pd.concat([s1.rename("S1"), s2.rename("S2"), s3.rename("S3")], axis=1).dropna()
books = books[(books != 0).all(axis=1).cumsum() > 0]
vol = books.rolling(90, min_periods=60).std().shift(1)
inv = (1.0 / vol).where(np.isfinite(1.0 / vol))
lw = inv.div(inv.sum(axis=1), axis=0)
lw.loc[lw.index.dayofweek != 0] = np.nan
lw = lw.ffill().dropna()

# --- per-coin leg weights, decided at 00:00 UTC of day d ---
days = lw.index
syms = list(opens.columns)
# S1: last completed 8h target (bar 16:00 of d-1), equal capital across coins with data
tpanel = pd.DataFrame({s: t for s, t in targets.items()}).sort_index()
t_at = tpanel.reindex(days - LAG)
t_at.index = days
has = opens.reindex(days).notna()
w1 = t_at.where(has).fillna(0.0).div(has.sum(axis=1).clip(lower=1), axis=0)


def xs_weights(score: pd.DataFrame) -> pd.DataFrame:
    """Frozen quantile weights at run_xs rebalance days, held (undrifted) between rebalances."""
    ret = opens.shift(-1) / opens - 1.0
    out, w = {}, pd.Series(0.0, index=syms)
    for i, d in enumerate(opens.index[:-1]):
        if i % 7 == 0:
            sc = score.loc[d].where(opens.loc[d].notna() & ret.loc[d].notna())
            w = quantile_weights(sc, 0.25) if sc.notna().sum() >= 8 else pd.Series(0.0, index=syms)
        out[d] = w
    return pd.DataFrame(out).T.reindex(days).fillna(0.0)


w2, w3 = xs_weights(mom), xs_weights(car)
agg = w1.mul(lw["S1"], axis=0) + w2.mul(lw["S2"], axis=0) + w3.mul(lw["S3"], axis=0)

# --- execution at the 08:00 UTC open, held to the next 08:00 UTC open ---
o8 = pd.DataFrame({s: f["open"].astype(float) for s, f in frames.items()}).sort_index()
px = o8.reindex(days + LAG)
px.index = days
ret = (px.shift(-1) / px - 1.0)
fset = {}
for s, f in fund.items():
    if f is None or len(f) == 0:
        fset[s] = pd.Series(0.0, index=days)
        continue
    # settlements in (d+8h, d+1+8h]
    day = (f.index - LAG - pd.Timedelta(microseconds=1)).floor("D")
    fset[s] = f.groupby(day).sum().reindex(days).fillna(0.0)
fpan = pd.DataFrame(fset).reindex(columns=syms).fillna(0.0)


def truncate(a: pd.Series, k: int | None) -> pd.Series:
    if k is None:
        return a
    g = float(a.abs().sum())
    keep = a.abs().nlargest(k).index
    out = pd.Series(0.0, index=a.index)
    out[keep] = a[keep]
    gk = float(out.abs().sum())
    return out * (min(g, 1.0) / gk) if gk > 0 else out


def simulate(k: int | None) -> tuple[pd.Series, float]:
    held = pd.Series(0.0, index=syms)
    rows, turns = {}, []
    for d in days[:-1]:
        r = ret.loc[d]
        tradable = r.notna()
        target = truncate(agg.loc[d].where(tradable, 0.0), k)
        turn = float((target - held).abs().sum())
        turns.append(turn)
        rr = r.fillna(0.0)
        rows[d + pd.Timedelta(days=1)] = float((target * rr).sum() - (target * fpan.loc[d]).sum() - turn * COST / 2 / 1e4)
        held = target * (1.0 + rr)
    return pd.Series(rows), float(np.mean(turns))


halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in cfg["halves"]]
res = {}
for name, k in (("V_ALL", None), ("H10", 10), ("H5", 5), ("H3", 3)):
    x, turn = simulate(k)
    s = summarize(x, nw_lags=5)
    res[name] = {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365),
                 "max_drawdown": s["max_drawdown"], "days": s["days"], "mean_daily_turnover": turn,
                 "halves": [summarize(x[(x.index >= a) & (x.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves],
                 "per_year": {str(y): float((1 + v).prod() - 1) for y, v in x.groupby(x.index.year)}}
h, v = res["H5"], res["V_ALL"]
res["H5"]["passes"] = bool(h["t"] >= 2 and h["sharpe"] >= 0.5 * v["sharpe"] and min(h["halves"]) > 0)
res["mean_full_gross"] = float(agg.abs().sum(axis=1).mean())
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/multi_premia_human_eval.json", "w"), indent=1, default=float)
for k in ("V_ALL", "H10", "H5", "H3"):
    r = res[k]
    print(f"{k} Sharpe {r['sharpe']:.2f} t {r['t']:.2f} ret {r['annual_return']:.3f} DD {r['max_drawdown']:.3f} "
          f"halves {[round(x, 2) for x in r['halves']]} turn {r['mean_daily_turnover']:.3f} pass {r.get('passes')}")
print("gross", round(res["mean_full_gross"], 3))

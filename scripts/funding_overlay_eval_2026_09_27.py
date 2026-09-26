"""Evaluate the declared funding crowding overlay. Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.funding_overlay import funding_overlay_strategy
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

cfg = json.load(open("config/funding_crowding_overlay_v1.json", encoding="utf-8"))
tp = json.load(open("config/trend_channel_exit_v1.json", encoding="utf-8"))["trend_parameters"]
syms = json.load(open("config/crypto_trend_core_v1.json", encoding="utf-8"))["groups"]["crypto"]
F = pickle.load(open(os.environ["TEMP"] + "/binance_funding.pkl", "rb"))
start, end = cfg["window"]


def get(s):
    try:
        return s, fetch_mexc_futures_klines(s, "8h", start, end)
    except Exception:
        return s, None


with ThreadPoolExecutor(4) as ex:
    frames = {s: f for s, f in ex.map(get, syms) if f is not None and s in F}
core = core_strategy(tp, exit_window=None)
thr = float(cfg["overlay"]["threshold_per_8h"])
basket = pd.DataFrame({s: _daily(f["open"]) for s, f in frames.items()}).pct_change().mean(axis=1).dropna()
mret = (1 + basket).resample("ME").prod() - 1
mdir = pd.qcut(mret, 3, labels=["DOWN", "FLAT", "UP"])
res = {}
for name in ("core", "core_funding_overlay"):
    cols, inmkt, fpaid = {}, [], []
    for s, f in frames.items():
        base = core if name == "core" else funding_overlay_strategy(core, F[s], threshold=thr)
        strat = vol_sized_strategy(base, window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)
        r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=20.0), return_equity=True, funding=F[s])
        cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
        inmkt.append(r["exposure_fraction"])
        fpaid.append(sum(t.get("funding_bps", 0.0) for t in r["trades_ledger"]))
    d = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
    d = d[d.index >= d[d != 0].index[0]]
    s = summarize(d, nw_lags=5)
    m = ((1 + d).resample("ME").prod() - 1).reindex(mret.index)
    res[name] = {**{k: s[k] for k in ("annualized_sharpe", "newey_west_t", "mean_daily_bps", "max_drawdown", "days")},
                 "annual_return": float(d.mean() * 365),
                 "per_year": {str(y): float((1 + v).prod() - 1) for y, v in d.groupby(d.index.year)},
                 "monthly_by_basket_regime": {str(g): float(v.mean()) for g, v in m.groupby(mdir, observed=True)},
                 "time_in_market": float(np.mean(inmkt)), "sum_trade_funding_bps": float(np.sum(fpaid))}
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/funding_overlay_eval.json", "w"), indent=1, default=float)
for k, v in res.items():
    mm = v["monthly_by_basket_regime"]
    print(f"{k:22s} Sharpe {v['annualized_sharpe']:.2f} t {v['newey_west_t']:.2f} ret {v['annual_return']:.3f} DD {v['max_drawdown']:.3f} "
          f"| down {mm['DOWN']*100:.2f} flat {mm['FLAT']*100:.2f} up {mm['UP']*100:.2f} | inMkt {v['time_in_market']:.2f} funding_bps {v['sum_trade_funding_bps']:.0f}")
    print("   ", {y: round(x, 3) for y, x in v["per_year"].items()})

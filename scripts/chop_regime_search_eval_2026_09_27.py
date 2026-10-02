"""Evaluate the declared chop-regime candidates (config/chop_regime_search_v1.json). Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.chop_candidates import TEXTBOOK, cross_sectional_reversal, family_target, funding_carry
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.regime_switch import component_targets, regime_labels
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel, FunctionStrategy
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

cfg = json.load(open("config/chop_regime_search_v1.json", encoding="utf-8"))
rs = json.load(open("config/regime_switch_v1.json", encoding="utf-8"))
syms = json.load(open(cfg["universe"]["symbols_from"], encoding="utf-8"))["groups"]["crypto"]
F = pickle.load(open(os.environ["TEMP"] + "/binance_funding.pkl", "rb"))
start, end = cfg["universe"]["window"]


def get(s):
    try:
        return s, fetch_mexc_futures_klines(s, "8h", start, end)
    except Exception:
        return s, None


with ThreadPoolExecutor(4) as ex:
    frames = {s: f for s, f in ex.map(get, syms) if f is not None and s in F}
tp = rs["universes"]["crypto"]["trend_parameters"]
mr = rs["components"]["mean_reversion"]["parameters"]
labels = {s: regime_labels(f, rs["regime"]) for s, f in frames.items()}
trend = {s: component_targets(f, tp, mr)[0] for s, f in frames.items()}
chop = {s: (labels[s] == "CHOP") for s in frames}
cands = {n: {s: family_target(f, n) for s, f in frames.items()} for n in TEXTBOOK}
cands["C5_xs_reversal"] = cross_sectional_reversal(frames, chop)
cands["C6_funding_carry"] = {s: funding_carry(f, F[s]) for s, f in frames.items()}
books = {"trend_only": None, "chop_flat": "FLAT", **{n: n for n in cands}}


def book_target(s, which):
    lab = labels[s]
    known = lab != "UNKNOWN"
    t = trend[s]
    if which is None:
        return t.where(known, 0.0)
    inner = 0.0 if which == "FLAT" else cands[which][s]
    return t.where(~chop[s], inner).where(known, 0.0)


halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in cfg["halves"]]
res = {}
for name, which in books.items():
    cols, chop_only = {}, []
    for s, f in frames.items():
        tgt = book_target(s, which)
        strat = vol_sized_strategy(FunctionStrategy(strategy_id=name, target_fn=lambda fr, p, t=tgt: t.reindex(fr.index).fillna(0.0), warmup_bars=100),
                                   window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)
        r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=20.0), return_equity=True, funding=F[s])
        d = _daily(r["equity_path"].iloc[:-1]).pct_change()
        cols[s] = d
        c = _daily(chop[s].astype(float)).shift(1).reindex(d.index)
        chop_only.append(d[c == 1.0])
    d = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
    d = d[d.index >= d[d != 0].index[0]]
    full = summarize(d, nw_lags=5)
    hs = [summarize(d[(d.index >= a) & (d.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves]
    co = pd.concat(chop_only)
    res[name] = {"sharpe_full": full["annualized_sharpe"], "t_full": full["newey_west_t"], "max_drawdown": full["max_drawdown"],
                 "annual_return": float(d.mean() * 365), "sharpe_half1": hs[0], "sharpe_half2": hs[1],
                 "chop_sleeve_day_mean_bps": float(co.mean() * 1e4), "chop_sleeve_days": int(len(co))}
base = res["trend_only"]
for n, v in res.items():
    v["passes"] = bool(n not in ("trend_only",) and v["sharpe_half1"] > base["sharpe_half1"] and v["sharpe_half2"] > base["sharpe_half2"])
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/chop_search_eval.json", "w"), indent=1, default=float)
print(f"{'book':22s} full   t    H1    H2   ret    DD   chop-day-bp  pass")
for n, v in res.items():
    print(f"{n:22s} {v['sharpe_full']:5.2f} {v['t_full']:5.2f} {v['sharpe_half1']:5.2f} {v['sharpe_half2']:5.2f} {v['annual_return']:6.3f} {v['max_drawdown']:6.3f} {v['chop_sleeve_day_mean_bps']:8.2f}   {v['passes']}")

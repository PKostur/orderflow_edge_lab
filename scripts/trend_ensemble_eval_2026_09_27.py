"""Evaluate trend-horizon-ensemble-v1 vs the core. Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys
import urllib.request

import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.strategy_tournament import generate_target_position
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel, FunctionStrategy
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

cfg = json.load(open("config/trend_ensemble_v1.json", encoding="utf-8"))
sets = {"core17": json.load(open("config/crypto_trend_core_v1.json"))["groups"]["crypto"],
        "untouched53": json.load(open("config/untouched_coins_holdout_v2.json"))["source"]["symbols"]}
ALIAS = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}


def ens_target(frame, _p):
    parts = [generate_target_position(frame, fam, dict(p)).reindex(frame.index).fillna(0.0)
             for fam, plist in cfg["signals"].items() for p in plist]
    return sum(parts) / len(parts)


ensemble = FunctionStrategy(strategy_id="ensemble", target_fn=ens_target, warmup_bars=100)
core = core_strategy({"DON8": {"lookback": 55}, "EMA8": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}, exit_window=None)


def funding(sym):
    base = ALIAS.get(sym.replace("_USDT", ""), sym.replace("_USDT", ""))
    for cand in (f"{base}USDT", f"1000{base}USDT"):
        s0, e0, rows = int(pd.Timestamp("2020-06-01", tz="UTC").timestamp() * 1000), int(pd.Timestamp("2026-09-12", tz="UTC").timestamp() * 1000), []
        try:
            while s0 < e0:
                with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={cand}&startTime={s0}&endTime={e0}&limit=1000", timeout=30) as r:
                    d = json.load(r)
                if not d:
                    break
                rows += d
                s0 = int(d[-1]["fundingTime"]) + 1
                if len(d) < 1000:
                    break
        except Exception:
            rows = []
        if rows:
            return pd.Series({pd.Timestamp(int(x["fundingTime"]), unit="ms", tz="UTC"): float(x["fundingRate"]) for x in rows}).sort_index()
    return pd.Series(dtype=float)


def load(s):
    try:
        return s, fetch_mexc_futures_klines(s, "8h", "2020-06-01T00:00:00Z", "2026-09-12T00:00:00Z"), funding(s)
    except Exception:
        return s, None, None


halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in cfg["halves"]]
res = {}
for set_name, syms in sets.items():
    with ThreadPoolExecutor(4) as ex:
        data = {s: (f, fu) for s, f, fu in ex.map(load, syms) if f is not None and len(f) > 400}
    for name, base in (("core", core), ("ensemble", ensemble)):
        strat = vol_sized_strategy(base, window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)
        cols = {}
        for s, (f, fu) in data.items():
            r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=20.0), return_equity=True, funding=fu)
            cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
        d = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
        d = d[d.index >= d[d != 0].index[0]]
        full = summarize(d, nw_lags=5)
        res[f"{set_name}:{name}"] = {"sharpe": full["annualized_sharpe"], "t": full["newey_west_t"], "max_drawdown": full["max_drawdown"],
                                     "annual_return": float(d.mean() * 365),
                                     "halves": [summarize(d[(d.index >= a) & (d.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves]}
adopt = all(res[f"{k}:ensemble"]["sharpe"] >= res[f"{k}:core"]["sharpe"] and
            all(e >= c for e, c in zip(res[f"{k}:ensemble"]["halves"], res[f"{k}:core"]["halves"])) for k in sets)
res["adopt"] = adopt
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/trend_ensemble_eval.json", "w"), indent=1, default=float)
for k, v in res.items():
    if k != "adopt":
        print(f"{k:22s} Sharpe {v['sharpe']:.2f} t {v['t']:.2f} ret {v['annual_return']:.3f} DD {v['max_drawdown']:.3f} halves {[round(x, 2) for x in v['halves']]}")
print("adopt", adopt)

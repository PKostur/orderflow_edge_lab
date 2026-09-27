"""Evaluate multi-premia-v1 (config/multi_premia_v1.json). Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys
import urllib.request

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy
from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score, run_xs

cfg = json.load(open("config/multi_premia_v1.json", encoding="utf-8"))
syms = (json.load(open("config/crypto_trend_core_v1.json"))["groups"]["crypto"]
        + json.load(open("config/untouched_coins_holdout_v2.json"))["source"]["symbols"])
ALIAS = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}
START, END = cfg["window"]
CACHE = os.path.join(os.environ["TEMP"], "multi_premia_data.pkl")


def funding(sym):
    base = ALIAS.get(sym.replace("_USDT", ""), sym.replace("_USDT", ""))
    for cand in (f"{base}USDT", f"1000{base}USDT"):
        s0, e0, rows = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000), int(pd.Timestamp(END, tz="UTC").timestamp() * 1000), []
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
        return s, fetch_mexc_futures_klines(s, "8h", f"{START}T00:00:00Z", f"{END}T00:00:00Z"), funding(s)
    except Exception:
        return s, None, None


if os.path.exists(CACHE):
    frames, fund = pickle.load(open(CACHE, "rb"))
else:
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, syms))
    frames = {s: f for s, f, _ in got if f is not None and len(f) > 400}
    fund = {s: fu for s, f, fu in got if s in frames}
    pickle.dump((frames, fund), open(CACHE, "wb"))

# S1 trend core
strat = vol_sized_strategy(core_strategy({"DON8": {"lookback": 55}, "EMA8": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}, exit_window=None),
                           window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)
cols = {}
for s, f in frames.items():
    r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=20.0), return_equity=True, funding=fund[s])
    cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
s1 = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
s1 = s1[s1.index >= s1[s1 != 0].index[0]]
# S2, S3 cross-sectional (returns stamped at d cover open d -> open d+1; shift to canonical d+1 stamp)
opens = daily_open_panel(frames)
fp = daily_funding_panel(fund, opens.index)
s2 = run_xs(opens, fp, momentum_score(opens, 30), rebalance_days=7, q=0.25, cost_bps=20)["returns"]
s3 = run_xs(opens, fp, carry_score(fp, 7), rebalance_days=7, q=0.25, cost_bps=20)["returns"]
s2.index = s2.index + pd.Timedelta(days=1)
s3.index = s3.index + pd.Timedelta(days=1)
books = pd.concat([s1.rename("S1"), s2.rename("S2"), s3.rename("S3")], axis=1).dropna()
books = books[(books != 0).all(axis=1).cumsum() > 0]
# S4 equal-risk blend, weekly, trailing 90-day vol from prior days only
vol = books.rolling(90, min_periods=60).std().shift(1)
inv = (1.0 / vol).where(np.isfinite(1.0 / vol))
w = inv.div(inv.sum(axis=1), axis=0)
w = w.where(w.index.dayofweek == 0).ffill()
s4 = (w * books).sum(axis=1).where(w.notna().all(axis=1)).dropna()
books = books.loc[s4.index]
books["S4"] = s4
halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in cfg["halves"]]
res = {"coins": len(frames), "correlations": books.corr().round(3).to_dict()}
for k in books:
    x = books[k]
    s = summarize(x, nw_lags=5)
    res[k] = {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365),
              "max_drawdown": s["max_drawdown"], "days": s["days"],
              "halves": [summarize(x[(x.index >= a) & (x.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves],
              "per_year": {str(y): float((1 + v).prod() - 1) for y, v in x.groupby(x.index.year)}}
for k in ("S2", "S3"):
    v = res[k]
    res[k]["passes"] = bool(v["annual_return"] > 0 and v["t"] >= 2 and min(v["halves"]) > 0)
res["S4"]["passes"] = bool(all(a > b for a, b in zip(res["S4"]["halves"], res["S1"]["halves"])))
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/multi_premia_eval.json", "w"), indent=1, default=float)
for k in ("S1", "S2", "S3", "S4"):
    v = res[k]
    print(f"{k} Sharpe {v['sharpe']:.2f} t {v['t']:.2f} ret {v['annual_return']:.3f} DD {v['max_drawdown']:.3f} halves {[round(h, 2) for h in v['halves']]} pass {v.get('passes')}")
print("corr", {k: {kk: vv for kk, vv in d.items() if kk != k} for k, d in res["correlations"].items()})

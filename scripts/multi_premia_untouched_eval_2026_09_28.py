"""Run multi-premia-untouched-holdout-v1 exactly once (config/multi_premia_untouched_holdout_v1.json). Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys
import urllib.request

import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights, simulate
from orderflow_edge_lab.trend_portfolio_forward import summarize

cfg = json.load(open("config/multi_premia_untouched_holdout_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
START, END = cfg["window"]
CACHE = os.path.join(os.environ["TEMP"], "multi_premia_untouched_data.pkl")


def funding(sym):
    base = sym.replace("_USDT", "")
    for cand in (f"{base}USDT", f"1000{base}USDT", f"{base.removeprefix('1000')}USDT"):
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
        got = list(ex.map(load, cfg["symbols"]))
    frames = {s: f for s, f, _ in got if f is not None and len(f) > 400}
    fund = {s: fu for s, f, fu in got if s in frames}
    pickle.dump((frames, fund), open(CACHE, "wb"))

legs = leg_returns(rules, frames, fund)
legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
b = rules["blend"]
legs["S4"] = blend(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
h5, _ = simulate(coin_targets(rules, frames, fund, lw), frames, fund, 5, 20.0)
books = legs.dropna().copy()
books["H5"] = h5.reindex(books.index)
halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(e, tz="UTC")) for a, e in cfg["halves"]]
res = {"coins": len(frames), "missing": sorted(set(cfg["symbols"]) - set(frames)),
       "funding_coverage": sum(1 for s in frames if len(fund[s]) > 0), "correlations": books.corr().round(3).to_dict()}
for k in books:
    x = books[k].dropna()
    s = summarize(x, nw_lags=5)
    res[k] = {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365),
              "max_drawdown": s["max_drawdown"], "days": s["days"],
              "halves": [summarize(x[(x.index >= a) & (x.index < e)], nw_lags=5)["annualized_sharpe"] for a, e in halves],
              "per_year": {str(y): float((1 + v).prod() - 1) for y, v in x.groupby(x.index.year)}}
p = res["S4"]
res["primary_passes"] = bool(p["annual_return"] > 0 and p["t"] >= 2 and min(p["halves"]) > 0)
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
print("coins", res["coins"], "funding", res["funding_coverage"], "missing", res["missing"])
for k in ("S1", "S2", "S3", "S4", "H5"):
    v = res[k]
    print(f"{k} Sharpe {v['sharpe']:.2f} t {v['t']:.2f} ret {v['annual_return']:.3f} DD {v['max_drawdown']:.3f} "
          f"halves {[round(h, 2) for h in v['halves']]} years {({y: round(r * 100) for y, r in v['per_year'].items()})}")
print("PRIMARY PASS", res["primary_passes"])

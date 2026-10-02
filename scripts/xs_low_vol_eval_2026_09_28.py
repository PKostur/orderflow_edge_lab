"""Evaluate xs-low-vol-v1 (config/xs_low_vol_v1.json) on development then confirmation samples. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.trend_portfolio_forward import summarize
from orderflow_edge_lab.xs_premia import daily_funding_panel, daily_open_panel

cfg = json.load(open("config/xs_low_vol_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
sig = cfg["signal"]
COST = float(cfg["economics"]["round_trip_cost_bps"])
halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in cfg["halves"]]


def low_vol_book(opens: pd.DataFrame, fund: pd.DataFrame) -> pd.Series:
    ret = opens.shift(-1) / opens - 1.0
    vol = (opens / opens.shift(1) - 1.0).rolling(60, min_periods=60).std()  # uses opens up to d: returns strictly before d
    w = pd.Series(0.0, index=opens.columns)
    rows = {}
    for i, d in enumerate(opens.index[:-1]):
        turn = 0.0
        if i % int(sig["rebalance_days"]) == 0:
            v = vol.loc[d].where(opens.loc[d].notna() & ret.loc[d].notna()).dropna()
            new = pd.Series(0.0, index=opens.columns)
            n = int(np.floor(len(v) * float(sig["quantile"])))
            if len(v) >= int(sig["min_names"]) and n >= 1:
                order = v.sort_values()
                lo, hi = order.index[:n], order.index[-n:]
                # each side at unit ex-ante vol, then normalise book to 1.0x gross
                new[lo] = 1.0 / n / float(v[lo].mean())
                new[hi] = -1.0 / n / float(v[hi].mean())
                new = new / new.abs().sum()
            turn = float((new - w).abs().sum())
            w = new
        r = ret.loc[d].fillna(0.0)
        rows[d + pd.Timedelta(days=1)] = float((w * r).sum() - (w * fund.loc[d]).sum() - turn * COST / 2 / 1e4)
        w = w * (1.0 + r)
    return pd.Series(rows)


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    s = summarize(x, nw_lags=5)
    return {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365),
            "max_drawdown": s["max_drawdown"], "days": s["days"],
            "halves": [summarize(x[(x.index >= a) & (x.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves],
            "per_year": {str(y): float((1 + v).prod() - 1) for y, v in x.groupby(x.index.year)}}


def evaluate(cache: str) -> dict:
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    legs = leg_returns(rules, frames, fund)
    opens = daily_open_panel(frames)
    s5 = low_vol_book(opens, daily_funding_panel(fund, opens.index))
    legs["S5"] = s5.reindex(legs.index)
    legs = legs.dropna()
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    b = rules["blend"]
    b3 = blend(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    b4 = blend(legs[["S1", "S2", "S3", "S5"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    idx = b3.index.intersection(b4.index)
    out = {"coins": len(frames), "S5": stats(legs["S5"]), "blend3": stats(b3.loc[idx]), "blend4": stats(b4.loc[idx]),
           "corr_S5": legs.corr()["S5"].round(3).to_dict()}
    return out


res = {"development": evaluate("multi_premia_data.pkl")}
d = res["development"]
res["confirmation"] = evaluate("multi_premia_untouched_data.pkl")
c = res["confirmation"]
res["standalone_passes"] = bool(d["S5"]["annual_return"] > 0 and d["S5"]["t"] >= 2 and min(d["S5"]["halves"]) > 0
                                and c["S5"]["annual_return"] > 0 and c["S5"]["t"] >= 1.5 and min(c["S5"]["halves"]) > 0)
res["blend_addition_passes"] = bool(d["blend4"]["sharpe"] > d["blend3"]["sharpe"] and c["blend4"]["sharpe"] > c["blend3"]["sharpe"])
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
for name in ("development", "confirmation"):
    r = res[name]
    print(name, "coins", r["coins"], "corr", r["corr_S5"])
    for k in ("S5", "blend3", "blend4"):
        v = r[k]
        print(f"  {k} Sharpe {v['sharpe']:.2f} t {v['t']:.2f} ret {v['annual_return']:.3f} DD {v['max_drawdown']:.3f} "
              f"halves {[round(h, 2) for h in v['halves']]}")
print("standalone", res["standalone_passes"], "blend_addition", res["blend_addition_passes"])

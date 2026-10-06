"""Evaluate prop-firm-v2 (config/prop_firm_v2.json) once. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights, simulate
from orderflow_edge_lab.prop_sim import evaluate_survival

v1 = json.load(open("config/prop_firm_v1.json", encoding="utf-8"))
cfg = json.load(open("config/prop_firm_v2.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
END = pd.Timestamp("2026-09-12", tz="UTC")
B = rules["blend"]
SIZE = {"HyroTrader": None, "Breakout": 30, "FTMO": 10}


def liquidity_rank(frames):
    dv = {s: float((f["volume"] * f["close"]).groupby(f.index.floor("D")).sum().median()) for s, f in frames.items()}
    return sorted(dv, key=dv.get, reverse=True)


def books(frames, fund):
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs[["S1", "S2", "S3"]], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))
    lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))
    agg = coin_targets(rules, frames, fund, lw)
    h10, _ = simulate(agg, frames, fund, 10, 20.0)
    h5, _ = simulate(agg, frames, fund, 5, 20.0)
    out = pd.concat([s4.rename("S4_blend"), h10.rename("H10_human"), h5.rename("H5_human")], axis=1).dropna()
    return out[out.index < END]


res = {}
for sample, cache in (("development", "multi_premia_data.pkl"), ("confirmation", "multi_premia_untouched_data.pkl")):
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    ranked = liquidity_rank(frames)
    res[sample] = {}
    for firm, n in SIZE.items():
        uni = ranked if n is None else ranked[:n]
        sub = {s: frames[s] for s in uni}
        bk = books(sub, {s: fund[s] for s in uni})
        res[sample][firm] = {"universe": uni, "annual_vol": (bk.std() * 365 ** 0.5).round(3).to_dict(), "grid": {}}
        for prog in cfg["programs"][firm]:
            for book in bk.columns:
                for L in cfg["scales"]:
                    res[sample][firm]["grid"][f"{prog}|{book}|{L}"] = evaluate_survival(bk[book].to_numpy() * L, v1["firms"][prog])
        print(sample, firm, len(uni), "coins done", flush=True)

works = []
for firm in SIZE:
    for key, d in res["development"][firm]["grid"].items():
        c = res["confirmation"][firm]["grid"][key]
        ok = all(x["breach_rate"] <= 0.25 and x["funded_survival_12m"] >= 0.70 and x["p_paid_by_3m"] >= 0.50 and x["ev_per_fee"] > 0 for x in (d, c))
        if ok:
            works.append({"firm": firm, "config": key, "dev": d, "conf": c,
                          "min_survival": min(d["funded_survival_12m"], c["funded_survival_12m"])})
works.sort(key=lambda w: -w["min_survival"])
res["works"] = works
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
print(len(works), "configurations work")
for w in works[:15]:
    d, c = w["dev"], w["conf"]
    print(f"{w['config']:38s} pass {d['pass_rate']:.0%}/{c['pass_rate']:.0%} breach {d['breach_rate']:.0%}/{c['breach_rate']:.0%} "
          f"days {d['median_days_to_pass']}/{c['median_days_to_pass']} surv12m {d['funded_survival_12m']:.0%}/{c['funded_survival_12m']:.0%} "
          f"paid3m {d['p_paid_by_3m']:.0%}/{c['p_paid_by_3m']:.0%} payout12m {d['mean_payout_12m_pct']:.1f}%/{c['mean_payout_12m_pct']:.1f}% "
          f"EV/fee {d['ev_per_fee']:.1f}/{c['ev_per_fee']:.1f}")

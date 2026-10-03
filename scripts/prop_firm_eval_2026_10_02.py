"""Evaluate prop-firm-v1 (config/prop_firm_v1.json) once. Descriptive (all return series are historical, seen data)."""

from __future__ import annotations

import json
import os
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights, simulate
from orderflow_edge_lab.prop_sim import evaluate

cfg = json.load(open("config/prop_firm_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
END = pd.Timestamp("2026-09-12", tz="UTC")
B = rules["blend"]


def books(cache: str) -> pd.DataFrame:
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs[["S1", "S2", "S3"]], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))
    lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))
    h10, _ = simulate(coin_targets(rules, frames, fund, lw), frames, fund, 10, 20.0)
    out = pd.concat([s4.rename("S4_blend"), legs["S1"].rename("S1_trend"), legs["S2"].rename("S2_xs_momentum"),
                     legs["S3"].rename("S3_carry"), h10.rename("H10_human")], axis=1).dropna()
    return out[out.index < END]


res = {}
for sample, cache in (("development", "multi_premia_data.pkl"), ("confirmation", "multi_premia_untouched_data.pkl")):
    bk = books(cache)
    res[sample] = {"annual_vol": (bk.std() * (365 ** 0.5)).round(3).to_dict(), "days": len(bk), "grid": {}}
    for firm, rule in cfg["firms"].items():
        for book in bk.columns:
            for L in cfg["scales"]:
                res[sample]["grid"][f"{firm}|{book}|{L}"] = evaluate(bk[book].to_numpy() * L, rule)

best = {}
for firm in cfg["firms"]:
    cand = {k: v for k, v in res["development"]["grid"].items() if k.startswith(firm + "|")}
    k = max(cand, key=lambda x: cand[x]["ev_per_fee"])
    d, c = cand[k], res["confirmation"]["grid"][k]
    best[firm] = {"choice": k, "dev": d, "conf": c,
                  "recommended": bool(c["pass_rate"] >= 0.6 * d["pass_rate"] and c["ev_per_100"] > 0)}
res["best_by_firm"] = best
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
print("annual vol (dev):", res["development"]["annual_vol"])
for firm, b in best.items():
    _, book, L = b["choice"].split("|")
    d, c = b["dev"], b["conf"]
    print(f"{firm:22s} {book:15s} x{L:>3s} | dev pass {d['pass_rate']:.0%} days {d['median_days_to_pass']} EV/100 {d['ev_per_100']:+.2f} "
          f"| conf pass {c['pass_rate']:.0%} days {c['median_days_to_pass']} EV/100 {c['ev_per_100']:+.2f} | rec {b['recommended']}")

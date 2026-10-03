"""Evaluate prop-firm-v3 (config/prop_firm_v3.json) once. Descriptive."""

from __future__ import annotations

import itertools
import json
import os
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.prop_sim import evaluate_policy

v1 = json.load(open("config/prop_firm_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
END = pd.Timestamp("2026-09-12", tz="UTC")
B = rules["blend"]
UNI = {"HyroTrader_1step": None, "Breakout_classic_1step": 30, "FTMO_2step": 10}
POLICIES = {"baseline": {"challenge_scale": 0.5, "funded_scale": 0.5}}
for cs, hr, vg, cu in itertools.product([0.75, 1.0], [False, True], [False, True], [0.0, 0.03]):
    POLICIES[f"c{cs}_hr{int(hr)}_vg{int(vg)}_cu{cu}"] = {"challenge_scale": cs, "funded_scale": 0.5, "headroom": hr, "vol_guard": vg, "cushion": cu}


def liquidity_rank(frames):
    dv = {s: float((f["volume"] * f["close"]).groupby(f.index.floor("D")).sum().median()) for s, f in frames.items()}
    return sorted(dv, key=dv.get, reverse=True)


def blend_series(frames, fund):
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs[["S1", "S2", "S3"]], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))
    return s4[s4.index < END]


res = {}
for sample, cache in (("development", "multi_premia_data.pkl"), ("confirmation", "multi_premia_untouched_data.pkl")):
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    ranked = liquidity_rank(frames)
    res[sample] = {}
    for firm, n in UNI.items():
        uni = ranked if n is None else ranked[:n]
        r = blend_series({s: frames[s] for s in uni}, {s: fund[s] for s in uni}).to_numpy()
        res[sample][firm] = {k: evaluate_policy(r, v1["firms"][firm], p) for k, p in POLICIES.items()}
        print(sample, firm, "done", flush=True)


def works(x):
    return x["breach_rate"] <= 0.25 and x["funded_survival_12m"] >= 0.70 and x["p_paid_by_3m"] >= 0.50 and x["ev_per_fee"] > 0


summary = []
for firm in UNI:
    b = {s: res[s][firm]["baseline"] for s in res}
    for k in POLICIES:
        d, c = res["development"][firm][k], res["confirmation"][firm][k]
        w = works(d) and works(c)
        imp = w and all(res[s][firm][k]["pass_rate"] > b[s]["pass_rate"] and res[s][firm][k]["funded_survival_12m"] >= b[s]["funded_survival_12m"] - 0.05 for s in res)
        summary.append({"firm": firm, "policy": k, "works": w, "improves": bool(imp), "dev": d, "conf": c})
res["summary"] = summary
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
for row in summary:
    if row["works"] or row["policy"] == "baseline":
        d, c = row["dev"], row["conf"]
        print(f"{row['firm'][:16]:16s} {row['policy']:26s} works {row['works']!s:5s} improves {row['improves']!s:5s} | pass {d['pass_rate']:.0%}/{c['pass_rate']:.0%} "
              f"breach {d['breach_rate']:.0%}/{c['breach_rate']:.0%} days {d['median_days_to_pass']}/{c['median_days_to_pass']} surv {d['funded_survival_12m']:.0%}/{c['funded_survival_12m']:.0%} "
              f"paid3m {d['p_paid_by_3m']:.0%}/{c['p_paid_by_3m']:.0%} pay12m {d['mean_payout_12m_pct']:.1f}/{c['mean_payout_12m_pct']:.1f}% EV/fee {d['ev_per_fee']:.1f}/{c['ev_per_fee']:.1f}")

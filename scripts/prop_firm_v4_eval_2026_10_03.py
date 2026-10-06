"""Evaluate prop-firm-v4 (config/prop_firm_v4.json) once. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.prop_sim import run_funded_policy, run_phase_policy, trailing_sigma
from orderflow_edge_lab.xs_premia import daily_open_panel

v1 = json.load(open("config/prop_firm_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
END = pd.Timestamp("2026-09-12", tz="UTC")
B = rules["blend"]
UNI = {"HyroTrader_1step": None, "Breakout_classic_1step": 30, "FTMO_2step": 10}
FUNDED = {"funded_scale": 0.5, "headroom": True, "vol_guard": True, "cushion": 0.0}


def liquidity_rank(frames):
    dv = {s: float((f["volume"] * f["close"]).groupby(f.index.floor("D")).sum().median()) for s, f in frames.items()}
    return sorted(dv, key=dv.get, reverse=True)


def blend_series(frames, fund):
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs[["S1", "S2", "S3"]], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))
    return s4[s4.index < END].to_numpy()


def run(r, firm, cscale, funded=True, every=7):
    r = np.nan_to_num(np.asarray(r, dtype=float))
    sig = trailing_sigma(r)
    pol = dict(FUNDED, challenge_scale=cscale)
    outs, adays, fres = [], [], []
    for s0 in range(0, len(r) - 400, every):
        i, total, why = s0, 0, "pass"
        for target in firm["phases"]:
            res = run_phase_policy(r, sig, i, target, firm, pol)
            total += res.days
            if not res.passed:
                why = res.reason
                break
            i = res.end + 1
        if why == "data_end":
            continue
        outs.append(why)
        adays.append(total)
        if why == "pass" and funded:
            f = run_funded_policy(r, sig, i, firm, pol)
            if f["complete"]:
                fres.append(f)
    n = len(outs)
    p = outs.count("pass") / n
    D = float(np.mean(adays))
    out = {"attempts": n, "pass_rate": p, "breach_rate": outs.count("breach") / n, "mean_attempt_days": D,
           "expected_fees_per_funded_pct": 100 * firm["fee_pct"] / p if p else None,
           "expected_days_to_funded": D / p if p else None}
    if funded:
        nf = len(fres)
        out["funded_survival_12m"] = sum(f["survived"] for f in fres) / nf if nf else 0.0
        out["mean_payout_12m_pct"] = 100 * float(np.mean([f["paid"] for f in fres])) if nf else 0.0
        out["net_value_12m_pct"] = out["mean_payout_12m_pct"] - (out["expected_fees_per_funded_pct"] or 1e9)
    return out


res = {}
dev_frames, _ = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
btc = daily_open_panel({"BTC_USDT": dev_frames["BTC_USDT"]})["BTC_USDT"]
btc_r = (btc.shift(-1) / btc - 1.0)[btc.index < END].dropna().to_numpy()
for sample, cache in (("development", "multi_premia_data.pkl"), ("confirmation", "multi_premia_untouched_data.pkl")):
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    ranked = liquidity_rank(frames)
    res[sample] = {}
    for firm, n in UNI.items():
        uni = ranked if n is None else ranked[:n]
        r = blend_series({s: frames[s] for s in uni}, {s: fund[s] for s in uni})
        res[sample][firm] = {f"blend_hr|{c}": run(r, v1["firms"][firm], c) for c in (1.0, 1.5, 2.0, 3.0)}
        if sample == "development":
            res[sample][firm].update({f"gamble_btc|{c}": run(btc_r, v1["firms"][firm], c, funded=False) for c in (1.0, 2.0, 3.0)})
        print(sample, firm, "done", flush=True)

choice = {}
for firm in UNI:
    ok = [k for k in res["development"][firm] if k.startswith("blend")
          and all(res[s][firm][k]["net_value_12m_pct"] > 0 and res[s][firm][k]["funded_survival_12m"] >= 0.7 for s in res)]
    choice[firm] = min(ok, key=lambda k: (max(res[s][firm][k]["expected_days_to_funded"] for s in res), -res["confirmation"][firm][k]["net_value_12m_pct"])) if ok else None
res["choice"] = choice
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
fmt = lambda x, f: "–" if x is None else format(x, f)  # noqa: E731
for firm in UNI:
    print("==", firm, "choice:", choice[firm])
    for k in res["development"][firm]:
        d = res["development"][firm][k]
        c = res["confirmation"][firm].get(k)
        line = f"  {k:14s} dev pass {d['pass_rate']:.0%} breach {d['breach_rate']:.0%} attempt {d['mean_attempt_days']:.0f}d E[days to funded] {fmt(d['expected_days_to_funded'], '.0f')} E[fees] {fmt(d['expected_fees_per_funded_pct'], '.2f')}%"
        if "funded_survival_12m" in d:
            line += f" surv {d['funded_survival_12m']:.0%} pay12m {d['mean_payout_12m_pct']:.1f}% net {d['net_value_12m_pct']:+.1f}%"
        if c:
            line += f" || conf pass {c['pass_rate']:.0%} E[days] {fmt(c['expected_days_to_funded'], '.0f')} surv {c['funded_survival_12m']:.0%} pay {c['mean_payout_12m_pct']:.1f}% net {c['net_value_12m_pct']:+.1f}%"
        print(line)

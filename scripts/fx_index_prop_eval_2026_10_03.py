"""Evaluate fx-index-prop-v1 (config/fx_index_prop_v1.json) once. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.fx_index import (
    close_panel, fx_xs_momentum_weights, long_voltarget_weights, rsi2_dip_weights, run_book, sharpe, tsmom_weights,
)
from orderflow_edge_lab.multi_premia_forward import blend
from orderflow_edge_lab.prop_sim import BUFFER, headroom_multiplier, trailing_sigma
from orderflow_edge_lab.prop_sim_v5 import run_phase
from orderflow_edge_lab.trend_portfolio_forward import summarize

cfg = json.load(open("config/fx_index_prop_v1.json", encoding="utf-8"))
v1 = json.load(open("config/prop_firm_v1.json", encoding="utf-8"))
frames = pickle.load(open(os.path.join(os.environ["TEMP"], "fx_index_data.pkl"), "rb"))
C = cfg["costs"]
fx = close_panel({s: frames[s] for s in cfg["universe"]["fx"]})
ix = close_panel({s: frames[s] for s in cfg["universe"]["indices"]})
books = pd.DataFrame({
    "X1_tsmom_fx": run_book(tsmom_weights(fx), fx, cost_bps=C["fx_round_trip_bps"]),
    "X1_tsmom_index": run_book(tsmom_weights(ix), ix, cost_bps=C["index_round_trip_bps"], long_financing=C["index_long_financing_per_year"]),
    "X2_index_long_voltarget": run_book(long_voltarget_weights(ix), ix, cost_bps=C["index_round_trip_bps"], long_financing=C["index_long_financing_per_year"]),
    "X3_index_rsi2_dips": run_book(rsi2_dip_weights(ix), ix, cost_bps=C["index_round_trip_bps"], long_financing=C["index_long_financing_per_year"]),
    "X4_fx_xs_momentum": run_book(fx_xs_momentum_weights(fx), fx, cost_bps=C["fx_round_trip_bps"]),
})
books = books[books.index >= pd.Timestamp("2006-01-01", tz="UTC")].dropna(how="all").fillna(0.0)
books = books[books.index.dayofweek < 5]
books["X5_fx_index_blend"] = blend(books.copy(), vol_window=90, min_obs=60)
books = books.dropna()
DEV = (books.index < pd.Timestamp("2016-01-01", tz="UTC"))
END = pd.Timestamp("2026-09-12", tz="UTC")
periods = {"development": books[DEV], "confirmation": books[(~DEV) & (books.index < END)]}


def stats(x):
    s = summarize(x, nw_lags=5)
    return {"sharpe_252": sharpe(x), "t": s["newey_west_t"], "annual_return": float(x.mean() * 252), "annual_vol": float(x.std() * np.sqrt(252)),
            "max_drawdown": s["max_drawdown"], "days": len(x)}


res = {"standalone": {p: {k: stats(v[k]) for k in v} for p, v in periods.items()},
       "correlations_dev": periods["development"].corr().round(2).to_dict()}
passing = [k for k in books if k != "X5_fx_index_blend"
           and res["standalone"]["development"][k]["annual_return"] > 0 and res["standalone"]["development"][k]["t"] >= 2
           and res["standalone"]["confirmation"][k]["sharpe_252"] > 0 and res["standalone"]["confirmation"][k]["t"] >= 1.5]
res["standalone_passing"] = passing

# ---- FTMO careers (trading days: horizon 504 ~ 24 months, challenge cap 252 ~ 12 months, payout after 10 days) ----
HORIZON, CAP = 504, 252
PRULE = {"first_eligible_day": 10, "max_per_payout": None}


def hv(st, s):
    sig = st["aux"]["sigma"][st["i"]]
    s = s * headroom_multiplier(st["eq"] - st["floor"])
    if np.isfinite(sig) and sig > 0:
        s = min(s, 0.7 * st["firm"]["daily_loss"] / (2.33 * sig))
    return s


def career(r, s0, firm, cscale, fscale, buffer=BUFFER):
    aux = {"sigma": trailing_sigma(r)}
    end_t = s0 + HORIZON
    t, fees, paid, bought, breaches = s0, 0.0, 0.0, 0, 0
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    trailing = firm["max_loss_type"] == "trailing_eod"
    cfn = lambda st: hv(st, cscale)  # noqa: E731
    while t < end_t:
        fees += firm["fee_pct"]
        bought += 1
        i, why, e = t, "pass", t
        for target in firm["phases"]:
            why, d, e = run_phase(r, i, target, firm, cfn, aux, cap_days=max(1, min(CAP, end_t - i)))
            if why != "pass":
                break
            i = e + 1
        if why != "pass":
            t = max(t + 1, e + 1)
            continue
        eq, peak, k = 1.0, 1.0, 0
        t = i
        while t < end_t:
            floor = (peak if trailing else 1.0) - max_lim
            s = fscale * headroom_multiplier(eq - floor)
            pnl = eq * s * r[t]
            eq += pnl
            t += 1
            k += 1
            if -pnl > daily_lim or eq < floor:
                breaches += 1
                break
            peak = max(peak, eq)
            if k >= PRULE["first_eligible_day"] and eq - 1.0 >= 0.01:
                paid += firm["split"] * (eq - 1.0)
                eq = 1.0
                peak = 1.0
        else:
            if eq > 1.0:
                paid += firm["split"] * (eq - 1.0)
            break
    return paid - fees, fees, bought, breaches


prop_books = ["X5_fx_index_blend"] + passing
res["prop"] = {}
for p, df in periods.items():
    res["prop"][p] = {}
    for b in prop_books:
        r = np.nan_to_num(df[b].to_numpy())
        for firm in ("FTMO_2step", "FTMO_1step"):
            for cs in (1.0, 2.0, 3.0):
                for fsc in (0.5, 0.75, 1.0, 1.25, 1.5):
                    runs = [career(r, s0, v1["firms"][firm], cs, fsc) for s0 in range(0, len(r) - HORIZON, 10)]
                    net = np.array([x[0] for x in runs]) * 100
                    res["prop"][p][f"{b}|{firm}|c{cs}|f{fsc}"] = {
                        "careers": len(runs), "mean_net_pct": float(net.mean()), "median_net_pct": float(np.median(net)),
                        "p10_net_pct": float(np.percentile(net, 10)), "p_net_positive": float((net > 0).mean()),
                        "mean_fees_pct": float(np.mean([x[1] for x in runs]) * 100),
                        "mean_challenges": float(np.mean([x[2] for x in runs])), "mean_breaches": float(np.mean([x[3] for x in runs]))}
rows = []
for k, d in res["prop"]["development"].items():
    c = res["prop"]["confirmation"][k]
    if d["p_net_positive"] >= 0.6 and c["p_net_positive"] >= 0.6:
        rows.append((min(d["mean_net_pct"], c["mean_net_pct"]), k))
rows.sort(reverse=True)
res["prop_best"] = [k for _, k in rows[:10]]
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
for p in periods:
    print("==", p)
    for k, v in res["standalone"][p].items():
        print(f"  {k:26s} Sharpe {v['sharpe_252']:5.2f} t {v['t']:5.2f} ret {v['annual_return']:6.1%} vol {v['annual_vol']:5.1%} DD {v['max_drawdown']:.1%}")
print("standalone passing:", passing)
print("prop best (24-month net % of account, dev/conf):")
for k in res["prop_best"]:
    d, c = res["prop"]["development"][k], res["prop"]["confirmation"][k]
    print(f"  {k:48s} net {d['mean_net_pct']:5.1f}/{c['mean_net_pct']:5.1f} median {d['median_net_pct']:5.1f}/{c['median_net_pct']:5.1f} "
          f"p10 {d['p10_net_pct']:5.1f}/{c['p10_net_pct']:5.1f} P>0 {d['p_net_positive']:.0%}/{c['p_net_positive']:.0%} "
          f"fees {d['mean_fees_pct']:.1f}/{c['mean_fees_pct']:.1f} breaches {d['mean_breaches']:.1f}/{c['mean_breaches']:.1f}")

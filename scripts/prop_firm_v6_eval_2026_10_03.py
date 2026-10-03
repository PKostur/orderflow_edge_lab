"""Evaluate prop-firm-v6 (config/prop_firm_v6.json) once. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.prop_sim import trailing_sigma
from orderflow_edge_lab.prop_sim import BUFFER
from orderflow_edge_lab.prop_sim_v5 import headroom, run_phase, vol_guard
from orderflow_edge_lab.strategy_zoo import market_regimes
from orderflow_edge_lab.xs_premia import daily_open_panel

v1 = json.load(open("config/prop_firm_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
END = pd.Timestamp("2026-09-12", tz="UTC")
B = rules["blend"]
UNI = {"HyroTrader_1step": None, "Breakout_classic_1step": 30, "FTMO_2step": 10}
dev_frames, _ = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
btc_open = daily_open_panel({"BTC_USDT": dev_frames["BTC_USDT"]})["BTC_USDT"]


def liquidity_rank(frames):
    dv = {s: float((f["volume"] * f["close"]).groupby(f.index.floor("D")).sum().median()) for s, f in frames.items()}
    return sorted(dv, key=dv.get, reverse=True)


def series(frames, fund):
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    bl = lambda cols: blend(legs[cols], vol_window=int(B["vol_window_days"]), min_obs=int(B["min_obs"]))  # noqa: E731
    btc_r = (btc_open.shift(-1) / btc_open - 1.0)
    btc_r.index = btc_r.index + pd.Timedelta(days=1)  # canonical stamp: return of day d-1 -> d
    sig20 = np.sign((btc_open / btc_open.shift(20) - 1.0))
    sig20.index = sig20.index + pd.Timedelta(days=1)
    df = pd.concat([bl(["S1", "S2", "S3"]).rename("blend"), legs["S1"].rename("trend"), legs["S2"].rename("mom"),
                    legs["S3"].rename("carry"), bl(["S1", "S2"]).rename("trend_mom"), btc_r.rename("btc"),
                    (btc_r * sig20).rename("btc_trend")], axis=1).dropna()
    df = df[df.index < END]
    reg = market_regimes(daily_open_panel(frames))
    reg.index = reg.index + pd.Timedelta(days=1)
    reg = reg.reindex(df.index)
    df["trend_bull"] = ((reg["trend_efficiency"] == "TREND") | (reg["direction"] == "BULL")).astype(float)
    df["blend_20d"] = df["blend"].shift(1).rolling(20, min_periods=20).sum()
    return df


def aux_for(r, extra):
    a = {"sigma": trailing_sigma(np.nan_to_num(r)), "annvol": trailing_sigma(np.nan_to_num(r)) * np.sqrt(365)}
    a.update(extra)
    return a


def hv(st, s):
    return vol_guard(st, headroom(st, s))


def cppi(m, cap):
    def f(st):
        v = st["aux"]["annvol"][st["i"]]
        return min(cap, m * max(0.0, st["eq"] - st["floor"]) / v) if np.isfinite(v) and v > 0 else 0.0
    return f


def two_speed(st):
    return hv(st, 3.0 if st["eq"] - 1.0 < 0.5 * st["target"] else 1.0)


def catch_up(st):
    return hv(st, min(4.0, 1.0 + 0.02 * st["k"]))


def const_vol(st):
    v = st["aux"]["annvol"][st["i"]]
    return headroom(st, min(5.0, 0.25 / v)) if np.isfinite(v) and v > 0 else 0.0


def ecf(hi, lo):
    def f(st):
        x = st["aux"]["blend_20d"][st["i"]]
        return headroom(st, hi if np.isfinite(x) and x > 0 else lo)
    return f


def regime(st):
    return headroom(st, 2.5 if st["aux"]["trend_bull"][st["i"]] > 0 else 1.0)


def daily_stop(st):
    ctx = st["ctx"]
    if ctx.get("last_pnl", 0.0) < -0.015:
        ctx["cool"] = 2
    s = 0.5 if ctx.get("cool", 0) > 0 else 3.0
    ctx["cool"] = max(0, ctx.get("cool", 0) - 1)
    return hv(st, s)


def profit_lock(st):
    return hv(st, 3.0) if st["eq"] < 1.06 else vol_guard(st, headroom(st, 3.0, floor_override=1.02))



cfg = json.load(open("config/prop_firm_v6.json", encoding="utf-8"))
CHALLENGE = {
    "C01_blend_2x_headroom": ("blend", lambda st: hv(st, 2.0)),
    "C05_constant_vol_25": ("blend", const_vol),
    "C13_blend_3x_profit_lock": ("blend", profit_lock),
    "C14_btc_gamble": ("btc", lambda st: hv(st, 2.0)),
    "C15_btc_trend": ("btc_trend", lambda st: hv(st, 3.0)),
}


def cvol15(st):
    v = st["aux"]["annvol"][st["i"]]
    return headroom(st, min(2.0, 0.15 / v)) if np.isfinite(v) and v > 0 else 0.0


FUNDED = {
    "P1_half_headroom": lambda st: headroom(st, 0.5),
    "P2_three_quarter_headroom": lambda st: headroom(st, 0.75),
    "P3_one_x_headroom": lambda st: headroom(st, 1.0),
    "P4_sprint_then_protect": lambda st: headroom(st, 0.75 if st["ctx"].get("paid") else 1.5),
    "P5_constant_vol_15": cvol15,
}


def funded_payouts(r, start, firm, prule, fn, aux, days=365, buffer=BUFFER):
    eq, peak, paid, first = 1.0, 1.0, 0.0, None
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    ctx = {}
    trailing = firm["max_loss_type"] == "trailing_eod"
    for k in range(days):
        i = start + k
        if i >= len(r):
            return None
        floor = (peak if trailing else 1.0) - max_lim
        st = {"i": i, "k": k, "eq": eq, "floor": floor, "target": None, "firm": firm, "ctx": ctx, "aux": aux}
        pnl = eq * max(0.0, float(fn(st))) * r[i]
        eq += pnl
        if -pnl > daily_lim or eq < floor:
            return {"first_day": first, "end_day": k + 1, "survived": False, "paid": paid}
        peak = max(peak, eq)
        if k + 1 >= prule["first_eligible_day"] and eq - 1.0 >= 0.01:
            amt = eq - 1.0 if prule["max_per_payout"] is None else min(eq - 1.0, prule["max_per_payout"])
            paid += firm["split"] * amt
            eq -= amt
            peak = eq if trailing else max(1.0, eq)
            if first is None:
                first = k + 1
                ctx["paid"] = True
    return {"first_day": first, "end_day": days, "survived": True, "paid": paid}


def evaluate(df, col, cfn, ffn, firm, prule, aux_c, aux_f, every=7):
    rc, rf = np.nan_to_num(df[col].to_numpy()), np.nan_to_num(df["blend"].to_numpy())
    outs, adays, fres = [], [], []
    for s0 in range(0, len(rc) - 400, every):
        i, total, why = s0, 0, "pass"
        for target in firm["phases"]:
            why, d, end = run_phase(rc, i, target, firm, cfn, aux_c)
            total += d
            if why != "pass":
                break
            i = end + 1
        if why == "data_end":
            continue
        outs.append(why)
        adays.append(total)
        if why == "pass":
            f = funded_payouts(rf, i, firm, prule, ffn, aux_f)
            if f is not None:
                fres.append(f)
    n, nf = len(outs), len(fres)
    p = outs.count("pass") / n if n else 0.0
    D = float(np.mean(adays))
    payers = [f for f in fres if f["first_day"] is not None]
    p_pay = len(payers) / nf if nf else 0.0
    d_f = float(np.mean([f["first_day"] if f["first_day"] is not None else f["end_day"] for f in fres])) if nf else None
    out = {"p_pass": p, "D_challenge": D, "funded_samples": nf, "p_pay": p_pay, "D_funded": d_f,
           "median_days_funded_to_first_payout": float(np.median([f["first_day"] for f in payers])) if payers else None,
           "funded_survival_12m": sum(f["survived"] for f in fres) / nf if nf else 0.0,
           "first_year_payouts_pct": 100 * float(np.mean([f["paid"] for f in fres])) if nf else 0.0}
    ok = p > 0 and p_pay > 0
    out["expected_days_to_first_payout"] = (D / p + d_f) / p_pay if ok else None
    out["expected_fees_to_first_payout_pct"] = 100 * firm["fee_pct"] / (p * p_pay) if ok else None
    return out


res = {}
for sample, cache in (("development", "multi_premia_data.pkl"), ("confirmation", "multi_premia_untouched_data.pkl")):
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    ranked = liquidity_rank(frames)
    res[sample] = {}
    for firm, n in UNI.items():
        uni = ranked if n is None else ranked[:n]
        df = series({s: frames[s] for s in uni}, {s: fund[s] for s in uni})
        extra = {"blend_20d": df["blend_20d"].to_numpy(), "trend_bull": df["trend_bull"].to_numpy()}
        aux_f = aux_for(df["blend"].to_numpy(), extra)
        res[sample][firm] = {}
        for cn, (col, cfn) in CHALLENGE.items():
            aux_c = aux_for(df[col].to_numpy(), extra)
            for fn_name, ffn in FUNDED.items():
                res[sample][firm][f"{cn}|{fn_name}"] = evaluate(df, col, cfn, ffn, v1["firms"][firm], cfg["payout_rules"][firm], aux_c, aux_f)
        print(sample, firm, "done", flush=True)

best = {}
for firm in UNI:
    rows = []
    for k, d in res["development"][firm].items():
        c = res["confirmation"][firm][k]
        if all(x["expected_days_to_first_payout"] is not None and x["funded_survival_12m"] >= 0.6 for x in (d, c)):
            rows.append((max(d["expected_days_to_first_payout"], c["expected_days_to_first_payout"]), k))
    rows.sort()
    best[firm] = {"all_sorted": [k for _, k in rows],
                  "best": rows[0][1] if rows else None,
                  "best_non_btc": next((k for _, k in rows if "btc" not in k), None)}
res["best"] = best
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
for firm in UNI:
    print("==", firm, "best:", best[firm]["best"], "| best confirmed (non-BTC):", best[firm]["best_non_btc"])
    for k in best[firm]["all_sorted"][:7]:
        d, c = res["development"][firm][k], res["confirmation"][firm][k]
        print(f"  {k:42s} days-to-1st-payout {d['expected_days_to_first_payout']:.0f}/{c['expected_days_to_first_payout']:.0f} "
              f"fees {d['expected_fees_to_first_payout_pct']:.2f}/{c['expected_fees_to_first_payout_pct']:.2f}% pass {d['p_pass']:.0%}/{c['p_pass']:.0%} "
              f"pay-before-breach {d['p_pay']:.0%}/{c['p_pay']:.0%} funded->paid {d['median_days_funded_to_first_payout']}/{c['median_days_funded_to_first_payout']}d "
              f"surv {d['funded_survival_12m']:.0%}/{c['funded_survival_12m']:.0%} yr1 {d['first_year_payouts_pct']:.1f}/{c['first_year_payouts_pct']:.1f}%")

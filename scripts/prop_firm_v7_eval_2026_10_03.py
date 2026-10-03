"""Evaluate prop-firm-v7 (config/prop_firm_v7.json) once. Descriptive."""

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




cfg = json.load(open("config/prop_firm_v7.json", encoding="utf-8"))
PAYOUT = json.load(open("config/prop_firm_v6.json", encoding="utf-8"))["payout_rules"]
HORIZON = int(cfg["horizon_days"])
CHALLENGE = {
    "C01_blend_2x_headroom": ("blend", lambda st: hv(st, 2.0)),
    "C05_constant_vol_25": ("blend", const_vol),
    "C13_blend_3x_profit_lock": ("blend", profit_lock),
    "C14_btc_gamble": ("btc", lambda st: hv(st, 2.0)),
}


def funded_fn(scale, variant):
    if variant == "headroom":
        return lambda st: headroom(st, scale)

    def f(st):
        v = st["aux"]["annvol"][st["i"]]
        return min(scale, 2.0 * max(0.0, st["eq"] - st["floor"]) / v) if np.isfinite(v) and v > 0 else 0.0
    return f


def career(rc, rf, s0, firm, prule, cfn, ffn, wrule, aux_c, aux_f, buffer=BUFFER):
    end_t = s0 + HORIZON
    t, fees, paid, bought, breaches = s0, 0.0, 0.0, 0, 0
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    trailing = firm["max_loss_type"] == "trailing_eod"
    while t < end_t:
        fees += firm["fee_pct"]
        bought += 1
        i, why = t, "pass"
        for target in firm["phases"]:
            why, d, e = run_phase(rc, i, target, firm, cfn, aux_c, cap_days=max(1, min(365, end_t - i)))
            if why != "pass":
                break
            i = e + 1
        if why != "pass":
            t = max(t + 1, e + 1)
            continue
        # funded
        eq, peak, k, ctx = 1.0, 1.0, 0, {}
        t = i
        while t < end_t:
            floor = (peak if trailing else 1.0) - max_lim
            st = {"i": t, "k": k, "eq": eq, "floor": floor, "target": None, "firm": firm, "ctx": ctx, "aux": aux_f}
            pnl = eq * max(0.0, float(ffn(st))) * rf[t]
            eq += pnl
            t += 1
            k += 1
            if -pnl > daily_lim or eq < floor:
                breaches += 1
                break
            peak = max(peak, eq)
            elig = k >= prule["first_eligible_day"]
            amt = 0.0
            if elig and wrule == "W_on_demand_1pct" and eq - 1.0 >= 0.01:
                amt = eq - 1.0
            elif elig and wrule == "W_monthly" and k % 30 == 0 and eq > 1.0:
                amt = eq - 1.0
            elif elig and wrule == "W_cushion_3pct" and k % 30 == 0 and eq > 1.03:
                amt = eq - 1.03
            if amt > 0:
                if prule["max_per_payout"] is not None:
                    amt = min(amt, prule["max_per_payout"])
                paid += firm["split"] * amt
                eq -= amt
                peak = eq if trailing else max(1.0, eq)
        else:
            if eq > 1.0:
                paid += firm["split"] * (eq - 1.0)
            break
    return {"net": paid - fees, "paid": paid, "fees": fees, "bought": bought, "breaches": breaches}


res = {}
for sample, cache in (("development", "multi_premia_data.pkl"), ("confirmation", "multi_premia_untouched_data.pkl")):
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    ranked = liquidity_rank(frames)
    res[sample] = {}
    for firm, n in UNI.items():
        uni = ranked if n is None else ranked[:n]
        df = series({s: frames[s] for s in uni}, {s: fund[s] for s in uni})
        extra = {"blend_20d": df["blend_20d"].to_numpy(), "trend_bull": df["trend_bull"].to_numpy()}
        rf = np.nan_to_num(df["blend"].to_numpy())
        aux_f = aux_for(rf, extra)
        res[sample][firm] = {}
        for cn, (col, cfn) in CHALLENGE.items():
            rc = np.nan_to_num(df[col].to_numpy())
            aux_c = aux_for(rc, extra)
            for scale in cfg["funded_scales"]:
                for variant in ("headroom", "cppi"):
                    ffn = funded_fn(scale, variant)
                    for w in cfg["withdrawal_rules"]:
                        runs = [career(rc, rf, s0, v1["firms"][firm], PAYOUT[firm], cfn, ffn, w, aux_c, aux_f)
                                for s0 in range(0, len(rc) - HORIZON, 14)]
                        net = np.array([x["net"] for x in runs]) * 100
                        res[sample][firm][f"{cn}|{variant}{scale}|{w}"] = {
                            "careers": len(runs), "mean_net_pct": float(net.mean()), "median_net_pct": float(np.median(net)),
                            "p10_net_pct": float(np.percentile(net, 10)), "p_net_positive": float((net > 0).mean()),
                            "mean_paid_pct": float(np.mean([x["paid"] for x in runs]) * 100),
                            "mean_fees_pct": float(np.mean([x["fees"] for x in runs]) * 100),
                            "mean_challenges_bought": float(np.mean([x["bought"] for x in runs])),
                            "mean_funded_breaches": float(np.mean([x["breaches"] for x in runs]))}
        print(sample, firm, "done", flush=True)

best = {}
for firm in UNI:
    rows = []
    for k, d in res["development"][firm].items():
        c = res["confirmation"][firm][k]
        if d["p_net_positive"] >= 0.6 and c["p_net_positive"] >= 0.6:
            rows.append((min(d["mean_net_pct"], c["mean_net_pct"]), k))
    rows.sort(reverse=True)
    best[firm] = {"sorted": [k for _, k in rows], "best": rows[0][1] if rows else None,
                  "best_non_btc": next((k for _, k in rows if "btc" not in k), None)}
res["best"] = best
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
for firm in UNI:
    print("==", firm, "best:", best[firm]["best"], "| non-BTC:", best[firm]["best_non_btc"])
    for k in best[firm]["sorted"][:8]:
        d, c = res["development"][firm][k], res["confirmation"][firm][k]
        print(f"  {k:52s} net24m {d['mean_net_pct']:.1f}/{c['mean_net_pct']:.1f}% median {d['median_net_pct']:.1f}/{c['median_net_pct']:.1f} "
              f"p10 {d['p10_net_pct']:.1f}/{c['p10_net_pct']:.1f} P(>0) {d['p_net_positive']:.0%}/{c['p_net_positive']:.0%} "
              f"fees {d['mean_fees_pct']:.1f}/{c['mean_fees_pct']:.1f}% bought {d['mean_challenges_bought']:.1f}/{c['mean_challenges_bought']:.1f} "
              f"breaches {d['mean_funded_breaches']:.1f}/{c['mean_funded_breaches']:.1f}")

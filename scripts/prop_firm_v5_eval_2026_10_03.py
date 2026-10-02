"""Evaluate prop-firm-v5 (config/prop_firm_v5.json) once. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.prop_sim import trailing_sigma
from orderflow_edge_lab.prop_sim_v5 import evaluate_pair, headroom, vol_guard
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


CHALLENGE = {
    "C01_blend_2x_headroom": ("blend", lambda st: hv(st, 2.0)),
    "C02_blend_cppi": ("blend", cppi(4.0, 4.0)),
    "C03_two_speed": ("blend", two_speed),
    "C04_catch_up": ("blend", catch_up),
    "C05_constant_vol_25": ("blend", const_vol),
    "C06_equity_curve_filter": ("blend", ecf(2.0, 0.5)),
    "C07_regime_trend_bull": ("blend", regime),
    "C08_momentum_leg_1x": ("mom", lambda st: hv(st, 1.0)),
    "C09_trend_leg_3x": ("trend", lambda st: hv(st, 3.0)),
    "C10_carry_leg_1x": ("carry", lambda st: hv(st, 1.0)),
    "C11_trend_plus_momentum": ("trend_mom", lambda st: headroom(st, 2.0)),
    "C12_blend_3x_daily_stop": ("blend", daily_stop),
    "C13_blend_3x_profit_lock": ("blend", profit_lock),
    "C14_btc_gamble": ("btc", lambda st: hv(st, 2.0)),
    "C15_btc_trend": ("btc_trend", lambda st: hv(st, 3.0)),
}
FUNDED = {
    "F1_half_headroom": lambda st: headroom(st, 0.5),
    "F2_cppi": cppi(2.0, 1.5),
    "F3_equity_curve": ecf(0.75, 0.25),
    "F4_three_quarter_headroom": lambda st: headroom(st, 0.75),
}

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
                res[sample][firm][f"{cn}|{fn_name}"] = evaluate_pair(df[col].to_numpy(), df["blend"].to_numpy(), v1["firms"][firm], cfn, ffn, aux_c, aux_f)
        print(sample, firm, "done", flush=True)

working, rec = [], {}
for firm in UNI:
    for key, d in res["development"][firm].items():
        c = res["confirmation"][firm][key]
        if all(x["funded_survival_12m"] >= 0.7 and x["net_value_12m_pct"] is not None and x["net_value_12m_pct"] > 0 for x in (d, c)):
            working.append({"firm": firm, "pair": key, "worst_days": max(d["expected_days_to_funded"], c["expected_days_to_funded"]),
                            "worst_net": min(d["net_value_12m_pct"], c["net_value_12m_pct"]), "dev": d, "conf": c})
    fw = [w for w in working if w["firm"] == firm]
    rec[firm] = min(fw, key=lambda w: (w["worst_days"], -w["worst_net"]))["pair"] if fw else None
res["working"], res["recommended"] = working, rec
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
print(len(working), "working pairs out of", len(CHALLENGE) * len(FUNDED) * len(UNI))
for firm in UNI:
    fw = sorted([w for w in working if w["firm"] == firm], key=lambda w: (w["worst_days"], -w["worst_net"]))
    print("==", firm, "recommended:", rec[firm])
    for w in fw[:8]:
        d, c = w["dev"], w["conf"]
        print(f"  {w['pair']:46s} days {d['expected_days_to_funded']:.0f}/{c['expected_days_to_funded']:.0f} pass {d['pass_rate']:.0%}/{c['pass_rate']:.0%} "
              f"fees {d['expected_fees_per_funded_pct']:.2f}/{c['expected_fees_per_funded_pct']:.2f}% surv {d['funded_survival_12m']:.0%}/{c['funded_survival_12m']:.0%} "
              f"pay {d['mean_payout_12m_pct']:.1f}/{c['mean_payout_12m_pct']:.1f}% net {d['net_value_12m_pct']:+.1f}/{c['net_value_12m_pct']:+.1f}%")

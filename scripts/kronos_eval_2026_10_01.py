"""Evaluate kronos-v1 (config/kronos_v1.json) from the saved forecasts. Run once after the forecasts are complete."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.trend_portfolio_forward import summarize
from orderflow_edge_lab.xs_premia import daily_funding_panel, daily_open_panel, momentum_score, run_xs

cfg = json.load(open("config/kronos_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
W0, W1 = pd.Timestamp(cfg["test_window"]["start"], tz="UTC"), pd.Timestamp(cfg["test_window"]["end"], tz="UTC")
SPLIT = pd.Timestamp("2025-08-07", tz="UTC")
CACHES = {"development": "multi_premia_data.pkl", "confirmation": "multi_premia_untouched_data.pkl"}


def load(sample):
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], CACHES[sample]), "rb"))
    fc = json.load(open(f"research/kronos/forecasts_{sample}.json"))
    return frames, fund, fc


def score_frame(fc, opens, field):
    sc = pd.DataFrame(np.nan, index=opens.index, columns=opens.columns)
    for day, rows in fc.items():
        d = pd.Timestamp(day, tz="UTC")
        for s, v in rows.items():
            sc.at[d, s] = v[field]
    return sc


def stats(x):
    x = x.dropna()
    s = summarize(x, nw_lags=5)
    return {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365), "max_drawdown": s["max_drawdown"],
            "days": s["days"], "halves": [summarize(x[x.index < SPLIT], nw_lags=5)["annualized_sharpe"],
                                          summarize(x[x.index >= SPLIT], nw_lags=5)["annualized_sharpe"]]}


def diagnostics(fc, opens):
    fwd7 = opens.shift(-7) / opens - 1.0
    absmove = np.log(opens.shift(-7) / opens).abs()
    trail = np.log(opens / opens.shift(1)).rolling(30, min_periods=30).std()
    ic, k2, base = [], [], []
    for day, rows in fc.items():
        d = pd.Timestamp(day, tz="UTC")
        if d not in fwd7.index:
            continue
        df = pd.DataFrame(rows).T
        df["real"] = fwd7.loc[d].reindex(df.index)
        df["absmove"] = absmove.loc[d].reindex(df.index)
        df["trail"] = trail.loc[d].reindex(df.index)
        df = df.dropna()
        if len(df) < 8:
            continue
        ic.append(df["pred_return"].corr(df["real"], method="spearman"))
        k2.append(df["pred_move"].corr(df["absmove"], method="spearman"))
        base.append(df["trail"].corr(df["absmove"], method="spearman"))
    t = lambda a: float(np.mean(a) / (np.std(a, ddof=1) / np.sqrt(len(a)))) if len(a) > 2 else None  # noqa: E731
    return {"rank_ic_mean": float(np.mean(ic)), "rank_ic_t": t(ic), "n": len(ic),
            "k2_kronos_vol_ic": float(np.mean(k2)), "k2_trailing_vol_ic": float(np.mean(base)),
            "k2_kronos_minus_trailing_t": t(np.array(k2) - np.array(base))}


def book(frames, fund, fc):
    opens = daily_open_panel(frames)
    fp = daily_funding_panel(fund, opens.index)
    k1 = run_xs(opens, fp, score_frame(fc, opens, "pred_return"), rebalance_days=7, q=0.25, cost_bps=20)["returns"]
    mom = run_xs(opens, fp, momentum_score(opens, 30), rebalance_days=7, q=0.25, cost_bps=20)["returns"]
    win = (k1.index >= W0) & (k1.index < W1)
    return k1[win], mom[win], opens


res = {}
pool_frames, pool_fund, pool_fc = {}, {}, {}
for sample in CACHES:
    frames, fund, fc = load(sample)
    k1, mom, opens = book(frames, fund, fc)
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs.index >= W0 + pd.Timedelta(days=1)) & (legs.index < W1)]
    z = k1.copy()
    z.index = z.index + pd.Timedelta(days=1)
    b = rules["blend"]
    # blend vol windows need history: compute on full legs, then restrict to the window
    full_legs = leg_returns(rules, frames, fund)
    base = blend(full_legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    four = pd.concat([full_legs[["S1", "S2", "S3"]], z.rename("K1")], axis=1)
    four["K1"] = four["K1"].fillna(0.0)
    b4 = blend(four, vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    sel = lambda s: s[(s.index > W0 + pd.Timedelta(days=90)) & (s.index < W1)]  # noqa: E731  (K1 needs 90 days of history in the blend)
    res[sample] = {"K1": stats(k1), "reference_momentum": stats(mom), "corr_K1_momentum": float(k1.corr(mom)),
                   "diagnostics": diagnostics(fc, opens),
                   "blend3_window": stats(sel(base)), "blend4_window": stats(sel(b4))}
    for s, f in frames.items():
        pool_frames.setdefault(s, f)
        pool_fund.setdefault(s, fund[s])
    for day, rows in fc.items():
        pool_fc.setdefault(day, {}).update(rows)

k1p, momp, opens_p = book(pool_frames, pool_fund, pool_fc)
res["pooled"] = {"K1": stats(k1p), "reference_momentum": stats(momp), "corr_K1_momentum": float(k1p.corr(momp)),
                 "diagnostics": diagnostics(pool_fc, opens_p)}
p = res["pooled"]
res["verdict"] = {
    "K1_pass": bool(p["K1"]["annual_return"] > 0 and p["K1"]["t"] >= 2 and min(p["K1"]["halves"]) > 0
                    and res["development"]["K1"]["sharpe"] > 0 and res["confirmation"]["K1"]["sharpe"] > 0
                    and p["corr_K1_momentum"] < 0.7),
    "K2_kronos_better_both": bool(all(res[s]["diagnostics"]["k2_kronos_vol_ic"] > res[s]["diagnostics"]["k2_trailing_vol_ic"] for s in CACHES)),
}
json.dump(res, open(sys.argv[1], "w"), indent=1, default=float)
for k in ("development", "confirmation", "pooled"):
    r = res[k]
    print(f"{k:12s} K1 S {r['K1']['sharpe']:5.2f} t {r['K1']['t']:5.2f} halves {[round(h, 2) for h in r['K1']['halves']]} DD {r['K1']['max_drawdown']:.2f} | "
          f"mom S {r['reference_momentum']['sharpe']:5.2f} | corr {r['corr_K1_momentum']:.2f} | IC {r['diagnostics']['rank_ic_mean']:.3f} "
          f"(t {r['diagnostics']['rank_ic_t']:.2f}, n {r['diagnostics']['n']}) | volIC kronos {r['diagnostics']['k2_kronos_vol_ic']:.3f} "
          f"trailing {r['diagnostics']['k2_trailing_vol_ic']:.3f}"
          + (f" | blend {r['blend3_window']['sharpe']:.2f}->{r['blend4_window']['sharpe']:.2f}" if "blend3_window" in r else ""))
print(res["verdict"])

"""Evaluate custom-sentiment-v1 (config/custom_sentiment_v1.json) once. Descriptive (contaminated by design)."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.custom_sentiment import (
    extreme_fear_targets, fng_known_at, fng_series, forced_flow_targets, sentiment_following_targets,
)
from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.strategy_zoo import daily_volume_panel, market_regimes, run_targets
from orderflow_edge_lab.trend_portfolio_forward import summarize
from orderflow_edge_lab.xs_premia import daily_funding_panel, daily_open_panel

zoo_cfg = json.load(open("config/strategy_zoo_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
FNG = fng_series(json.load(open("research/custom_sentiment/fng_history_2026_10_01.json"))["data"])
halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in zoo_cfg["halves"]]
END = pd.Timestamp("2026-09-12", tz="UTC")
BV = rules["blend"]


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    s = summarize(x, nw_lags=5)
    return {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365),
            "max_drawdown": s["max_drawdown"], "days": s["days"],
            "halves": [summarize(x[(x.index >= a) & (x.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves]}


def regimes(x: pd.Series, labels: pd.DataFrame) -> dict:
    out = {}
    for dim in labels.columns:
        lab = labels[dim].reindex(x.index)
        out[dim] = {}
        for k in sorted(lab.dropna().unique()):
            y = x[lab == k].dropna()
            out[dim][k] = float(y.mean() / y.std() * np.sqrt(365)) if len(y) > 20 and y.std() > 0 else None
    return out


def evaluate(cache: str) -> dict:
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    opens = daily_open_panel(frames)
    fp = daily_funding_panel(fund, opens.index)
    known = fng_known_at(FNG, opens.index)
    books = pd.DataFrame({
        "C1_forced_flow_with_trend": run_targets(forced_flow_targets(opens, daily_volume_panel(frames)), opens, fp, cost_bps=20),
        "F1_extreme_fear_buy": run_targets(extreme_fear_targets(opens, known), opens, fp, cost_bps=20),
        "F2_sentiment_following": run_targets(sentiment_following_targets(opens, known), opens, fp, cost_bps=20),
    })
    books = books[books.index < END]
    books = books.where(books.ne(0).cumsum() > 0)
    labels = market_regimes(opens)
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    base = blend(legs[["S1", "S2", "S3"]], vol_window=int(BV["vol_window_days"]), min_obs=int(BV["min_obs"]))
    res = {"coins": len(frames), "books": {}, "overlays": {}}
    for k in books:
        x = books[k].dropna()
        e = stats(x)
        e["regimes"] = regimes(x, labels)
        e["exposure_share"] = float((x != 0).mean())
        z = x.copy()
        z.index = z.index + pd.Timedelta(days=1)
        four = pd.concat([legs[["S1", "S2", "S3"]], z.rename("Z")], axis=1).dropna()
        b4 = blend(four, vol_window=int(BV["vol_window_days"]), min_obs=int(BV["min_obs"]))
        idx = b4.index.intersection(base.index)
        e["blend3_sharpe"] = summarize(base.loc[idx], nw_lags=5)["annualized_sharpe"]
        e["blend4_sharpe"] = summarize(b4.loc[idx], nw_lags=5)["annualized_sharpe"]
        res["books"][k] = e
    # overlays: leg return stamped t covers day t-1; the latest F&G usable for it is dated t-2
    f_at = fng_known_at(FNG, legs.index - pd.Timedelta(days=1))
    f_at.index = legs.index
    variants = {
        "O1_greed_brake": legs[["S1", "S2", "S3"]].assign(S1=legs["S1"] * np.where(f_at >= 80, 0.5, 1.0)),
        "O2_panic_momentum_pause": legs[["S1", "S2", "S3"]].assign(S2=legs["S2"] * np.where(f_at <= 25, 0.5, 1.0)),
    }
    b0 = stats(base)
    res["blend_base"] = b0
    for k, lg in variants.items():
        bv = stats(blend(lg, vol_window=int(BV["vol_window_days"]), min_obs=int(BV["min_obs"])))
        bv["share_days_scaled"] = float(((f_at >= 80) if k.startswith("O1") else (f_at <= 25)).mean())
        res["overlays"][k] = bv
    return res


out = {"development": evaluate("multi_premia_data.pkl"), "confirmation": evaluate("multi_premia_untouched_data.pkl")}
verd = {}
for k in out["development"]["books"]:
    d, c = out["development"]["books"][k], out["confirmation"]["books"][k]
    ok = d["annual_return"] > 0 and d["t"] >= 2 and min(d["halves"]) > 0 and c["sharpe"] > 0 and c["t"] >= 1.5
    verd[k] = {"overall": "PASS" if ok else "FAIL", "bonferroni_survives": bool(d["t"] >= 2.6)}
for k in out["development"]["overlays"]:
    better, halves_better, dd_ok = [], 0, True
    for s in ("development", "confirmation"):
        o, b = out[s]["overlays"][k], out[s]["blend_base"]
        better.append(o["sharpe"] > b["sharpe"])
        halves_better += sum(x > y for x, y in zip(o["halves"], b["halves"]))
        dd_ok &= o["max_drawdown"] >= b["max_drawdown"]
    verd[k] = {"overall": "PASS" if all(better) and halves_better >= 3 and dd_ok else "FAIL"}
out["verdicts"] = verd
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
for k in out["development"]["books"]:
    d, c = out["development"]["books"][k], out["confirmation"]["books"][k]
    print(f"{k:27s} dev S {d['sharpe']:5.2f} t {d['t']:5.2f} halves {[round(h, 2) for h in d['halves']]} DD {d['max_drawdown']:.2f} "
          f"exp {d['exposure_share']:.2f} | conf S {c['sharpe']:5.2f} t {c['t']:5.2f} | blend {d['blend3_sharpe']:.2f}->{d['blend4_sharpe']:.2f} / "
          f"{c['blend3_sharpe']:.2f}->{c['blend4_sharpe']:.2f} | {verd[k]['overall']}")
for s in ("development", "confirmation"):
    b = out[s]["blend_base"]
    print(s, "blend base", round(b["sharpe"], 2), [round(h, 2) for h in b["halves"]], round(b["max_drawdown"], 3))
    for k, o in out[s]["overlays"].items():
        print("  ", k, round(o["sharpe"], 2), [round(h, 2) for h in o["halves"]], round(o["max_drawdown"], 3), "scaled days", round(o["share_days_scaled"], 3))
print({k: v["overall"] for k, v in verd.items()})

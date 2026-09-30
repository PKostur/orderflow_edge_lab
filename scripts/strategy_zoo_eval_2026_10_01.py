"""Evaluate strategy-zoo-v1 (config/strategy_zoo_v1.json) once, on development then confirmation samples. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.strategy_zoo import market_regimes, zoo_books
from orderflow_edge_lab.trend_portfolio_forward import summarize
from orderflow_edge_lab.xs_premia import daily_funding_panel, daily_open_panel

cfg = json.load(open("config/strategy_zoo_v1.json", encoding="utf-8"))
rules = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
halves = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")) for a, b in cfg["halves"]]
END = pd.Timestamp("2026-09-12", tz="UTC")


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    s = summarize(x, nw_lags=5)
    return {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365),
            "max_drawdown": s["max_drawdown"], "days": s["days"],
            "halves": [summarize(x[(x.index >= a) & (x.index < b)], nw_lags=5)["annualized_sharpe"] for a, b in halves]}


def by_regime(x: pd.Series, labels: pd.DataFrame) -> dict:
    out = {}
    for dim in labels.columns:
        lab = labels[dim].reindex(x.index)
        out[dim] = {}
        for k in sorted(lab.dropna().unique()):
            y = x[lab == k].dropna()
            sd = y.std()
            out[dim][k] = {"days": int(len(y)), "mean_bps_day": float(y.mean() * 1e4),
                           "sharpe": float(y.mean() / sd * np.sqrt(365)) if sd > 0 else None}
    return out


DEV_FRAMES, _ = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))


def evaluate(cache: str) -> dict:
    frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    opens = daily_open_panel(frames)
    fp = daily_funding_panel(fund, opens.index)
    books = zoo_books(frames, fp, btc_frame=DEV_FRAMES["BTC_USDT"])  # BTC is signal-only when not in the sample
    books = books[books.index < END]
    books = books.loc[:, :].where(books.ne(0).cumsum() > 0)  # start each book at its first active day
    labels = market_regimes(opens)
    res = {"coins": len(frames), "books": {}}
    # blend addition: legs are stamped d+1, zoo books at d -> shift zoo by one day
    legs = leg_returns(rules, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    b = rules["blend"]
    base = blend(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    for k in books:
        x = books[k].dropna()
        entry = stats(x)
        entry["regimes"] = by_regime(x, labels)
        z = x.copy()
        z.index = z.index + pd.Timedelta(days=1)
        four = pd.concat([legs[["S1", "S2", "S3"]], z.rename("Z")], axis=1).dropna()
        b4 = blend(four, vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
        idx = b4.index.intersection(base.index)
        entry["blend3_sharpe"] = summarize(base.loc[idx], nw_lags=5)["annualized_sharpe"]
        entry["blend4_sharpe"] = summarize(b4.loc[idx], nw_lags=5)["annualized_sharpe"]
        entry["corr_to_legs"] = {c: float(four["Z"].corr(four[c])) for c in ("S1", "S2", "S3")}
        res["books"][k] = entry
    res["regime_share"] = {dim: labels[dim].value_counts(normalize=True).round(3).to_dict() for dim in labels.columns}
    return res


out = {"development": evaluate("multi_premia_data.pkl"), "confirmation": evaluate("multi_premia_untouched_data.pkl")}
verdicts = {}
for k in out["development"]["books"]:
    d, c = out["development"]["books"][k], out["confirmation"]["books"][k]
    dev = bool(d["annual_return"] > 0 and d["t"] >= 2.0 and min(d["halves"]) > 0)
    conf = bool(c["sharpe"] > 0 and c["t"] >= 1.5)
    verdicts[k] = {"development_pass": dev, "confirmation_pass": conf, "bonferroni_survives": bool(d["t"] >= 2.7),
                   "overall": "PASS" if dev and conf else "FAIL"}
out["verdicts"] = verdicts
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
for k, v in verdicts.items():
    d, c = out["development"]["books"][k], out["confirmation"]["books"][k]
    print(f"{k:22s} dev S {d['sharpe']:5.2f} t {d['t']:5.2f} halves {[round(h, 2) for h in d['halves']]} DD {d['max_drawdown']:.2f} | "
          f"conf S {c['sharpe']:5.2f} t {c['t']:5.2f} | blend {d['blend3_sharpe']:.2f}->{d['blend4_sharpe']:.2f} / "
          f"{c['blend3_sharpe']:.2f}->{c['blend4_sharpe']:.2f} | {v['overall']}{' (Bonferroni ok)' if v['bonferroni_survives'] else ''}")

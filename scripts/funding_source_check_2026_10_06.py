"""funding-source-check-v1 (config/funding_source_check_v1.json): MEXC prices with Binance vs MEXC funding. Run once.

Usage: python scripts/funding_source_check_2026_10_06.py research/fast_gates/funding_source_check.json
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.trend_portfolio_forward import summarize

CFG = json.load(open("config/funding_source_check_v1.json", encoding="utf-8"))
BCFG = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
SPLICE = pd.Timestamp("2025-04-15", tz="UTC")
W0, W1 = (pd.Timestamp(x, tz="UTC") for x in CFG["data"]["evaluation_window"])
MCACHE = os.path.join(os.environ["TEMP"], "funding_source_check_mexc.pkl")


def books(frames, funding) -> pd.DataFrame:
    legs = leg_returns(BCFG, frames, funding)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    legs["S4"] = blend(legs[["S1", "S2", "S3"]], vol_window=int(BCFG["blend"]["vol_window_days"]), min_obs=int(BCFG["blend"]["min_obs"]))
    return legs[(legs.index >= W0) & (legs.index < W1)]


def stats(x: pd.Series) -> dict:
    s = summarize(x.dropna(), nw_lags=5)
    return {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "annual_return": float(x.mean() * 365), "days": s["days"]}


def run_sample(name: str, cache: str, mexc_fund: dict) -> dict:
    frames, fund_a = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    fund_b, corr = {}, {}
    for s in frames:
        a = fund_a.get(s)
        if a is None or not isinstance(a.index, pd.DatetimeIndex):
            a = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        m = mexc_fund.get(s)
        if m is None or not len(m):
            fund_b[s] = a
            continue
        fund_b[s] = pd.concat([a[a.index < SPLICE], m[m.index >= SPLICE]]).sort_index()
        j = a.index.intersection(m.index)
        j = j[(j >= W0) & (j < W1)]
        if len(j) > 30:
            corr[s] = float(a.loc[j].corr(m.loc[j]))
    A, B = books(frames, fund_a), books(frames, fund_b)
    out = {"coins": len(frames), "coins_with_mexc_funding": sum(1 for s in frames if mexc_fund.get(s) is not None and len(mexc_fund[s])),
           "funding_corr_median": float(pd.Series(corr).median()) if corr else None, "legs": {}}
    for k in ("S1", "S2", "S3", "S4"):
        d = (B[k] - A[k]).dropna()
        out["legs"][k] = {"A_binance_funding": stats(A[k]), "B_mexc_funding": stats(B[k]),
                          "diff_B_minus_A": {"annual": float(d.mean() * 365), "t": summarize(d, nw_lags=5)["newey_west_t"]}}
    s4 = out["legs"]["S4"]
    ra, rb, t = s4["A_binance_funding"]["annual_return"], s4["B_mexc_funding"]["annual_return"], s4["diff_B_minus_A"]["t"]
    out["reading"] = "MATERIAL" if (ra > 0 and rb < 0.5 * ra) or (ra <= 0 and rb < ra) or t <= -2 else "NOT_MATERIAL"
    print(name, json.dumps({k: {"A": round(v["A_binance_funding"]["sharpe"], 2), "B": round(v["B_mexc_funding"]["sharpe"], 2),
                                "A_ret": round(v["A_binance_funding"]["annual_return"], 3), "B_ret": round(v["B_mexc_funding"]["annual_return"], 3),
                                "diff_t": round(v["diff_B_minus_A"]["t"], 2)} for k, v in out["legs"].items()}), out["reading"], flush=True)
    return out


def main(out_path: str) -> int:
    syms = set()
    for c in ("multi_premia_data.pkl", "multi_premia_untouched_data.pkl"):
        syms |= set(pickle.load(open(os.path.join(os.environ["TEMP"], c), "rb"))[0])
    if os.path.exists(MCACHE):
        mexc = pickle.load(open(MCACHE, "rb"))
    else:
        def load(s):
            try:
                return s, fetch_mexc_funding_history(s, "2025-01-01", W1.isoformat())["funding_rate"].astype(float)
            except Exception:
                return s, None
        with ThreadPoolExecutor(4) as ex:
            mexc = dict(ex.map(load, sorted(syms)))
        pickle.dump(mexc, open(MCACHE, "wb"))
    res = {"check_id": CFG["check_id"], "window": [str(W0.date()), str(W1.date())],
           "development_70": run_sample("development_70", "multi_premia_data.pkl", mexc),
           "untouched_60": run_sample("untouched_60", "multi_premia_untouched_data.pkl", mexc)}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "research/fast_gates/funding_source_check.json"))

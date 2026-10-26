"""hyperliquid-venue-check-v1 (config/hyperliquid_venue_check_v1.json): frozen multi-premia blend on Hyperliquid. Run once.

The MEXC/Binance reference is recomputed on the same coins from the development cache (%TEMP%/multi_premia_data.pkl).
Usage: python scripts/hyperliquid_venue_check_2026_10_09.py research/fast_gates/hyperliquid_venue_check.json
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.hyperliquid_history import (
    _post,
    fetch_hyperliquid_candles,
    fetch_hyperliquid_funding,
    hyperliquid_coin,
)
from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.trend_portfolio_forward import summarize

CFG = json.load(open("config/hyperliquid_venue_check_v1.json", encoding="utf-8"))
BCFG = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
START, END = CFG["data"]["window"]
CACHE = os.path.join(os.environ["TEMP"], "hyperliquid_venue_data.pkl")


def s4_stats(frames, funding) -> tuple[dict, pd.Series]:
    legs = leg_returns(BCFG, frames, funding)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs, vol_window=int(BCFG["blend"]["vol_window_days"]), min_obs=int(BCFG["blend"]["min_obs"]))
    out = {}
    for k, x in list(legs.items()) + [("S4", s4)]:
        s = summarize(x.dropna(), nw_lags=5)
        out[k] = {"sharpe": s["annualized_sharpe"], "t": s["newey_west_t"], "max_drawdown": s["max_drawdown"], "days": s["days"],
                  "annual_return": float(x.mean() * 365)}
    return out, s4


def fetch_all(syms: list[str]) -> dict:
    meta = _post({"type": "meta"})
    names = {u["name"] for u in meta["universe"]}
    cmap = {s: hyperliquid_coin(s, names) for s in syms}

    def load(s):
        coin = cmap[s]
        if coin is None:
            return s, None
        try:
            return s, (coin, fetch_hyperliquid_candles(coin, "8h", START, END), fetch_hyperliquid_funding(coin, START, END))
        except Exception as exc:
            print("fail", s, coin, repr(exc), flush=True)
            return s, None

    with ThreadPoolExecutor(3) as ex:
        got = dict(ex.map(load, syms))
    return {s: v for s, v in got.items() if v is not None and len(v[1]) > 400}


def main(out_path: str) -> int:
    ref_frames, ref_fund = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
    syms = BCFG["symbols"]
    if os.path.exists(CACHE):
        data = pickle.load(open(CACHE, "rb"))
    else:
        data = fetch_all(syms)
        pickle.dump(data, open(CACHE, "wb"))
    coins = sorted(s for s in data if s in ref_frames)
    v_stats, v_s4 = s4_stats({s: data[s][1] for s in coins}, {s: data[s][2] for s in coins})
    r_stats, r_s4 = s4_stats({s: ref_frames[s] for s in coins}, {s: ref_fund[s] for s in coins})
    common = v_s4.index.intersection(r_s4.index)
    v_c, r_c = summarize(v_s4.loc[common], nw_lags=5), summarize(r_s4.loc[common], nw_lags=5)
    ok = len(coins) >= 40 and v_c["annualized_sharpe"] >= 0.5 * r_c["annualized_sharpe"] and v_c["newey_west_t"] >= 2.0
    res = {
        "check_id": CFG["check_id"], "window": [START, END], "pass_rule": CFG["pass_rule"], "coins": len(coins),
        "missing": sorted(set(syms) - set(coins)), "contracts": {s: data[s][0] for s in coins},
        "common_dates": {"days": len(common), "first": str(common.min()) if len(common) else None, "last": str(common.max()) if len(common) else None,
                         "hyperliquid_S4": {"sharpe": v_c["annualized_sharpe"], "t": v_c["newey_west_t"], "annual_return": float(v_s4.loc[common].mean() * 365)},
                         "reference_S4": {"sharpe": r_c["annualized_sharpe"], "t": r_c["newey_west_t"], "annual_return": float(r_s4.loc[common].mean() * 365)}},
        "hyperliquid_full_period": v_stats, "reference_full_period": r_stats,
        "s4_daily_correlation": float(v_s4.loc[common].corr(r_s4.loc[common])),
        "passes": bool(ok), "verdict": "PASS" if ok else "FAIL",
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1, default=float)
    print("verdict", res["verdict"], json.dumps({"coins": len(coins), "common_days": len(common),
                                                  "hl_S4": res["common_dates"]["hyperliquid_S4"], "ref_S4": res["common_dates"]["reference_S4"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "research/fast_gates/hyperliquid_venue_check.json"))

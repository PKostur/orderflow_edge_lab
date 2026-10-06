"""fast-gates-v1 G3: rerun the frozen multi-premia-v1 blend on Binance and Bybit (config/fast_gates_v1.json). Run once.

The MEXC reference is recomputed on the same coins from the development cache (%TEMP%/multi_premia_data.pkl).
Usage: python scripts/fast_gates_venue_replication_2026_10_04.py artifacts/fast_gates/venue_replication.json
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import pickle
import sys
import time
import urllib.request

import pandas as pd

from orderflow_edge_lab.bybit_history import fetch_bybit_linear_funding_history
from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.trend_portfolio_forward import summarize

GATES = json.load(open("config/fast_gates_v1.json", encoding="utf-8"))
BCFG = json.load(open("config/multi_premia_blend_v1.json", encoding="utf-8"))
START, END = "2020-06-01", "2026-09-12"
S_MS, E_MS = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000), int(pd.Timestamp(END, tz="UTC").timestamp() * 1000)
ALIAS = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}
CACHE = os.path.join(os.environ["TEMP"], "fast_gates_venue_data.pkl")


def _get(url: str):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "orderflow-edge-lab/1.0"}), timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2.0 * (attempt + 1))


def _frame(rows: dict[int, list[float]]) -> pd.DataFrame:
    f = pd.DataFrame.from_dict(rows, orient="index", columns=["open", "high", "low", "close", "volume"]).sort_index()
    f.index = pd.to_datetime(f.index, unit="ms", utc=True).rename("timestamp")
    return f


def binance(sym: str):
    for cand in sym_candidates(sym):
        rows, s0 = {}, S_MS
        try:
            while s0 < E_MS:
                d = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={cand}&interval=8h&startTime={s0}&endTime={E_MS - 1}&limit=1500")
                if not d:
                    break
                for k in d:
                    if int(k[6]) < E_MS:  # completed before the window end
                        rows[int(k[0])] = [float(x) for x in k[1:6]]
                s0 = int(d[-1][0]) + 1
                if len(d) < 1500:
                    break
        except Exception:
            rows = {}
        if rows:
            fund, s0 = [], S_MS
            while s0 < E_MS:
                d = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={cand}&startTime={s0}&endTime={E_MS}&limit=1000")
                if not d:
                    break
                fund += d
                s0 = int(d[-1]["fundingTime"]) + 1
                if len(d) < 1000:
                    break
            fs = pd.Series({pd.Timestamp(int(x["fundingTime"]), unit="ms", tz="UTC"): float(x["fundingRate"]) for x in fund}, dtype=float).sort_index()
            return cand, _frame(rows), fs
    return None, None, None


def bybit(sym: str):
    for cand in sym_candidates(sym):
        rows, end = {}, E_MS - 1
        try:
            while end > S_MS:
                d = _get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={cand}&interval=240&start={S_MS}&end={end}&limit=1000")
                items = d["result"]["list"]
                if not items:
                    break
                for k in items:
                    rows[int(k[0])] = [float(x) for x in k[1:6]]
                oldest = min(int(k[0]) for k in items)
                if len(items) < 1000 or oldest <= S_MS:
                    break
                end = oldest - 1
        except Exception:
            rows = {}
        if rows:
            h4 = _frame(rows)
            h4 = h4[h4.index + pd.Timedelta(hours=4) <= pd.Timestamp(END, tz="UTC")]
            g = h4.resample("8h", origin="epoch")
            h8 = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                               "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["open"].count()})
            h8 = h8[h8["n"] == 2].drop(columns="n")  # both 4h halves present
            fs = fetch_bybit_linear_funding_history(cand, START, END)["funding_rate"].astype(float)
            return cand, h8, fs
    return None, None, None


def sym_candidates(sym: str) -> list[str]:
    base = sym.replace("_USDT", "")
    base = ALIAS.get(base, base)
    return [f"{base}USDT", f"1000{base}USDT"]


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


def main(out_path: str) -> int:
    mexc_frames, mexc_fund = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
    syms = BCFG["symbols"]
    if os.path.exists(CACHE):
        data = pickle.load(open(CACHE, "rb"))
    else:
        data = {}
        for name, fn, workers in (("binance", binance, 4), ("bybit", bybit, 4)):
            with ThreadPoolExecutor(workers) as ex:
                got = list(ex.map(fn, syms))
            data[name] = {s: (c, f, fu) for s, (c, f, fu) in zip(syms, got) if f is not None and len(f) > 400}
            print(name, len(data[name]), "coins", flush=True)
        pickle.dump(data, open(CACHE, "wb"))
    rule = GATES["gates"]["G3_venue_replication"]
    res = {"gate": "G3_venue_replication", "window": [START, END], "pass_rule_per_venue": rule["pass_rule_per_venue"], "venues": {}}
    for name, d in data.items():
        coins = sorted(s for s in d if s in mexc_frames)
        vf = {s: d[s][1] for s in coins}
        vfu = {s: d[s][2] for s in coins}
        v_stats, v_s4 = s4_stats(vf, vfu)
        m_stats, m_s4 = s4_stats({s: mexc_frames[s] for s in coins}, {s: mexc_fund[s] for s in coins})
        common = v_s4.index.intersection(m_s4.index)
        ok = (len(coins) >= 40 and v_stats["S4"]["sharpe"] >= 0.5 * m_stats["S4"]["sharpe"] and v_stats["S4"]["t"] >= 2.0)
        res["venues"][name] = {"coins": len(coins), "missing": sorted(set(syms) - set(coins)),
                               "contracts": {s: d[s][0] for s in coins}, "venue": v_stats, "mexc_reference": m_stats,
                               "s4_daily_correlation": float(v_s4.loc[common].corr(m_s4.loc[common])),
                               "passes": bool(ok)}
        print(name, json.dumps({"coins": len(coins), "S4": v_stats["S4"], "mexc_S4": m_stats["S4"], "passes": ok}), flush=True)
    n = sum(v["passes"] for v in res["venues"].values())
    res["verdict"] = "PASS" if n == 2 else ("MIXED" if n == 1 else "FAIL")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1, default=float)
    print("verdict", res["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "artifacts/fast_gates/venue_replication.json"))

"""One-shot evaluation of untouched-coins-holdout-v2 (config/untouched_coins_holdout_v2.json)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import sys
import urllib.request

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

cfg = json.load(open("config/untouched_coins_holdout_v2.json", encoding="utf-8"))
start, end = cfg["window"]["start"], cfg["window"]["end_exclusive"]
ALIASES = {"FILECOIN": "FIL", "TRUMPOFFICIAL": "TRUMP", "PUMPFUN": "PUMP"}


def binance_funding(sym: str) -> pd.Series | None:
    base = sym.replace("_USDT", "")
    base = ALIASES.get(base, base)
    for cand in (f"{base}USDT", f"1000{base}USDT"):
        s0, e0, rows = int(pd.Timestamp(start).timestamp() * 1000), int(pd.Timestamp(end).timestamp() * 1000), []
        try:
            while s0 < e0:
                url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={cand}&startTime={s0}&endTime={e0}&limit=1000"
                with urllib.request.urlopen(url, timeout=30) as r:
                    d = json.load(r)
                if not d:
                    break
                rows += d
                s0 = int(d[-1]["fundingTime"]) + 1
                if len(d) < 1000:
                    break
        except Exception:
            rows = []
        if rows:
            return pd.Series({pd.Timestamp(int(x["fundingTime"]), unit="ms", tz="UTC"): float(x["fundingRate"]) for x in rows}).sort_index()
    return None


def load(sym: str):
    try:
        f = fetch_mexc_futures_klines(sym, "8h", start, end)
    except Exception as exc:
        return sym, None, None, f"klines: {exc}"[:80]
    fund = binance_funding(sym)
    source = "binance"
    if fund is None or fund.empty:
        try:
            fund = fetch_mexc_funding_history(sym, start, end)["funding_rate"]
            source = "mexc"
        except Exception:
            fund, source = pd.Series(dtype=float), "none"
    return sym, f, fund, source


with ThreadPoolExecutor(4) as ex:
    loaded = list(ex.map(load, cfg["source"]["symbols"]))
frames = {s: f for s, f, _, _ in loaded if f is not None and len(f) > 400}
funding = {s: fu for s, f, fu, _ in loaded if s in frames}
sources = {s: src for s, _, _, src in loaded}
core = core_strategy({x["audit_id"]: x["parameters"] for x in cfg["strategies"]}, exit_window=None)
sz = cfg["sizing"]
sized = vol_sized_strategy(core, window=int(sz["window_bars"]), target_vol=float(sz["target_annual_vol"]),
                           cap=float(sz["cap"]), bars_per_year=int(sz["bars_per_year"]))
ex_m = ExecutionModel(round_trip_cost_bps=float(cfg["economics"]["round_trip_cost_bps"]))
cols, cols_pm, coin_total, coverage = {}, {}, {}, {}
for s, f in frames.items():
    r = run_canonical_backtest_v3(f, sized, {}, ex_m, return_equity=True, funding=funding[s])
    cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
    coin_total[s] = float(r["total_return"])
    coverage[s] = r["accounting"].get("funding_coverage")
    rp = run_canonical_backtest_v3(f, core, {}, ex_m, return_equity=True, funding=funding[s])
    cols_pm[s] = _daily(rp["equity_path"].iloc[:-1]).pct_change()


def port(c):
    d = pd.DataFrame(c).iloc[1:].mean(axis=1).dropna()
    return d[d.index >= d[d != 0].index[0]]


d, dpm = port(cols), port(cols_pm)
primary = summarize(d, nw_lags=5)
passed = bool(primary["mean_daily_bps"] > 0 and primary["newey_west_t"] is not None and primary["newey_west_t"] >= 2.0)
data_hash = sha256("".join(f"{s}:{len(f)}:{float(f['open'].sum()):.6f}" for s, f in sorted(frames.items())).encode()).hexdigest()
out = {
    "protocol_id": cfg["protocol_id"], "data_hash": data_hash, "symbols_evaluated": sorted(frames),
    "symbols_missing": sorted(set(cfg["source"]["symbols"]) - set(frames)),
    "funding_source": sources, "funding_coverage": coverage,
    "primary": {**primary, "pass_rule": cfg["hypotheses"]["primary"]["pass_rule"], "passed": passed},
    "secondary": {"plus_minus_one": summarize(dpm, nw_lags=5),
                  "per_year": {str(y): float((1 + x).prod() - 1) for y, x in d.groupby(d.index.year)},
                  "share_coins_positive": float(np.mean([v > 0 for v in coin_total.values()])),
                  "coin_total_return_quantiles": [float(q) for q in np.quantile(list(coin_total.values()), [0.1, 0.25, 0.5, 0.75, 0.9])]},
}
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/untouched_v2.json", "w"), indent=1, default=float)
p = out["primary"]
print(json.dumps({"passed": passed, "sharpe": round(p["annualized_sharpe"], 3), "t": round(p["newey_west_t"], 3),
                  "coins": len(frames), "missing": out["symbols_missing"]}))

"""Evaluate the declared regime-switch variants (config/regime_switch_v1.json). Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.etf_history_holdout import fetch_yahoo_daily
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.regime_switch import VARIANTS, regime_labels, regime_shares, regime_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy


def load(universe: str, cfg: dict) -> dict[str, pd.DataFrame]:
    u = cfg["universes"][universe]
    start, end = u["window"]
    src = json.load(open(u["symbols_from"], encoding="utf-8"))
    if universe == "crypto":
        syms = src["groups"]["crypto"]

        def get(s):
            try:
                return s, fetch_mexc_futures_klines(s, "8h", start, end)
            except Exception:
                return s, None
    else:
        syms = [s for m in src["universe_rule"]["symbols"].values() for s in m]

        def get(s):
            f = fetch_yahoo_daily(s, "2006-01-01", end)
            return s, f.loc[(f.index >= pd.Timestamp(start)) & (f.index < pd.Timestamp(end))]
    with ThreadPoolExecutor(4) as ex:
        return {s: f for s, f in ex.map(get, syms) if f is not None and len(f) > 700}


def evaluate(universe: str, cfg: dict, frames: dict) -> dict:
    u, sz = cfg["universes"][universe], cfg["sizing"]
    ex = ExecutionModel(round_trip_cost_bps=float(u["round_trip_cost_bps"]))
    series, out = {}, {}
    for v in VARIANTS:
        strat = vol_sized_strategy(regime_strategy(v, cfg, universe), window=int(sz["window_bars"][universe]),
                                   target_vol=float(sz["target_annual_vol"]), cap=float(sz["cap"]),
                                   bars_per_year=int(sz["bars_per_year"][universe]))
        cols = {}
        for s, f in frames.items():
            eq = run_canonical_backtest_v3(f, strat, {}, ex, return_equity=True)["equity_path"]
            cols[s] = _daily(eq.iloc[:-1]).pct_change()
        r = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
        r = r[r.index >= r[r != 0].index[0]] if (r != 0).any() else r
        series[v] = r
        out[v] = summarize(r, nw_lags=5)
        out[v]["per_year"] = {str(y): float((1 + x).prod() - 1) for y, x in r.groupby(r.index.year)}
    shares = pd.DataFrame({s: regime_shares(f, cfg["regime"]) for s, f in frames.items()}).T.mean().to_dict()
    # attribution: portfolio return on days when the median asset is labelled CHOP vs not
    labs = pd.DataFrame({s: _daily(regime_labels(f, cfg["regime"]).map({"CHOP": 1.0, "MIXED": 0.0, "TREND": 0.0})
                                   .astype(float)) for s, f in frames.items()})
    chop_share_day = labs.mean(axis=1)
    attrib = {}
    for v, r in series.items():
        c = chop_share_day.reindex(r.index).shift(1)  # label known before the day's return
        hi, lo = r[c >= 0.5], r[c < 0.5]
        attrib[v] = {"mean_bps_mostly_chop_days": float(hi.mean() * 1e4) if len(hi) else None,
                     "mean_bps_other_days": float(lo.mean() * 1e4) if len(lo) else None,
                     "mostly_chop_days": int(len(hi))}
    corr = pd.DataFrame(series).corr().round(3).to_dict()
    return {"symbols": sorted(frames), "summary": out, "regime_shares": shares, "attribution": attrib,
            "correlations": corr}


if __name__ == "__main__":
    cfg = json.load(open("config/regime_switch_v1.json", encoding="utf-8"))
    result = {u: evaluate(u, cfg, load(u, cfg)) for u in ("crypto", "etf")}
    out = sys.argv[1] if len(sys.argv) > 1 else "artifacts/regime_switch_eval.json"
    json.dump(result, open(out, "w"), indent=1, default=float)
    print("done")

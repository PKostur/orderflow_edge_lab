"""Evaluate the declared portfolio vol-targeting overlay (config/portfolio_vol_target_v1.json). Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.portfolio_vol_target import vol_target_overlay
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

cfg = json.load(open("config/portfolio_vol_target_v1.json", encoding="utf-8"))
ex_cfg = json.load(open("config/trend_channel_exit_v1.json", encoding="utf-8"))
syms = json.load(open("config/crypto_trend_core_v1.json", encoding="utf-8"))["groups"]["crypto"]


def get(s):
    try:
        return s, fetch_mexc_futures_klines(s, "8h", "2020-06-01T00:00:00Z", "2026-09-12T00:00:00Z")
    except Exception:
        return s, None


with ThreadPoolExecutor(4) as ex:
    frames = {s: f for s, f in ex.map(get, syms) if f is not None}
strat = vol_sized_strategy(core_strategy(ex_cfg["trend_parameters"], exit_window=None), window=180,
                           target_vol=0.15, cap=1.0, bars_per_year=1095)
rets, gross = {}, {}
for s, f in frames.items():
    r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=20.0), return_equity=True)
    rets[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
    held = strat.generate_target(f, {}, None).shift(1).fillna(0.0).abs()
    gross[s] = _daily(held)
R = pd.DataFrame(rets).iloc[1:]
n_active = R.notna().sum(axis=1).replace(0, np.nan)
base = R.mean(axis=1).dropna()
base = base[base.index >= base[base != 0].index[0]]
g = (pd.DataFrame(gross).reindex(base.index).fillna(0.0).sum(axis=1) / n_active.reindex(base.index)).fillna(0.0)
o = cfg["overlay"]
out = vol_target_overlay(base, g, target_annual_vol=o["target_annual_vol"], window_days=o["window_days"],
                         max_leverage=o["max_leverage"], rebalance="W-MON", cost_bps=20.0)
scaled = out["returns"][out["leverage"] > 0]
b = base.loc[scaled.index]
res = {}
for name, x in (("base", b), ("vol_target", scaled)):
    s = summarize(x, nw_lags=5)
    res[name] = {**{k: s[k] for k in ("annualized_sharpe", "newey_west_t", "mean_daily_bps", "max_drawdown", "days")},
                 "annual_return": float(x.mean() * 365), "realized_vol": float(x.std() * np.sqrt(365)),
                 "per_year": {str(y): float((1 + v).prod() - 1) for y, v in x.groupby(x.index.year)}}
L, G = out["leverage"].loc[scaled.index], out["gross_exposure"].loc[scaled.index]
res["overlay"] = {"leverage_p10_p50_p90": [float(v) for v in L.quantile([.1, .5, .9])], "leverage_at_cap_share": float((L >= 3.0 - 1e-9).mean()),
                  "base_gross_mean": float(g.loc[scaled.index].mean()), "scaled_gross_p50_p90_max": [float(G.quantile(.5)), float(G.quantile(.9)), float(G.max())],
                  "share_days_gross_above_1": float((G > 1.0).mean()), "total_cost": out["total_cost"]}
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/portfolio_vol_target_eval.json", "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in res.items() if k != "overlay"} | {"overlay": res["overlay"]}, default=lambda z: round(z, 3), indent=0)[:2500])

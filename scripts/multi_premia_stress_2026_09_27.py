"""Stress tests for the multi-premia blend: costs, crises, tails. Descriptive."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.multi_premia_forward import blend
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy
from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score, run_xs

frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
opens = daily_open_panel(frames)
fp = daily_funding_panel(fund, opens.index)
strat = vol_sized_strategy(core_strategy({"DON8": {"lookback": 55}, "EMA8": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}, exit_window=None),
                           window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)


def legs_at(cost):
    cols = {s: _daily(run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=cost), return_equity=True,
                                                funding=fund[s])["equity_path"].iloc[:-1]).pct_change() for s, f in frames.items()}
    s1 = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
    s2 = run_xs(opens, fp, momentum_score(opens, 30), rebalance_days=7, q=0.25, cost_bps=cost)["returns"]
    s3 = run_xs(opens, fp, carry_score(fp, 7), rebalance_days=7, q=0.25, cost_bps=cost)["returns"]
    s2.index, s3.index = s2.index + pd.Timedelta(days=1), s3.index + pd.Timedelta(days=1)
    legs = pd.concat([s1.rename("S1"), s2.rename("S2"), s3.rename("S3")], axis=1).dropna()
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    legs["S4"] = blend(legs, vol_window=90, min_obs=60)
    return legs.dropna()


out = {"costs": {}}
for c in (20, 40, 60):
    L = legs_at(c)
    out["costs"][c] = {k: round(summarize(L[k], nw_lags=5)["annualized_sharpe"], 3) for k in L}
    if c == 20:
        base = L
basket = opens.pct_change().mean(axis=1).shift(-1)
basket.index = basket.index + pd.Timedelta(days=1)
basket = basket.reindex(base.index)
crises = {"LUNA 2022-05-05..05-20": ("2022-05-05", "2022-05-20"), "FTX 2022-11-06..11-21": ("2022-11-06", "2022-11-21"),
          "COVID-like 2021-05-12..05-24 crash": ("2021-05-12", "2021-05-24")}
out["crises"] = {}
for name, (a, b) in crises.items():
    seg = base.loc[a:b]
    out["crises"][name] = {**{k: round(float((1 + seg[k]).prod() - 1), 4) for k in base}, "basket": round(float((1 + basket.loc[a:b]).prod() - 1), 4)}
wk = (1 + base).resample("W").prod() - 1
bw = (1 + basket).resample("W").prod() - 1
worst = bw.nsmallest(10).index
out["worst10_basket_weeks_mean"] = {**{k: round(float(wk.loc[worst, k].mean()), 4) for k in base}, "basket": round(float(bw.loc[worst].mean()), 4)}
out["worst_day"] = {k: round(float(base[k].min()), 4) for k in base}
out["worst_week"] = {k: round(float(wk[k].min()), 4) for k in base}
out["S3_worst_weeks"] = {str(d.date()): round(float(v), 4) for d, v in wk["S3"].nsmallest(5).items()}
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/mp_stress.json", "w"), indent=1)
print(json.dumps(out, indent=1))

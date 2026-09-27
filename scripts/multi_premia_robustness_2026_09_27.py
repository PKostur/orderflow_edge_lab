"""Robustness of the multi-premia blend to neighbouring parameters (config/multi_premia_robustness_v1.json)."""

from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend
from orderflow_edge_lab.trend_portfolio_forward import summarize
from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score, run_xs

frames, fund = pickle.load(open(os.path.join(os.environ["TEMP"], "multi_premia_data.pkl"), "rb"))
base = json.load(open("research/multi_premia/eval_2026_09_27.json"))
opens = daily_open_panel(frames)
fp = daily_funding_panel(fund, opens.index)
# S1 from the recorded evaluation is re-derived cheaply: rerun the evaluator's S1 is expensive, so rebuild from cache
from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy

strat = vol_sized_strategy(core_strategy({"DON8": {"lookback": 55}, "EMA8": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}, exit_window=None),
                           window=180, target_vol=0.15, cap=1.0, bars_per_year=1095)
cols = {s: _daily(run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=20.0), return_equity=True, funding=fund[s])["equity_path"].iloc[:-1]).pct_change() for s, f in frames.items()}
s1 = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
frozen = {"S2_lookback_days": 30, "S3_lookback_days": 7, "rebalance_days": 7, "quantile": 0.25}
grid = json.load(open("config/multi_premia_robustness_v1.json"))["grid"]
points = [dict(frozen)]
for k, vals in grid.items():
    for v in vals:
        if v != frozen[k]:
            points.append({**frozen, k: v})
rows = []
for p in points:
    s2 = run_xs(opens, fp, momentum_score(opens, p["S2_lookback_days"]), rebalance_days=p["rebalance_days"], q=p["quantile"], cost_bps=20)["returns"]
    s3 = run_xs(opens, fp, carry_score(fp, p["S3_lookback_days"]), rebalance_days=p["rebalance_days"], q=p["quantile"], cost_bps=20)["returns"]
    s2.index, s3.index = s2.index + pd.Timedelta(days=1), s3.index + pd.Timedelta(days=1)
    legs = pd.concat([s1.rename("S1"), s2.rename("S2"), s3.rename("S3")], axis=1).dropna()
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    b = blend(legs, vol_window=90, min_obs=60)
    sb, s1s = summarize(b, nw_lags=5), summarize(legs["S1"].loc[b.index], nw_lags=5)
    rows.append({**p, "blend_sharpe": sb["annualized_sharpe"], "blend_dd": sb["max_drawdown"], "s1_sharpe": s1s["annualized_sharpe"],
                 "s2_sharpe": summarize(legs["S2"], nw_lags=5)["annualized_sharpe"], "s3_sharpe": summarize(legs["S3"], nw_lags=5)["annualized_sharpe"]})
df = pd.DataFrame(rows)
robust = bool(((df["blend_sharpe"] >= 1.5) & (df["blend_sharpe"] >= df["s1_sharpe"])).all())
json.dump({"rows": rows, "robust": robust}, open(sys.argv[1] if len(sys.argv) > 1 else "artifacts/mp_robust.json", "w"), indent=1, default=float)
print(df.round(3).to_string(index=False))
print("robust", robust)

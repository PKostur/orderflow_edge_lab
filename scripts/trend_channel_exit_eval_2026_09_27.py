"""Evaluate the declared channel-exit overlay (config/trend_channel_exit_v1.json). Descriptive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.strategy_tournament import generate_target_position
from orderflow_edge_lab.trend_exits import core_strategy, exit_overlay_target
from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel, FunctionStrategy
from orderflow_edge_lab.vol_sizing import vol_sized_strategy


def single(family, params, exit_window):
    def t(frame, _p):
        if exit_window is None:
            return generate_target_position(frame, family, dict(params)).reindex(frame.index).fillna(0.0)
        return exit_overlay_target(frame, family, params, exit_window)
    return FunctionStrategy(strategy_id=f"{family}_{exit_window}", target_fn=t, warmup_bars=100)


def main(out_path: str) -> None:
    cfg = json.load(open("config/trend_channel_exit_v1.json", encoding="utf-8"))
    syms = json.load(open(cfg["universe"]["symbols_from"], encoding="utf-8"))["groups"]["crypto"]
    start, end = cfg["universe"]["window"]

    def get(s):
        try:
            return s, fetch_mexc_futures_klines(s, "8h", start, end)
        except Exception:
            return s, None
    with ThreadPoolExecutor(4) as ex:
        frames = {s: f for s, f in ex.map(get, syms) if f is not None}
    sz, tp, w = cfg["sizing"], cfg["trend_parameters"], int(cfg["overlay"]["exit_window_bars"])
    execm = ExecutionModel(round_trip_cost_bps=float(cfg["economics"]["round_trip_cost_bps"]))
    variants = {
        "core": core_strategy(tp, exit_window=None), "core_exit": core_strategy(tp, exit_window=w),
        "DON8": single("donchian_breakout", tp["DON8"], None), "DON8_exit": single("donchian_breakout", tp["DON8"], w),
        "EMA8": single("ema_tsmom", tp["EMA8"], None), "EMA8_exit": single("ema_tsmom", tp["EMA8"], w),
    }
    basket = pd.DataFrame({s: _daily(f["open"]) for s, f in frames.items()}).pct_change().mean(axis=1).dropna()
    mret = (1 + basket).resample("ME").prod() - 1
    mdir = pd.qcut(mret, 3, labels=["DOWN", "FLAT", "UP"])
    result = {}
    for name, base in variants.items():
        strat = vol_sized_strategy(base, window=int(sz["window_bars"]), target_vol=float(sz["target_annual_vol"]),
                                   cap=float(sz["cap"]), bars_per_year=int(sz["bars_per_year"]))
        cols, trades, inmkt = {}, [], []
        for s, f in frames.items():
            r = run_canonical_backtest_v3(f, strat, {}, execm, return_equity=True)
            cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
            trades += [t["net_bps"] for t in r["trades_ledger"] if not t["terminal_liquidation"]]
            inmkt.append(r["exposure_fraction"])
        d = pd.DataFrame(cols).iloc[1:].mean(axis=1).dropna()
        d = d[d.index >= d[d != 0].index[0]]
        s = summarize(d, nw_lags=5)
        m = ((1 + d).resample("ME").prod() - 1).reindex(mret.index)
        net = np.sort(np.array(trades))[::-1]
        k = max(1, len(net) // 100)
        result[name] = {**{x: s[x] for x in ("annualized_sharpe", "newey_west_t", "mean_daily_bps", "max_drawdown", "days")},
                        "per_year": {str(y): float((1 + x).prod() - 1) for y, x in d.groupby(d.index.year)},
                        "monthly_by_basket_regime": {str(g): float(v.mean()) for g, v in m.groupby(mdir, observed=True)},
                        "time_in_market": float(np.mean(inmkt)), "trades": int(len(net)),
                        "top1pct_share_of_net": float(net[:k].sum() / net.sum()) if net.sum() else None}
    json.dump(result, open(out_path, "w"), indent=1, default=float)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "artifacts/trend_channel_exit_eval.json")

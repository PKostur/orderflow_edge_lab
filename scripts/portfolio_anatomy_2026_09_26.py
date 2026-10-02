"""Descriptive anatomy of the combined DON8/EMA8/VOL8 v3 portfolio.

Frozen, already-inspected window 2024-01-01..2026-09-12, 20 bps round trip.
Nothing here selects parameters; it locates strengths and weaknesses to decide
where breadth should be added.  Usage:
    python scripts/portfolio_anatomy_2026_09_26.py artifacts/data/8h
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.trend_portfolio_forward import _daily, basket_daily_returns
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy
from orderflow_edge_lab.universal_existing_validation import load_protocol, load_snapshot

ANN = np.sqrt(365.0)


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * ANN) if len(r) > 2 and r.std() > 0 else float("nan")


def drawdown_episodes(r: pd.Series, top: int = 5) -> list[dict]:
    eq = (1 + r.fillna(0)).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1
    out, start = [], None
    for ts, v in dd.items():
        if v < 0 and start is None:
            start = ts
        if v == 0 and start is not None:
            seg = dd.loc[start:ts]
            out.append({"start": str(start.date()), "trough": str(seg.idxmin().date()),
                        "recovered": str(ts.date()), "depth": float(seg.min()),
                        "days": int((ts - start).days)})
            start = None
    if start is not None:
        seg = dd.loc[start:]
        out.append({"start": str(start.date()), "trough": str(seg.idxmin().date()),
                    "recovered": None, "depth": float(seg.min()), "days": int((dd.index[-1] - start).days)})
    return sorted(out, key=lambda e: e["depth"])[:top]


def main(data_dir: str) -> dict:
    protocol = load_protocol("config/universal_existing_strategy_backtests_v1.json")
    frames, _ = load_snapshot(protocol, data_dir)
    symbols = sorted(frames)
    execution = ExecutionModel(round_trip_cost_bps=20.0)
    free = ExecutionModel(round_trip_cost_bps=0.0)
    sleeves, gross_sleeves, pos, trades = {}, {}, {}, []
    for spec in protocol["strategies"]:
        strat = legacy_strategy(spec["family"])
        for s in symbols:
            key = f"{spec['audit_id']}:{s}"
            res = run_canonical_backtest_v3(frames[s], strat, dict(spec["parameters"]), execution, return_equity=True)
            res0 = run_canonical_backtest_v3(frames[s], strat, dict(spec["parameters"]), free, return_equity=True)
            sleeves[key] = _daily(res["equity_path"].iloc[:-1]).pct_change()
            gross_sleeves[key] = _daily(res0["equity_path"].iloc[:-1]).pct_change()
            tgt = strat.generate_target(frames[s], spec["parameters"], None).reindex(frames[s].index).fillna(0).shift(1).fillna(0)
            pos[key] = _daily(tgt)
            for t in res["trades_ledger"]:
                if not t["terminal_liquidation"]:
                    trades.append({"sleeve": key, "strategy": spec["audit_id"], "symbol": s, **t})
    S = pd.DataFrame(sleeves).iloc[1:]
    G = pd.DataFrame(gross_sleeves).iloc[1:]
    P = pd.DataFrame(pos).reindex(S.index)
    port, gross = S.mean(axis=1), G.mean(axis=1)
    basket = basket_daily_returns(frames, symbols).reindex(S.index)
    T = pd.DataFrame(trades)
    out: dict = {}

    out["headline"] = {"net_sharpe": sharpe(port), "gross_sharpe": sharpe(gross),
                       "ann_return_net": float(port.mean() * 365), "ann_vol": float(port.std() * ANN),
                       "cost_drag_ann": float((gross.mean() - port.mean()) * 365),
                       "skew": float(port.skew()), "excess_kurtosis": float(port.kurt()),
                       "basket_sharpe": sharpe(basket)}
    out["by_strategy"] = {a: {"sharpe": sharpe(S[[c for c in S if c.startswith(a)]].mean(axis=1)),
                              "pnl_share": float(S[[c for c in S if c.startswith(a)]].sum(axis=1).sum() / S.sum(axis=1).sum())}
                          for a in ("DON8", "EMA8", "VOL8")}
    coin = {s: S[[c for c in S if c.endswith(":" + s)]].mean(axis=1) for s in symbols}
    total = sum(v.sum() for v in coin.values())
    out["by_coin"] = {s: {"sharpe": sharpe(v), "pnl_share": float(v.sum() / total)} for s, v in sorted(coin.items(), key=lambda kv: -kv[1].sum())}
    yr = port.groupby(port.index.year)
    out["by_year"] = {int(y): {"return": float((1 + r).prod() - 1), "sharpe": sharpe(r), "basket": float((1 + basket.loc[r.index]).prod() - 1)} for y, r in yr}
    # long/short attribution: split each sleeve's daily return by its position sign that day
    long_part = (S.where(P > 0, 0.0)).mean(axis=1)
    short_part = (S.where(P < 0, 0.0)).mean(axis=1)
    out["long_short"] = {"long_ann_return": float(long_part.mean() * 365), "short_ann_return": float(short_part.mean() * 365),
                         "long_sharpe": sharpe(long_part), "short_sharpe": sharpe(short_part),
                         "avg_net_exposure": float(P.mean(axis=1).mean()), "avg_gross_exposure": float(P.abs().mean(axis=1).mean()),
                         "pct_days_net_long": float((P.mean(axis=1) > 0).mean())}
    # payoff vs market: trend convexity across basket-return months
    m = pd.DataFrame({"p": (1 + port).resample("ME").prod() - 1, "b": (1 + basket).resample("ME").prod() - 1})
    q = pd.qcut(m["b"], 5, labels=["worst", "q2", "q3", "q4", "best"])
    out["convexity_by_basket_month_quintile"] = {str(k): float(v) for k, v in m.groupby(q, observed=True)["p"].mean().items()}
    out["monthly"] = {"hit_rate": float((m["p"] > 0).mean()), "best": float(m["p"].max()), "worst": float(m["p"].min()),
                      "corr_to_basket": float(m.corr().iloc[0, 1])}
    out["drawdowns"] = drawdown_episodes(port)
    # concentration: how much of total P&L comes from the best trades
    net = T["net_bps"].sort_values(ascending=False)
    out["concentration"] = {"trades": int(len(net)), "top_1pct_share_of_net": float(net.head(max(1, len(net) // 100)).sum() / net.sum()),
                            "top_5pct_share_of_net": float(net.head(max(1, len(net) // 20)).sum() / net.sum()),
                            "net_without_top_5pct_bps": float(net.iloc[max(1, len(net) // 20):].sum())}
    daily = port.sort_values()
    out["tails"] = {"worst_5_days": {str(k.date()): float(v) for k, v in daily.head(5).items()},
                    "best_5_days": {str(k.date()): float(v) for k, v in daily.tail(5).items()}}
    # diversification under stress: sleeve correlation on the worst basket decile days vs all days
    stress = basket <= basket.quantile(0.1)
    def mean_corr(df):
        c = df.corr().to_numpy(); n = c.shape[0]
        return float((np.nansum(c) - n) / (n * (n - 1)))
    out["sleeve_corr"] = {"all_days": mean_corr(S), "worst_basket_decile_days": mean_corr(S.loc[stress])}
    out["turnover"] = {a: {"trades_per_year": float((T["strategy"] == a).sum() / (len(S) / 365)),
                           "cost_drag_ann": float((G[[c for c in G if c.startswith(a)]].mean(axis=1).mean() - S[[c for c in S if c.startswith(a)]].mean(axis=1).mean()) * 365)}
                       for a in ("DON8", "EMA8", "VOL8")}
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1] if len(sys.argv) > 1 else "artifacts/data/8h"), indent=1, default=float))

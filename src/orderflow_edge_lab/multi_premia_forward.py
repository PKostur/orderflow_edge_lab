"""Forward watch: equal-risk blend of trend core, cross-sectional momentum and funding carry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _daily, _utc, completed_bars, summarize
from orderflow_edge_lab.universal_backtest import ExecutionModel
from orderflow_edge_lab.vol_sizing import vol_sized_strategy
from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score, run_xs

WATCH_ID = "multi-premia-blend-v1"


def leg_returns(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                funding: Mapping[str, pd.Series]) -> pd.DataFrame:
    c = config["legs"]
    tr = c["S1_trend"]
    strat = vol_sized_strategy(core_strategy(tr["parameters"], exit_window=None), window=int(tr["sizing_window_bars"]),
                               target_vol=float(tr["target_annual_vol"]), cap=1.0, bars_per_year=1095)
    cost = float(config["economics"]["round_trip_cost_bps"])
    cols = {}
    for s, f in frames.items():
        if len(f) < 250:
            continue
        r = run_canonical_backtest_v3(f, strat, {}, ExecutionModel(round_trip_cost_bps=cost), return_equity=True,
                                      funding=funding.get(s))
        cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
    s1 = pd.DataFrame(cols).iloc[1:].mean(axis=1)
    opens = daily_open_panel(frames)
    fp = daily_funding_panel(funding, opens.index)
    m, k = c["S2_xs_momentum"], c["S3_xs_carry"]
    s2 = run_xs(opens, fp, momentum_score(opens, int(m["lookback_days"])), rebalance_days=int(m["rebalance_days"]),
                q=float(m["quantile"]), cost_bps=cost)["returns"]
    s3 = run_xs(opens, fp, carry_score(fp, int(k["lookback_days"])), rebalance_days=int(k["rebalance_days"]),
                q=float(k["quantile"]), cost_bps=cost)["returns"]
    s2.index = s2.index + pd.Timedelta(days=1)
    s3.index = s3.index + pd.Timedelta(days=1)
    return pd.concat([s1.rename("S1"), s2.rename("S2"), s3.rename("S3")], axis=1).dropna()


def blend(legs: pd.DataFrame, *, vol_window: int, min_obs: int) -> pd.Series:
    vol = legs.rolling(vol_window, min_periods=min_obs).std().shift(1)
    inv = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
    w = inv.div(inv.sum(axis=1), axis=0)
    w.loc[w.index.dayofweek != 0] = np.nan
    w = w.ffill()
    return (w * legs).sum(axis=1).where(w.notna().all(axis=1)).dropna()


def build_report(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series],
                 *, as_of: Any) -> dict[str, Any]:
    if config.get("watch_id") != WATCH_ID:
        raise ValueError("wrong watch config")
    as_of_ts, start = _utc(as_of), _utc(config["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    legs = leg_returns(config, clean, funding)
    b = config["blend"]
    legs["S4_blend"] = blend(legs, vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    mask = (legs.index - pd.Timedelta(days=1)) >= start
    fwd = legs.loc[mask]
    days = int(fwd["S1"].notna().sum()) if len(fwd) else 0
    return {
        "schema_version": 1, "watch_id": WATCH_ID,
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(),
        "coins_with_data": int(len(clean)),
        "forward": {k: summarize(fwd[k].dropna(), nw_lags=5) for k in legs.columns},
        "daily_returns": {k: {t.isoformat(): float(v) for t, v in fwd[k].dropna().items()} for k in legs.columns},
        "review_window_open": days >= int(config["reporting"]["review_after_days"]),
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Run the multi-premia blend forward watch.")
    p.add_argument("--config", default="config/multi_premia_blend_v1.json")
    p.add_argument("--output", required=True)
    p.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    as_of = _utc(a.as_of) if a.as_of else pd.Timestamp.now(tz="UTC")
    warm = config["source"]["warmup_start_utc"]

    def load(s):
        try:
            return (s, fetch_mexc_futures_klines(s, "8h", warm, as_of.isoformat()),
                    fetch_mexc_funding_history(s, warm, as_of.isoformat())["funding_rate"])
        except Exception:
            return s, None, None

    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, config["symbols"]))
    frames = {s: f for s, f, _ in got if f is not None}
    funding = {s: fu for s, f, fu in got if f is not None}
    report = build_report(config, frames, funding, as_of=as_of)
    report["missing_symbols"] = sorted(s for s, f, _ in got if f is None)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "coins": report["coins_with_data"], "missing": report["missing_symbols"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Forward watch: multi-premia blend held by a human (top-K coins, daily 08:00 UTC check-in).

Rules are exactly multi-premia-human-v1 (research/multi_premia_human/RESULT.md): net per-coin blend
weight decided at 00:00 UTC, traded at the 08:00 UTC open, only the K largest |weights| held, gross
rescaled to the full-universe gross capped at 1x. Legs and parameters come from the frozen
multi-premia-blend-v1 config; nothing here is tuned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import leg_returns
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars, summarize
from orderflow_edge_lab.vol_sizing import vol_sized_strategy
from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score, quantile_weights

WATCH_ID = "multi-premia-human-v1-forward"
LAG = pd.Timedelta(hours=8)


def leg_weights(legs: pd.DataFrame, *, vol_window: int, min_obs: int) -> pd.DataFrame:
    """Monday inverse-vol leg weights, same rule as multi_premia_forward.blend."""
    vol = legs.rolling(vol_window, min_periods=min_obs).std().shift(1)
    inv = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
    w = inv.div(inv.sum(axis=1), axis=0)
    w.loc[w.index.dayofweek != 0] = np.nan
    return w.ffill().dropna()


def _xs_weights(opens: pd.DataFrame, score: pd.DataFrame, days: pd.DatetimeIndex, *, rebalance_days: int,
                q: float) -> pd.DataFrame:
    ret = opens.shift(-1) / opens - 1.0
    out, w = {}, pd.Series(0.0, index=opens.columns)
    for i, d in enumerate(opens.index[:-1]):
        if i % rebalance_days == 0:
            sc = score.loc[d].where(opens.loc[d].notna() & ret.loc[d].notna())
            w = quantile_weights(sc, q) if sc.notna().sum() >= 8 else pd.Series(0.0, index=opens.columns)
        out[d] = w
    return pd.DataFrame(out).T.reindex(days).fillna(0.0)


def coin_targets(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series],
                 lw: pd.DataFrame) -> pd.DataFrame:
    """Net per-coin blend weight decided at 00:00 UTC of each day in ``lw``."""
    c = config["legs"]
    tr = c["S1_trend"]
    strat = vol_sized_strategy(core_strategy(tr["parameters"], exit_window=None), window=int(tr["sizing_window_bars"]),
                               target_vol=float(tr["target_annual_vol"]), cap=1.0, bars_per_year=1095)
    frames = {s: f for s, f in frames.items() if len(f) >= 250}
    days = lw.index
    opens = daily_open_panel(frames)
    tpanel = pd.DataFrame({s: strat.generate_target(f, {}, None) for s, f in frames.items()}).sort_index()
    t_at = tpanel.reindex(days - LAG)
    t_at.index = days
    has = opens.reindex(days).notna()
    w1 = t_at.where(has).fillna(0.0).div(has.sum(axis=1).clip(lower=1), axis=0)
    fp = daily_funding_panel(funding, opens.index)
    m, k = c["S2_xs_momentum"], c["S3_xs_carry"]
    w2 = _xs_weights(opens, momentum_score(opens, int(m["lookback_days"])), days,
                     rebalance_days=int(m["rebalance_days"]), q=float(m["quantile"]))
    w3 = _xs_weights(opens, carry_score(fp, int(k["lookback_days"])), days,
                     rebalance_days=int(k["rebalance_days"]), q=float(k["quantile"]))
    return w1.mul(lw["S1"], axis=0) + w2.mul(lw["S2"], axis=0) + w3.mul(lw["S3"], axis=0)


def truncate(a: pd.Series, k: int | None) -> pd.Series:
    if k is None:
        return a
    g = float(a.abs().sum())
    keep = a.abs().nlargest(k).index
    out = pd.Series(0.0, index=a.index)
    out[keep] = a[keep]
    gk = float(out.abs().sum())
    return out * (min(g, 1.0) / gk) if gk > 0 else out


def simulate(agg: pd.DataFrame, frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series], k: int | None,
             cost_bps: float) -> tuple[pd.Series, pd.DataFrame]:
    """Daily net returns stamped at d+1 (08:00 UTC open of d to 08:00 UTC open of d+1) and the held targets."""
    days, syms = agg.index, list(agg.columns)
    o8 = pd.DataFrame({s: frames[s]["open"].astype(float) for s in syms}).sort_index()
    px = o8.reindex(days + LAG)
    px.index = days
    ret = px.shift(-1) / px - 1.0
    fset = {}
    for s in syms:
        f = funding.get(s)
        if f is None or len(f) == 0:
            fset[s] = pd.Series(0.0, index=days)
            continue
        day = (f.index - LAG - pd.Timedelta(microseconds=1)).floor("D")
        fset[s] = f.groupby(day).sum().reindex(days).fillna(0.0)
    fpan = pd.DataFrame(fset).reindex(columns=syms).fillna(0.0)
    held = pd.Series(0.0, index=syms)
    rows, book = {}, {}
    for d in days[:-1]:
        r = ret.loc[d]
        if not r.notna().any():
            continue
        target = truncate(agg.loc[d].where(r.notna(), 0.0), k)
        turn = float((target - held).abs().sum())
        rr = r.fillna(0.0)
        rows[d + pd.Timedelta(days=1)] = float((target * rr).sum() - (target * fpan.loc[d]).sum() - turn * cost_bps / 2 / 1e4)
        book[d] = target[target != 0]
        held = target * (1.0 + rr)
    return pd.Series(rows, dtype=float), pd.DataFrame(book).T


def build_report(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series],
                 *, as_of: Any) -> dict[str, Any]:
    if config.get("watch_id") != "multi-premia-blend-v1":
        raise ValueError("expects the frozen multi-premia-blend-v1 config")
    as_of_ts, start = _utc(as_of), _utc(config["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    legs = leg_returns(config, clean, funding)
    b = config["blend"]
    lw = leg_weights(legs, vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    agg = coin_targets(config, clean, funding, lw)
    cost = float(config["economics"]["round_trip_cost_bps"])
    books, fwd, latest = {}, {}, {}
    for name, k in (("V_ALL", None), ("H5", 5), ("H10", 10)):
        x, held = simulate(agg, clean, funding, k, cost)
        books[name] = x[(x.index - pd.Timedelta(days=1)) >= start]
        if len(held):
            last = held.iloc[-1].dropna()
            latest[name] = {"decided_utc": held.index[-1].isoformat(), "weights": {s: float(v) for s, v in last.items()}}
    days = int(len(books["H5"]))
    return {
        "schema_version": 1, "watch_id": WATCH_ID, "protocol": "multi-premia-human-v1",
        "status": "PRE_START" if days == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(),
        "coins_with_data": int(len(clean)),
        "forward": {k: summarize(v, nw_lags=5) for k, v in books.items()},
        "daily_returns": {k: {t.isoformat(): float(v) for t, v in s.items()} for k, s in books.items()},
        "latest_book": latest,
        "review_window_open": days >= int(config["reporting"]["review_after_days"]),
        "claims": dict(config["claims"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Run the human-constrained multi-premia forward watch.")
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

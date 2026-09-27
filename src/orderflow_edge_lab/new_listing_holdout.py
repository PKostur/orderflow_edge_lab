"""Quarterly new-listing holdout for the crypto trend core.

Batch k contains MEXC USDT crypto perps first listed in quarter k after the
freeze (2026-09-12 + 3k months .. + 3(k+1) months).  A batch is evaluated once,
after a full further quarter of history, with the frozen core design.
Selection uses only contract metadata and turnover.  Batches are defined by
listing date, so reruns reproduce the same membership (up to delistings,
which are reported).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

EXCLUDE_ZONES = re.compile("tradfi|Stock|stockindex|Forex|Commodities|metals")


def batch_window(freeze: str, k: int) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """(listed_from, listed_until, evaluate_after)."""
    f = pd.Timestamp(freeze).tz_convert("UTC") if pd.Timestamp(freeze).tzinfo else pd.Timestamp(freeze, tz="UTC")
    a = f + pd.DateOffset(months=3 * k)
    b = f + pd.DateOffset(months=3 * (k + 1))
    return a, b, b + pd.DateOffset(months=3)


def select_batch(detail: Mapping[str, Mapping[str, Any]], turnover: Mapping[str, float], *, listed_from: pd.Timestamp,
                 listed_until: pd.Timestamp, min_turnover: float, exclude: set[str]) -> list[str]:
    out = []
    for s, d in detail.items():
        if d.get("quoteCoin") != "USDT" or s in exclude or int(d.get("state", 1)) != 0:
            continue
        if EXCLUDE_ZONES.search(" ".join(d.get("conceptPlate") or [])):
            continue
        listed = pd.Timestamp(int(d.get("openingTime") or d.get("createTime") or 0), unit="ms", tz="UTC")
        if listed_from <= listed < listed_until and float(turnover.get(s, 0.0)) >= min_turnover:
            out.append(s)
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import urllib.request

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
    from orderflow_edge_lab.trend_exits import core_strategy
    from orderflow_edge_lab.trend_portfolio_forward import _daily, summarize
    from orderflow_edge_lab.universal_backtest import ExecutionModel
    from orderflow_edge_lab.vol_sizing import vol_sized_strategy

    p = argparse.ArgumentParser(description="Evaluate every due, not-yet-reported new-listing batch.")
    p.add_argument("--config", default="config/new_listing_holdout_v1.json")
    p.add_argument("--output-dir", default="artifacts/new_listing_holdout")
    p.add_argument("--now", default=None)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    now = pd.Timestamp(a.now, tz="UTC") if a.now else pd.Timestamp.now(tz="UTC")

    def get(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)["data"]

    detail = {x["symbol"]: x for x in get("https://contract.mexc.com/api/v1/contract/detail")}
    turnover = {x["symbol"]: float(x.get("amount24", 0)) for x in get("https://contract.mexc.com/api/v1/contract/ticker")}
    exclude = set(cfg["exclude_symbols"])
    out_dir = Path(a.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    core = core_strategy({x["audit_id"]: x["parameters"] for x in cfg["strategies"]}, exit_window=None)
    sz = cfg["sizing"]
    sized = vol_sized_strategy(core, window=int(sz["window_bars"]), target_vol=float(sz["target_annual_vol"]),
                               cap=float(sz["cap"]), bars_per_year=int(sz["bars_per_year"]))
    reports = []
    k = 0
    while True:
        lf, lu, ev = batch_window(cfg["freeze_utc"], k)
        if ev > now:
            break
        members = select_batch(detail, turnover, listed_from=lf, listed_until=lu,
                               min_turnover=float(cfg["min_24h_turnover_usdt"]), exclude=exclude)
        cols = {}
        for s in members:
            try:
                f = fetch_mexc_futures_klines(s, "8h", lf.isoformat(), ev.isoformat())
                fund = fetch_mexc_funding_history(s, lf.isoformat(), ev.isoformat())["funding_rate"]
                r = run_canonical_backtest_v3(f, sized, {}, ExecutionModel(round_trip_cost_bps=20.0),
                                              return_equity=True, funding=fund)
                cols[s] = _daily(r["equity_path"].iloc[:-1]).pct_change()
            except Exception as exc:  # delisted or too short: reported, not silently dropped
                cols[s] = None
                print(f"{s}: skipped ({str(exc)[:60]})")
        used = {s: c for s, c in cols.items() if c is not None}
        d = pd.DataFrame(used).iloc[1:].mean(axis=1).dropna() if used else pd.Series(dtype=float)
        rep = {"batch": k, "listed_from": lf.isoformat(), "listed_until": lu.isoformat(), "evaluated_until": ev.isoformat(),
               "members": members, "skipped": sorted(s for s, c in cols.items() if c is None),
               "summary": summarize(d, nw_lags=5) if len(d) else None,
               "daily_returns": {t.isoformat(): float(v) for t, v in d.items()}}
        (out_dir / f"batch_{k:02d}.json").write_text(json.dumps(rep, indent=2, default=float), encoding="utf-8")
        reports.append(rep)
        k += 1
    pooled = pd.concat([pd.Series(r["daily_returns"]) for r in reports if r["daily_returns"]]) if reports else pd.Series(dtype=float)
    summary = {"batches_due": len(reports), "pooled_days": int(len(pooled)),
               "pooled": summarize(pooled.astype(float), nw_lags=5) if len(pooled) else None,
               "primary_rule": cfg["primary_rule"], "claims": cfg["claims"]}
    (out_dir / "pooled.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(json.dumps({"batches_due": len(reports), "pooled_days": int(len(pooled))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

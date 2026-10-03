"""Paper account for the 70-coin blend (config/paper_account_blend_v1.json). Paper only: no keys, no orders.

The ledger is replayed deterministically from the start date on every run, so no state has to be stored.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.multi_premia_forward import leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights
from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars, summarize

WATCH_ID = "paper-account-blend-v1"
LAG = pd.Timedelta(hours=8)


def contracts_for(target_w: float, equity: float, price: float, spec: Mapping[str, Any]) -> int:
    if not (price > 0) or not math.isfinite(target_w) or target_w == 0:
        return 0
    n = int(round(target_w * equity / (price * float(spec["contractSize"]))))
    return 0 if abs(n) < int(spec.get("minVol", 1)) else n


def replay(targets: pd.DataFrame, open8: pd.DataFrame, funding: Mapping[str, pd.Series], specs: Mapping[str, Mapping[str, Any]],
           *, start: pd.Timestamp, initial: float, slippage: float = 0.0005, min_fee: float = 0.0002) -> dict[str, Any]:
    """targets: per-coin weights decided at 00:00 UTC of each day; fills at that day's 08:00 open."""
    days = [d for d in targets.index if d >= start and (d + LAG) in open8.index]
    equity, qty = initial, {s: 0 for s in targets.columns}
    curve, trades_last, totals = [], [], {"fees": 0.0, "funding": 0.0, "traded_notional": 0.0}
    for n, d in enumerate(days):
        t = d + LAG
        px = open8.loc[t]
        # mark the positions held since the previous fill to this fill
        if n > 0:
            prev = days[n - 1] + LAG
            pnl = sum(q * float(specs[s]["contractSize"]) * (float(px[s]) - float(open8.loc[prev, s]))
                      for s, q in qty.items() if q and pd.notna(px.get(s)) and pd.notna(open8.loc[prev, s]))
            fund = 0.0
            for s, q in qty.items():
                f = funding.get(s)
                if q and f is not None and len(f):
                    window = f[(f.index > prev) & (f.index <= t)]
                    fund -= q * float(specs[s]["contractSize"]) * float(open8.loc[prev, s]) * float(window.sum())
            equity += pnl + fund
            totals["funding"] += fund
            curve.append({"date": t.isoformat(), "equity": equity})
        trades_last = []
        for s in targets.columns:
            p = px.get(s)
            if s not in specs or pd.isna(p):
                continue
            want = contracts_for(float(targets.at[d, s]), equity, float(p), specs[s])
            delta = want - qty[s]
            if delta:
                notional = abs(delta) * float(specs[s]["contractSize"]) * float(p)
                fee = notional * (max(float(specs[s].get("takerFeeRate", 0.0)), min_fee) + slippage)
                equity -= fee
                totals["fees"] += fee
                totals["traded_notional"] += notional
                trades_last.append({"symbol": s, "contracts": delta, "price": float(p), "notional": round(notional, 2)})
                qty[s] = want
    last_px = open8.loc[days[-1] + LAG] if days else pd.Series(dtype=float)
    positions = [{"symbol": s, "contracts": q, "notional": round(q * float(specs[s]["contractSize"]) * float(last_px[s]), 2)}
                 for s, q in qty.items() if q]
    return {"days": len(days), "equity": equity, "curve": curve, "positions": sorted(positions, key=lambda x: -abs(x["notional"])),
            "last_trades": trades_last, "totals": {k: round(v, 2) for k, v in totals.items()},
            "gross_exposure": round(sum(abs(p["notional"]) for p in positions), 2)}


def build_report(cfg: Mapping[str, Any], blend_cfg: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                 funding: Mapping[str, pd.Series], specs: Mapping[str, Mapping[str, Any]], *, as_of: Any) -> dict[str, Any]:
    as_of_ts, start = _utc(as_of), _utc(cfg["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    clean = {s: f for s, f in clean.items() if len(f) >= 250}
    legs = leg_returns(blend_cfg, clean, funding)
    b = blend_cfg["blend"]
    lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    agg = coin_targets(blend_cfg, clean, funding, lw)
    open8 = pd.DataFrame({s: f["open"].astype(float) for s, f in clean.items()}).sort_index()
    led = replay(agg, open8, funding, specs, start=start, initial=float(cfg["account"]["initial_equity"]))
    eq = pd.Series({pd.Timestamp(c["date"]): c["equity"] for c in led["curve"]}, dtype=float)
    rets = eq.pct_change().dropna() if len(eq) else pd.Series(dtype=float)
    if len(eq):
        rets = pd.concat([pd.Series({eq.index[0]: eq.iloc[0] / float(cfg["account"]["initial_equity"]) - 1.0}), rets])
    return {"schema_version": 1, "watch_id": WATCH_ID, "status": "PRE_START" if not led["days"] else "COLLECTING",
            "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(), "coins_with_data": len(clean),
            "account": {"initial_equity": cfg["account"]["initial_equity"], "equity": round(led["equity"], 2),
                        "return_pct": round(100 * (led["equity"] / float(cfg["account"]["initial_equity"]) - 1.0), 3),
                        "gross_exposure": led["gross_exposure"], "positions": led["positions"], "last_trades": led["last_trades"],
                        "totals": led["totals"]},
            "forward": {"paper": summarize(rets, nw_lags=5)},
            "daily_returns": {"paper": {t.isoformat(): float(v) for t, v in rets.items()}},
            "spec_snapshot": {s: {k: specs[s].get(k) for k in ("contractSize", "minVol", "takerFeeRate")} for s in sorted(specs)},
            "claims": dict(cfg["claims"])}


def fetch_specs() -> dict[str, dict[str, Any]]:
    import urllib.request
    with urllib.request.urlopen("https://contract.mexc.com/api/v1/contract/detail", timeout=30) as r:
        data = json.load(r)["data"]
    return {c["symbol"]: c for c in data}


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Replay the paper account (paper-account-blend-v1). Paper only.")
    p.add_argument("--config", default="config/paper_account_blend_v1.json")
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    bcfg = json.loads(Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))
    as_of = pd.Timestamp.now(tz="UTC")
    warm = bcfg["source"]["warmup_start_utc"]

    def load(s):
        try:
            return (s, fetch_mexc_futures_klines(s, "8h", warm, as_of.isoformat()),
                    fetch_mexc_funding_history(s, warm, as_of.isoformat())["funding_rate"])
        except Exception:
            return s, None, None

    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, bcfg["symbols"]))
    frames = {s: f for s, f, _ in got if f is not None}
    funding = {s: fu for s, f, fu in got if f is not None}
    specs = {s: v for s, v in fetch_specs().items() if s in frames}
    report = build_report(cfg, bcfg, frames, funding, specs, as_of=as_of)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "equity": report["account"]["equity"], "positions": len(report["account"]["positions"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

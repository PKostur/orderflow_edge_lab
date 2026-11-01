"""carry-forward-v1 (config/carry_forward_v1.json): paper delta-neutral BTC/ETH funding carry on MEXC, from 2026-10-24.

Replays from the start on every run using MEXC's public spot klines, perpetual klines and funding prints, so every
number can be checked against the exchange.  Descriptive paper only; sends no orders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.carry import Costs, daily_close, daily_funding, hedge_daily
from orderflow_edge_lab.trend_portfolio_forward import summarize

WATCH_ID = "carry-forward-v1"


def _utc(x: Any) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def build_report(config: Mapping[str, Any], inputs: Mapping[str, tuple[pd.Series, pd.Series, pd.Series]], *,
                 as_of: Any) -> dict[str, Any]:
    """``inputs``: asset -> (daily spot close, daily perp close, daily funding), all indexed by 00:00 UTC."""
    if config.get("watch_id") != WATCH_ID:
        raise ValueError("wrong watch config")
    start, as_of_ts = _utc(config["prospective_start_utc"]), _utc(as_of)
    c = config["costs"]
    costs = Costs(c["spot_taker_bps"], c["perp_taker_bps"], c["slippage_bps_per_leg"])
    capital = float(config["paper_capital_usdt"])
    per_asset_capital = capital / len(config["assets"])
    notional = per_asset_capital / 2.0
    assets: dict[str, Any] = {}
    daily: dict[str, pd.Series] = {}
    for sym in config["assets"]:
        if sym not in inputs:
            assets[sym] = {"status": "MISSING_DATA"}
            continue
        spot, perp, fund = (s[(s.index >= start) & (s.index <= as_of_ts)] for s in inputs[sym])
        if len(spot.index.intersection(perp.index)) < 2:
            assets[sym] = {"status": "PRE_START"}
            continue
        h = hedge_daily(spot, perp, fund, costs=costs, exit_at_end=False)   # still open; exit shown separately
        held = h[h["active"]]
        usd = held[["basis", "funding", "cost", "net"]] * notional
        daily[sym] = (held["net"] * notional / per_asset_capital).rename(sym)
        days = int(len(held))
        net_usd = float(usd["net"].sum())
        assets[sym] = {
            "status": "COLLECTING", "days": days, "notional_usdt": notional,
            "funding_usdt": float(usd["funding"].sum()), "basis_usdt": float(usd["basis"].sum()),
            "costs_usdt": float(usd["cost"].sum()), "net_usdt": net_usd,
            "net_after_exit_usdt": net_usd - notional * costs.pair_bps / 1e4,
            "funding_prints_days": {t.isoformat(): float(v) for t, v in held["funding"].items()},
        }
    port = pd.concat(daily, axis=1).fillna(0.0).sum(axis=1) if daily else pd.Series(dtype=float)
    total = sum(a.get("net_usdt", 0.0) for a in assets.values())
    total_exit = sum(a.get("net_after_exit_usdt", 0.0) for a in assets.values())
    n = int(len(port))
    return {
        "schema_version": 1, "watch_id": WATCH_ID, "status": "PRE_START" if n == 0 else "COLLECTING",
        "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(),
        "paper_capital_usdt": capital, "assets": assets,
        "portfolio": {"days": n, "net_usdt": total, "net_after_exit_usdt": total_exit,
                      "return_on_capital": total / capital, "return_on_capital_after_exit": total_exit / capital,
                      "annualized_run_rate": ((1 + total / capital) ** (365.0 / n) - 1) if n >= 7 else None},
        "forward": {"portfolio": summarize(port, nw_lags=5)},
        "review_window_open": n >= int(config["reporting"]["review_after_days"]),
        "daily_returns": {"portfolio": {t.isoformat(): float(v) for t, v in port.items()}},
        "claims": dict(config["claims"]),
    }


def load_mexc(sym: str, start: pd.Timestamp, as_of: pd.Timestamp) -> tuple[pd.Series, pd.Series, pd.Series]:
    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history, fetch_mexc_spot_klines
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    warm = (start - pd.Timedelta(days=30)).isoformat()
    one_h = pd.Timedelta(hours=1)
    s = fetch_mexc_spot_klines(sym, warm, as_of.isoformat(), interval="60m")
    p = fetch_mexc_futures_klines(sym.replace("USDT", "_USDT"), "1h", warm, as_of.isoformat())
    s.index, p.index = s.index + one_h, p.index + one_h          # MEXC stamps bar open; daily_close wants bar end
    f = fetch_mexc_funding_history(sym, warm, as_of.isoformat())["funding_rate"]
    return daily_close(s), daily_close(p), daily_funding(f)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config/carry_forward_v1.json")
    p.add_argument("--output", required=True)
    p.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    as_of = _utc(a.as_of) if a.as_of else pd.Timestamp.now(tz="UTC").floor("h")
    start = _utc(config["prospective_start_utc"])
    inputs, missing = {}, {}
    if as_of > start:
        for sym in config["assets"]:
            try:
                inputs[sym] = load_mexc(sym, start, as_of)
            except Exception as exc:
                missing[sym] = repr(exc)[:300]
    report = build_report(config, inputs, as_of=as_of)
    report["missing_symbols"] = sorted(missing)
    report["fetch_errors"] = missing
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "days": report["portfolio"]["days"],
                      "net_usdt": round(report["portfolio"]["net_usdt"], 2), "missing": report["missing_symbols"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

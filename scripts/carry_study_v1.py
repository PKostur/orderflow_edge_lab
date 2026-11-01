"""carry-study-v1 (config/carry_study_v1.json): historical delta-neutral funding carry on BTC and ETH, after fees.

Runs on a GitHub-hosted runner (carry-study-v1.yml).  Binance data from data.binance.vision, MEXC from its public API.
Writes one JSON result; descriptive only, sends no orders.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from orderflow_edge_lab.carry import Costs, daily_close, daily_funding, funding_filter, hedge_daily, summarize

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config/carry_study_v1.json").read_text(encoding="utf-8"))


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def binance_inputs(sym: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    from orderflow_edge_lab.binance_futures_archive import load_dataset

    start, end = CFG["venues"]["binance"]["window"]
    spot = daily_close(load_dataset("spot", sym, start=start, end=end))
    perp = daily_close(load_dataset("perp", sym, start=start, end=end))
    fr = load_dataset("funding", sym, start=start, end=end)
    return spot, perp, daily_funding(fr["rate"])


def mexc_inputs(sym: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history, fetch_mexc_spot_klines
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    start, end = CFG["venues"]["mexc"]["window"]
    one_h = pd.Timedelta(hours=1)
    s = fetch_mexc_spot_klines(sym, start, end, interval="60m")
    p = fetch_mexc_futures_klines(sym.replace("USDT", "_USDT"), "1h", start, end)
    s.index, p.index = s.index + one_h, p.index + one_h          # MEXC stamps bar open; carry.daily_close wants bar end
    f = fetch_mexc_funding_history(sym, start, end)["funding_rate"]
    return daily_close(s), daily_close(p), daily_funding(f)


def run_venue(load) -> dict[str, Any]:
    c = CFG["costs"]
    costs = Costs(c["spot_taker_bps"], c["perp_taker_bps"], c["slippage_bps_per_leg"])
    out: dict[str, Any] = {}
    nets: dict[str, dict[str, pd.Series]] = {"always_on": {}, "funding_filter_7d": {}}
    funds = {}
    for sym in CFG["assets"]:
        try:
            spot, perp, fund = load(sym)
        except Exception:
            out[sym] = {"error": traceback.format_exc()[-1500:]}
            continue
        funds[sym] = fund
        base = hedge_daily(spot, perp, fund, costs=costs)
        filt = hedge_daily(spot, perp, fund, costs=costs, active=funding_filter(fund, 7))
        nets["always_on"][sym], nets["funding_filter_7d"][sym] = base["net"], filt["net"]
        out[sym] = {"inputs": {"spot_days": len(spot), "perp_days": len(perp), "funding_days": len(fund),
                               "first": str(spot.index.min().date()), "last": str(spot.index.max().date())},
                    "always_on": {**summarize(base["net"], fund),
                                  "funding_part": float(base["funding"].sum()), "basis_part": float(base["basis"].sum()),
                                  "cost_part": float(-base["cost"].sum())},
                    "funding_filter_7d": {**summarize(filt["net"], fund), "days_active": int(filt["active"].sum())}}
    for variant, d in nets.items():
        if len(d) == len(CFG["assets"]):
            port = pd.concat(d, axis=1).dropna().mean(axis=1)
            fund_avg = pd.concat(funds, axis=1).reindex(port.index).mean(axis=1)
            s = summarize(port, fund_avg)
            half, uni = summarize(port / 2.0), summarize(port / 1.1)   # daily return on capital, compounded
            s["on_capital_50_50"] = {k: half.get(k) for k in ("annual_return", "max_drawdown", "per_year")}
            s["on_capital_unified"] = {k: uni.get(k) for k in ("annual_return", "max_drawdown")}
            out.setdefault("portfolio_btc_eth", {})[variant] = s
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args(argv)
    res: dict[str, Any] = {"study_id": CFG["study_id"], "run_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                           "costs": CFG["costs"], "descriptive_only": True}
    for venue, loader in (("binance", binance_inputs), ("mexc", mexc_inputs)):
        try:
            res[venue] = run_venue(loader)
        except Exception:
            res[venue] = {"error": traceback.format_exc()[-2000:]}
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(_clean(res), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[carry] {venue} done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

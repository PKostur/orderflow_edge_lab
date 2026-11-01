"""carry-rotation-v1 (config/carry_rotation_v1.json): run once on a GitHub-hosted runner. Descriptive only."""

from __future__ import annotations

import argparse
import json
import math
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from orderflow_edge_lab.carry import Costs, daily_close, daily_funding, hedge_daily, summarize
from orderflow_edge_lab.carry_rotation import pick_stats, rotation_book

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config/carry_rotation_v1.json").read_text(encoding="utf-8"))


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def load(sym: str):
    from orderflow_edge_lab.binance_futures_archive import load_dataset

    start, end = CFG["window"]
    warm = (pd.Timestamp(start) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    try:
        s = daily_close(load_dataset("spot", sym, start=warm, end=end))
        p = daily_close(load_dataset("perp", sym, start=warm, end=end))
        f = daily_funding(load_dataset("funding", sym, start=warm, end=end)["rate"])
        return sym, s, p, f, None
    except Exception:
        return sym, None, None, None, traceback.format_exc()[-800:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args(argv)
    c = CFG["costs"]
    costs = Costs(c["spot_taker_bps"], c["perp_taker_bps"], c["slippage_bps_per_leg"])
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(load, CFG["universe"]["symbols"]))
    errors = {s: e for s, _, _, _, e in got if e}
    ok = [(s, sp, pp, f) for s, sp, pp, f, e in got if not e and sp is not None and len(sp) and len(pp)]
    spot = pd.DataFrame({s: sp for s, sp, _, _ in ok}).sort_index()
    perp = pd.DataFrame({s: pp for s, _, pp, _ in ok}).sort_index()
    fund = pd.DataFrame({s: f for s, _, _, f in ok}).sort_index()
    start = pd.Timestamp(CFG["window"][0], tz="UTC")
    book = rotation_book(spot, perp, fund, top_n=5, lookback_days=7, costs=costs)
    net = book["net"][book["net"].index >= start]
    res: dict[str, Any] = {"study_id": CFG["study_id"], "run_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                           "coins_loaded": sorted(spot.columns), "load_errors": errors,
                           "coverage_first_day": {s: str(spot[s].first_valid_index())[:10] for s in spot.columns}}
    rot = summarize(net, book["funding"][net.index])
    rot["on_capital_50_50"] = {k: summarize(net / 2.0).get(k) for k in ("annual_return", "max_drawdown", "per_year")}
    rot["parts"] = {"funding": float(book["funding"][net.index].sum()), "basis": float(book["basis"][net.index].sum()),
                    "cost": float(-book["cost"][net.index].sum())}
    rot["picks"] = pick_stats({k: v for k, v in book["picks"].items() if pd.Timestamp(k) >= start})
    res["rotation_top5"] = rot
    bench = []
    for s in ("BTCUSDT", "ETHUSDT"):
        if s in spot:
            h = hedge_daily(spot[s].dropna(), perp[s].dropna(), fund[s].dropna(), costs=costs)
            bench.append(h["net"][h["net"].index >= start].rename(s))
    if len(bench) == 2:
        b = pd.concat(bench, axis=1).dropna().mean(axis=1)
        bs = summarize(b)
        bs["on_capital_50_50"] = {k: summarize(b / 2.0).get(k) for k in ("annual_return", "max_drawdown", "per_year")}
        res["benchmark_btc_eth_always_on"] = bs
    recent = net[net.index >= pd.Timestamp("2025-01-01", tz="UTC")]
    res["rotation_since_2025"] = {"on_notional": summarize(recent), "on_capital_50_50": summarize(recent / 2.0)}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(_clean(res), indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"coins": len(spot.columns), "errors": list(errors)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

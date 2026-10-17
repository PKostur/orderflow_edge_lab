"""Fill-realism sensitivity for the paper account (descriptive only; does not alter paper-account-blend-v1).

Scenario grid is declared here and is not tuned. The registered scenario must reproduce paper_account.replay exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from orderflow_edge_lab.multi_premia_forward import leg_returns
from orderflow_edge_lab.multi_premia_human_forward import coin_targets, leg_weights
from orderflow_edge_lab.paper_account import LAG, contracts_for
from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars

WATCH_ID = "paper-fill-scenarios-v1"
REGISTERED = "registered_5bps"
MIN_FEE = 0.0002
SLIPPAGE_BPS = (5, 10, 20, 40)  # per side; 5 = registered
ADVERSE_RANGE_FRACTION = 0.25  # of the 08:00 bar (high - low), on top of ADVERSE_SLIPPAGE_BPS
ADVERSE_SLIPPAGE_BPS = 10
MIN_ORDER_MULT = 2  # skip positions below MIN_ORDER_MULT x minVol (min-order stress)

SCENARIOS: dict[str, dict[str, Any]] = {
    REGISTERED: {"slippage_bps": 5, "range_fraction": 0.0, "min_order_mult": 1},
    "slippage_10bps": {"slippage_bps": 10, "range_fraction": 0.0, "min_order_mult": 1},
    "slippage_20bps": {"slippage_bps": 20, "range_fraction": 0.0, "min_order_mult": 1},
    "slippage_40bps": {"slippage_bps": 40, "range_fraction": 0.0, "min_order_mult": 1},
    "adverse_fill_quarter_range_10bps": {"slippage_bps": ADVERSE_SLIPPAGE_BPS, "range_fraction": ADVERSE_RANGE_FRACTION, "min_order_mult": 1},
    "min_order_2x_minvol": {"slippage_bps": 5, "range_fraction": 0.0, "min_order_mult": MIN_ORDER_MULT},
}
CLAIMS = {"edge_claimed": False, "promotion_authorized": False, "live_trading_authorized": False, "orders_sent": False}
NOTE = "Descriptive only. Sensitivity of the paper account to harsher pre-declared fill assumptions; the registered watch is unchanged."


def adverse_fill_price(open_px: float, high: float, low: float, delta: int, fraction: float) -> float:
    """Fill moved against the trade: buys (delta > 0) up, sells (delta < 0) down, by fraction x (high - low)."""
    move = fraction * max(float(high) - float(low), 0.0)
    return float(open_px) + (move if delta > 0 else -move if delta < 0 else 0.0)


def replay_scenario(targets: pd.DataFrame, open8: pd.DataFrame, funding: Mapping[str, pd.Series], specs: Mapping[str, Mapping[str, Any]],
                    *, start: pd.Timestamp, initial: float, slippage: float = 0.0005, min_fee: float = MIN_FEE,
                    ranges: pd.DataFrame | None = None, range_fraction: float = 0.0, min_order_mult: int = 1) -> dict[str, Any]:
    """Local copy of paper_account.replay (which has no fill hooks) with two additions. With range_fraction=0 and
    min_order_mult=1 it reproduces paper_account.replay exactly (tested). The adverse fill is charged as a cost at the
    fill (|delta| x contractSize x |fill - open|); marks stay at the open, as in the registered account.
    ranges: per-coin (high - low) of the 08:00 bar, indexed like open8."""
    days = [d for d in targets.index if d >= start and (d + LAG) in open8.index]
    equity, qty = initial, {s: 0 for s in targets.columns}
    curve, totals = [], {"fees": 0.0, "funding": 0.0, "traded_notional": 0.0, "adverse_fill_cost": 0.0}
    for n, d in enumerate(days):
        t = d + LAG
        px = open8.loc[t]
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
        for s in targets.columns:
            p = px.get(s)
            if s not in specs or pd.isna(p):
                continue
            want = contracts_for(float(targets.at[d, s]), equity, float(p), specs[s])
            if min_order_mult > 1 and abs(want) < min_order_mult * int(specs[s].get("minVol", 1)):
                want = 0
            delta = want - qty[s]
            if delta:
                cs = float(specs[s]["contractSize"])
                notional = abs(delta) * cs * float(p)
                fee = notional * (max(float(specs[s].get("takerFeeRate", 0.0)), min_fee) + slippage)
                if range_fraction and ranges is not None and t in ranges.index and s in ranges.columns and pd.notna(ranges.at[t, s]):
                    fill = adverse_fill_price(float(p), float(p) + float(ranges.at[t, s]), float(p), delta, range_fraction)
                    adv = abs(delta) * cs * abs(fill - float(p))
                    fee += adv
                    totals["adverse_fill_cost"] += adv
                equity -= fee
                totals["fees"] += fee
                totals["traded_notional"] += notional
                qty[s] = want
    return {"days": len(days), "equity": equity, "curve": curve, "totals": totals}


def _max_drawdown(curve: list[Mapping[str, Any]], initial: float) -> float:
    peak, worst = initial, 0.0
    for c in curve:
        peak = max(peak, c["equity"])
        worst = min(worst, c["equity"] / peak - 1.0)
    return worst


def _summary(led: Mapping[str, Any], initial: float) -> dict[str, Any]:
    t = led["totals"]
    return {"final_equity": round(led["equity"], 2), "return_pct": round(100 * (led["equity"] / initial - 1.0), 3),
            "total_fees": round(t["fees"], 2), "adverse_fill_cost": round(t["adverse_fill_cost"], 2),
            "funding": round(t["funding"], 2), "traded_notional": round(t["traded_notional"], 2),
            "turnover_x_initial": round(t["traded_notional"] / initial, 3),
            "max_drawdown_pct": round(100 * _max_drawdown(led["curve"], initial), 3)}


def run_grid(targets, open8, funding, specs, *, start, initial, ranges=None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, sc in SCENARIOS.items():
        led = replay_scenario(targets, open8, funding, specs, start=start, initial=initial, slippage=sc["slippage_bps"] / 1e4,
                              ranges=ranges, range_fraction=sc["range_fraction"], min_order_mult=sc["min_order_mult"])
        out[name] = {**sc, "days": led["days"], **_summary(led, initial)}
    base = out[REGISTERED]
    for r in out.values():
        r["equity_diff_vs_registered"] = round(r["final_equity"] - base["final_equity"], 2)
        r["return_pct_diff_vs_registered"] = round(r["return_pct"] - base["return_pct"], 3)
    return out


def build_report(cfg: Mapping[str, Any], blend_cfg: Mapping[str, Any], frames: Mapping[str, pd.DataFrame],
                 funding: Mapping[str, pd.Series], specs: Mapping[str, Mapping[str, Any]], *, as_of: Any) -> dict[str, Any]:
    # data path copied from paper_account.build_report
    as_of_ts, start = _utc(as_of), _utc(cfg["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    clean = {s: f for s, f in clean.items() if len(f) >= 250}
    legs = leg_returns(blend_cfg, clean, funding)
    b = blend_cfg["blend"]
    lw = leg_weights(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    agg = coin_targets(blend_cfg, clean, funding, lw)
    open8 = pd.DataFrame({s: f["open"].astype(float) for s, f in clean.items()}).sort_index()
    ranges = pd.DataFrame({s: (f["high"].astype(float) - f["low"].astype(float)) for s, f in clean.items()}).sort_index()
    initial = float(cfg["account"]["initial_equity"])
    scen = run_grid(agg, open8, funding, specs, start=start, initial=initial, ranges=ranges)
    days = next(iter(scen.values()))["days"]
    return {"schema_version": 1, "watch_id": WATCH_ID, "base_watch_id": cfg["watch_id"],
            "status": "PRE_START" if not days else "COLLECTING", "as_of_utc": as_of_ts.isoformat(),
            "prospective_start_utc": start.isoformat(), "coins_with_data": len(clean), "initial_equity": initial,
            "scenarios": scen, "note": NOTE, "claims": dict(CLAIMS)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
    from orderflow_edge_lab.paper_account import fetch_specs

    p = argparse.ArgumentParser(description="Fill-realism sensitivity for the paper account. Descriptive only.")
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
    print(json.dumps({"status": report["status"], "scenarios": {k: v["final_equity"] for k, v in report["scenarios"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

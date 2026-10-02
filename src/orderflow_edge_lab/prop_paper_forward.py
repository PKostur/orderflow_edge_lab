"""Paper prop career on live data (config/prop_paper_forward_v1.json). Paper only: no account, no orders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
from orderflow_edge_lab.prop_sim import BUFFER, headroom_multiplier, trailing_sigma
from orderflow_edge_lab.trend_portfolio_forward import _utc, completed_bars

WATCH_ID = "prop-paper-career-v1"


def challenge_scale(eq: float, floor: float, annvol: float) -> float:
    if not (np.isfinite(annvol) and annvol > 0):
        return 0.0
    return min(5.0, 0.25 / annvol) * headroom_multiplier(eq - floor)


def funded_scale(eq: float, floor: float) -> float:
    return 1.25 * headroom_multiplier(eq - floor)


def run_career(r: pd.Series, annvol: pd.Series, firm: Mapping[str, Any], prule: Mapping[str, Any], *,
               buffer: float = BUFFER) -> dict[str, Any]:
    """r: daily book returns from the start day on (index = day the return accrues to)."""
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    floor = 1.0 - max_lim  # static max loss (HyroTrader)
    st = {"events": [], "fees": 0.0, "paid": 0.0, "phase": "challenge", "eq": 1.0, "k": 0, "phase_i": 0}

    def buy(ts: str) -> None:
        st.update(fees=st["fees"] + firm["fee_pct"], phase="challenge", eq=1.0, k=0, phase_i=0)
        st["events"].append({"date": ts, "event": "challenge_bought"})

    if len(r):
        buy(r.index[0].isoformat())
    for t, ret in r.items():
        ts = t.isoformat()
        eq = st["eq"]
        if st["phase"] == "challenge":
            s = challenge_scale(eq, floor, float(annvol.get(t, np.nan)))
        else:
            s = funded_scale(eq, floor)
        pnl = eq * s * float(ret)
        eq += pnl
        st["eq"], st["k"] = eq, st["k"] + 1
        if -pnl > daily_lim or eq < floor:
            st["events"].append({"date": ts, "event": st["phase"] + "_breach", "equity": round(eq, 6)})
            buy(ts)
            continue
        if st["phase"] == "challenge" and eq >= 1.0 + firm["phases"][st["phase_i"]] and st["k"] >= firm.get("min_days", 0):
            st["phase_i"] += 1
            if st["phase_i"] < len(firm["phases"]):
                st.update(eq=1.0, k=0)
                st["events"].append({"date": ts, "event": "phase_passed"})
            else:
                st.update(phase="funded", eq=1.0, k=0)
                st["events"].append({"date": ts, "event": "challenge_passed"})
            continue
        if st["phase"] == "funded" and st["k"] >= prule["first_eligible_day"] and eq - 1.0 >= 0.01:
            amt = eq - 1.0 if prule["max_per_payout"] is None else min(eq - 1.0, prule["max_per_payout"])
            st["paid"] += firm["split"] * amt
            st["eq"] = eq - amt
            st["events"].append({"date": ts, "event": "payout", "amount_pct": round(100 * firm["split"] * amt, 4)})
    last_vol = float(annvol.iloc[-1]) if len(annvol) else float("nan")
    eq = st["eq"]
    nxt = challenge_scale(eq, floor, last_vol) if st["phase"] == "challenge" else funded_scale(eq, floor)
    ev = st["events"]
    return {"events": ev, "phase": st["phase"], "equity": eq, "headroom_pct": 100 * (eq - floor), "days_in_phase": st["k"],
            "next_day_risk_multiplier": nxt, "fees_pct": 100 * st["fees"], "payouts_pct": 100 * st["paid"],
            "net_pct": 100 * (st["paid"] - st["fees"]),
            "challenges_bought": sum(e["event"] == "challenge_bought" for e in ev),
            "payouts": sum(e["event"] == "payout" for e in ev)}


def build_report(cfg: Mapping[str, Any], blend_cfg: Mapping[str, Any], firm: Mapping[str, Any], prule: Mapping[str, Any],
                 frames: Mapping[str, pd.DataFrame], funding: Mapping[str, pd.Series], *, as_of: Any) -> dict[str, Any]:
    as_of_ts, start = _utc(as_of), _utc(cfg["prospective_start_utc"])
    clean = {s: completed_bars(f, as_of_ts) for s, f in frames.items()}
    legs = leg_returns(blend_cfg, clean, funding)
    b = blend_cfg["blend"]
    book = blend(legs[["S1", "S2", "S3"]], vol_window=int(b["vol_window_days"]), min_obs=int(b["min_obs"]))
    annvol = pd.Series(trailing_sigma(np.nan_to_num(book.to_numpy())) * np.sqrt(365), index=book.index)
    fwd = book[(book.index - pd.Timedelta(days=1)) >= start]
    career = run_career(fwd, annvol, firm, prule)
    return {"schema_version": 1, "watch_id": WATCH_ID, "status": "PRE_START" if fwd.empty else "COLLECTING",
            "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(), "days_scored": int(len(fwd)),
            "career": career, "claims": dict(cfg["claims"])}


def main(argv: list[str] | None = None) -> int:
    import argparse
    from concurrent.futures import ThreadPoolExecutor

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Run the paper prop career (prop-paper-career-v1).")
    p.add_argument("--config", default="config/prop_paper_forward_v1.json")
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    bcfg = json.loads(Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))
    firm = json.loads(Path("config/prop_firm_v1.json").read_text(encoding="utf-8"))["firms"][cfg["firm"]]
    prule = json.loads(Path("config/prop_firm_v6.json").read_text(encoding="utf-8"))["payout_rules"][cfg["firm"]]
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
    report = build_report(cfg, bcfg, firm, prule, frames, funding, as_of=as_of)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "days": report["days_scored"], "phase": report["career"]["phase"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

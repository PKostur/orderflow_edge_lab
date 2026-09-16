from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.residual_momentum_forward import simulate_forward, summarize


# Loader warm-up only. The candidate itself still uses exactly 45 prior completed days.
WARMUP_START = "2026-01-01T00:00:00Z"


def _safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.floating): v = float(v)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--protocol", default="config/dv2_residual_momentum_beta45_d4_v1.json")
    p.add_argument("--candidate", default="config/dv2_residual_momentum_beta45_v1.json")
    p.add_argument("--output-dir", default="research/discovery_v2/residual_momentum_beta45/d4_shadow")
    a = p.parse_args(); protocol = json.loads(Path(a.protocol).read_text()); candidate = json.loads(Path(a.candidate).read_text())
    asof = pd.Timestamp.now(tz="UTC"); fetch_end = asof.normalize() + pd.Timedelta(days=1)
    symbols = list(candidate["universe"]["symbols"]); prices = {}; funding = {}
    for symbol in symbols:
        prices[symbol] = fetch_mexc_futures_klines(symbol, "1d", WARMUP_START, fetch_end.isoformat())
        funding[symbol] = fetch_mexc_funding_history(symbol, WARMUP_START, fetch_end.isoformat())
    kwargs = dict(
        frames=prices, funding_frames=funding, symbols=symbols,
        lookback=int(candidate["signal"]["beta_lookback_completed_days"]),
        forward_start=pd.Timestamp(protocol["forward_start_utc"]), asof=asof,
        side_cost_bps=float(candidate["execution"]["baseline_round_trip_cost_bps"])/2.0,
    )
    exact = simulate_forward(reverse=True, **kwargs); control = simulate_forward(reverse=False, **kwargs)
    exact_summary = summarize(exact); control_summary = summarize(control)
    out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
    if not exact["observations"].empty: exact["observations"].to_csv(out/"observations.csv", index_label="timestamp")
    if not exact["contributions"].empty: exact["contributions"].to_csv(out/"symbol_contributions.csv", index=False)
    report = {
        "protocol": protocol["protocol"], "candidate_id": candidate["candidate_id"], "asof_utc": asof.isoformat(),
        "forward_start_utc": protocol["forward_start_utc"], "state": "EVIDENCE_ACCUMULATING" if exact_summary["completed_periods"] else "PROSPECTIVE_SHADOW",
        "exact_candidate": exact_summary, "principal_reversed_control": control_summary,
        "review_minimum_completed_periods": int(protocol["review"]["minimum_completed_portfolio_periods"]),
        "review_minimum_met": exact_summary["completed_periods"] >= int(protocol["review"]["minimum_completed_portfolio_periods"]),
        "funding_status": "actual MEXC public historical funding included strictly inside each completed open-to-open period",
        "cost_status": "10 bps per transaction side on actual portfolio turnover; 1.0x/1.5x/2.0x reported",
        "claims": {"paper_shadow_only": True, "persistent_edge_established": False, "live_eligible": False, "no_pre_start_backfill": True},
    }
    report = _safe(report); (out/"D4_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    lines = ["# beta45 Prospective D4 Shadow", "", f"As-of UTC: **{report['asof_utc']}**", f"State: **{report['state']}**", "",
             f"Completed periods: **{exact_summary['completed_periods']} / {report['review_minimum_completed_periods']}**",
             f"Forward PnL per $1,000: **${exact_summary['pnl_per_1000']:.2f}**", f"Max drawdown: **{exact_summary['max_drawdown']}**",
             f"Open position: `{exact_summary['open_position']}`", "", "Paper/shadow evidence only; no persistent edge claim and no live execution."]
    (out/"D4_REPORT.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({"asof_utc": report["asof_utc"], "completed": exact_summary["completed_periods"], "pnl_per_1000": exact_summary["pnl_per_1000"], "open": exact_summary["open_position"]}, indent=2))


if __name__ == "__main__": main()

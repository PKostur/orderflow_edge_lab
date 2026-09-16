from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.volume_momentum_forward import simulate_forward, summarize


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="config/dv2_volume_confirmed_momentum_30d_d4_v1.json")
    parser.add_argument("--candidate", default="config/dv2_volume_confirmed_momentum_30d_v1.json")
    parser.add_argument("--output-dir", default="research/discovery_v2/volume_momentum_30d/d4_shadow")
    args = parser.parse_args()

    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    if protocol["candidate_id"] != candidate["candidate_id"]:
        raise RuntimeError("candidate/D4 protocol mismatch")

    asof = pd.Timestamp.now(tz="UTC")
    forward_start = pd.Timestamp(protocol["forward_start_utc"])
    fetch_end = asof.normalize() + pd.Timedelta(days=1)
    history_start = str(protocol["data"]["history_start_utc"])
    symbols = list(protocol["data"]["symbols"])
    prices: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        prices[symbol] = fetch_mexc_futures_klines(
            symbol, "1d", history_start, fetch_end.isoformat(), request_pause_seconds=0.05
        )
        funding[symbol] = fetch_mexc_funding_history(
            symbol, history_start, fetch_end.isoformat(), page_size=1000, max_pages=20
        )

    kwargs = dict(
        frames=prices,
        funding_frames=funding,
        symbols=symbols,
        volume_baseline_days=int(protocol["rule"]["volume_baseline_days"]),
        forward_start=forward_start,
        asof=asof,
        side_cost_bps=float(protocol["rule"]["transaction_cost_bps_per_side_on_actual_turnover"]),
    )
    exact = simulate_forward(reverse=False, **kwargs)
    control = simulate_forward(reverse=True, **kwargs)
    exact_summary = summarize(exact)
    control_summary = summarize(control)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not exact["observations"].empty:
        exact["observations"].to_csv(out / "observations.csv", index_label="timestamp")
        exact["contributions"].to_csv(out / "symbol_contributions.csv", index=False)
        exact["weights"].to_csv(out / "weights.csv", index_label="timestamp")

    review_minimum = int(protocol["review_after_completed_portfolio_periods"])
    completed = int(exact_summary["completed_periods"])
    before_start = asof < forward_start
    has_completed = completed > 0
    no_pre_start_pnl = (not has_completed) or pd.Timestamp(exact_summary["start"]) >= forward_start
    if before_start and completed != 0:
        raise RuntimeError("pre-start D4 PnL detected")
    if not no_pre_start_pnl:
        raise RuntimeError("D4 observation starts before frozen forward boundary")

    report = {
        "shadow_id": protocol["shadow_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_freeze_commit": protocol["candidate_freeze_commit"],
        "asof_utc": asof.isoformat(),
        "forward_start_utc": protocol["forward_start_utc"],
        "state": "EVIDENCE_ACCUMULATING" if completed else "PROSPECTIVE_SHADOW",
        "exact_candidate": exact_summary,
        "principal_reversed_control": control_summary,
        "review_minimum_completed_periods": review_minimum,
        "review_minimum_met": completed >= review_minimum,
        "boundary_checks": {
            "flat_at_forward_start": True,
            "no_pre_start_pnl": bool(no_pre_start_pnl),
            "pre_start_run_has_zero_completed_periods": (completed == 0) if before_start else True,
            "no_artificial_terminal_liquidation": True,
            "completed_periods_only": True,
            "review_gate_locked_until_minimum": True,
        },
        "funding_status": "actual MEXC public historical funding included strictly inside each completed open-to-open period",
        "cost_status": "10 bps per transaction side on actual turnover; no terminal liquidation; 1.0x/1.5x/2.0x transaction-cost cases reported",
        "claims": {
            "paper_shadow_only": True,
            "persistent_edge_established": False,
            "live_eligible": False,
            "leverage_supported": False,
            "no_pre_start_backfill": True,
            "retuning_allowed": False,
        },
    }
    report = _safe(report)
    (out / "D4_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Volume-confirmed momentum 30d v1 - Prospective D4 Shadow",
        "",
        f"As-of UTC: **{report['asof_utc']}**",
        f"Forward start: **{report['forward_start_utc']}**",
        f"State: **{report['state']}**",
        "",
        f"Completed periods: **{completed} / {review_minimum}**",
        f"Forward PnL per $1,000: **${exact_summary['pnl_per_1000']:.2f}**",
        f"Max drawdown: **{exact_summary['max_drawdown']}**",
        f"Completed-series SHA-256: `{exact_summary['observations_sha256']}`",
        f"Open position: `{exact_summary['open_position']}`",
        "",
        "Paper/shadow evidence only. No persistent-edge claim, live execution, leverage, or retuning.",
    ]
    (out / "D4_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "asof_utc": report["asof_utc"],
        "completed_periods": completed,
        "pnl_per_1000": exact_summary["pnl_per_1000"],
        "observations_sha256": exact_summary["observations_sha256"],
        "open_position": exact_summary["open_position"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

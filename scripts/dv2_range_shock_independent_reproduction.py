from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint4 import liquidity_range_shock_reversal
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.range_shock_momentum_candidate import run_range_shock_momentum_candidate

START = "2026-01-01T00:00:00Z"
END = "2026-09-12T00:00:00Z"
SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fetch():
    daily, funding = {}, {}
    for symbol in SYMBOLS:
        daily[symbol] = fetch_mexc_futures_klines(symbol, "1d", START, END, request_pause_seconds=0.05)
        funding[symbol] = fetch_mexc_funding_history(symbol, START, END, page_size=1000, max_pages=20)
    return daily, funding


def _dense_primary(frame: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    x = frame.copy()
    if x.empty:
        x = pd.DataFrame(columns=["timestamp", "symbol", "net_contribution_bps"])
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    dense_idx = pd.MultiIndex.from_product([idx, SYMBOLS], names=["timestamp", "symbol"])
    return x.set_index(["timestamp", "symbol"])[["net_contribution_bps"]].reindex(dense_idx, fill_value=0.0).sort_index()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="research/discovery_v2/range_shock_momentum_30d/reproduction/results")
    args = parser.parse_args(); out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    daily, funding = _fetch()

    # Primary engine is the exact Sprint 4 reversed control that generated the new candidate.
    primary = liquidity_range_shock_reversal(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        range_baseline_days=30,
        common_warmup_days=45,
        side_cost_bps=10.0,
        reverse=True,
    )
    independent = run_range_shock_momentum_candidate(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        range_baseline_days=30,
        fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0,
        reverse=False,
        force_terminal_liquidation=True,
    )

    p, q = primary.observations.sort_index(), independent.observations.sort_index()
    timestamp_match = p.index.equals(q.index)
    end_match = timestamp_match and pd.to_datetime(p["end_timestamp"], utc=True).equals(pd.to_datetime(q["end_timestamp"], utc=True))
    numeric = ["gross_return_bps", "cost_bps", "net_return_bps", "active_gross"]
    max_obs = float(np.max(np.abs(p[numeric].to_numpy(float) - q[numeric].to_numpy(float)))) if timestamp_match and len(p) == len(q) else None

    pc = _dense_primary(primary.contributions, p.index)
    qc = independent.contributions.copy(); qc["timestamp"] = pd.to_datetime(qc["timestamp"], utc=True)
    qc = qc.set_index(["timestamp", "symbol"])[["net_contribution_bps"]].sort_index()
    contribution_index_match = pc.index.equals(qc.index)
    max_contrib = float(np.max(np.abs(pc["net_contribution_bps"].to_numpy(float) - qc["net_contribution_bps"].to_numpy(float)))) if contribution_index_match and len(pc) == len(qc) else None
    tolerance = 1e-9
    passed = bool(timestamp_match and end_match and max_obs is not None and max_obs <= tolerance and contribution_index_match and max_contrib is not None and max_contrib <= tolerance)

    report = {
        "candidate_id": "dv2_liquidity_range_shock_momentum_30d_v1",
        "candidate_freeze_commit": "0b47cc8986da030057e7dd4047ce4a60d1efb89a",
        "freeze_clarification_commit": "cf9d16937ef25f6cebb53c6724ff217a5ac47cf9",
        "source": "MEXC same-period engineering reproduction",
        "economic_evidence_level": "NONE_ENGINEERING_ONLY",
        "primary_engine": "discovery_v2_sprint4.liquidity_range_shock_reversal(reverse=True)",
        "independent_engine": "range_shock_momentum_candidate.run_range_shock_momentum_candidate",
        "observations_primary": int(len(p)),
        "observations_independent": int(len(q)),
        "timestamp_match": timestamp_match,
        "end_timestamp_match": end_match,
        "max_observation_abs_diff": max_obs,
        "contribution_index_match": contribution_index_match,
        "max_contribution_abs_diff": max_contrib,
        "tolerance": tolerance,
        "zero_disagreement_pass": passed,
        "claims": {"independent_engine_replication_complete": passed, "persistent_edge_established": False, "future_oos": False, "live_eligible": False},
    }
    (out / "REPRODUCTION_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    p.to_csv(out / "primary_observations.csv", index_label="timestamp")
    q.to_csv(out / "independent_observations.csv", index_label="timestamp")
    independent.weights.to_csv(out / "independent_weights.csv", index_label="timestamp")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit("independent reproduction disagreement")


if __name__ == "__main__": main()

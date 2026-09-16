from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint3 import volume_confirmed_momentum
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.volume_momentum_candidate import run_volume_momentum_candidate


START = "2026-01-01T00:00:00Z"
END = "2026-09-12T00:00:00Z"
SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"]


def _fetch() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    daily: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        daily[symbol] = fetch_mexc_futures_klines(symbol, "1d", START, END, request_pause_seconds=0.05)
        funding[symbol] = fetch_mexc_funding_history(symbol, START, END, page_size=1000, max_pages=20)
    return daily, funding


def _dense_primary_contributions(frame: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(index=pd.MultiIndex.from_arrays([[], []], names=["timestamp", "symbol"]))
    x = frame.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    dense_idx = pd.MultiIndex.from_product([idx, SYMBOLS], names=["timestamp", "symbol"])
    return x.set_index(["timestamp", "symbol"])[["net_contribution_bps"]].reindex(dense_idx, fill_value=0.0).sort_index()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="research/discovery_v2/volume_momentum_30d/reproduction/results")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    daily, funding = _fetch()
    primary = volume_confirmed_momentum(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        volume_baseline_days=30,
        common_warmup_days=45,
        side_cost_bps=10.0,
        reverse=False,
    )
    independent = run_volume_momentum_candidate(
        daily,
        symbols=SYMBOLS,
        funding_frames=funding,
        volume_baseline_days=30,
        fixed_evaluation_warmup_days=45,
        side_cost_bps=10.0,
        reverse=False,
        force_terminal_liquidation=True,
    )

    p = primary.observations.sort_index()
    q = independent.observations.sort_index()
    timestamp_match = p.index.equals(q.index)
    end_match = timestamp_match and pd.to_datetime(p["end_timestamp"], utc=True).equals(pd.to_datetime(q["end_timestamp"], utc=True))
    numeric_cols = ["gross_return_bps", "cost_bps", "net_return_bps", "active_gross"]
    max_obs_abs_diff = None
    if timestamp_match and len(p) == len(q):
        max_obs_abs_diff = float(np.max(np.abs(p[numeric_cols].to_numpy(float) - q[numeric_cols].to_numpy(float))))

    pc = _dense_primary_contributions(primary.contributions, p.index)
    qc = independent.contributions.copy()
    qc["timestamp"] = pd.to_datetime(qc["timestamp"], utc=True)
    qc = qc.set_index(["timestamp", "symbol"])[["net_contribution_bps"]].sort_index()
    contribution_index_match = pc.index.equals(qc.index)
    max_contribution_abs_diff = None
    if contribution_index_match and len(pc) == len(qc):
        max_contribution_abs_diff = float(np.max(np.abs(pc["net_contribution_bps"].to_numpy(float) - qc["net_contribution_bps"].to_numpy(float))))

    tolerance = 1e-9
    passed = bool(
        timestamp_match
        and end_match
        and max_obs_abs_diff is not None
        and max_obs_abs_diff <= tolerance
        and contribution_index_match
        and max_contribution_abs_diff is not None
        and max_contribution_abs_diff <= tolerance
    )
    report = {
        "candidate_id": "dv2_volume_confirmed_momentum_30d_v1",
        "candidate_freeze_commit": "b2c74be00fdebb78090f972b43a0ea480619c8d6",
        "freeze_clarification_commit": "37d2c5a1ebc1c510200f3b0b1159210ee81be11b",
        "source": "MEXC same-period engineering reproduction",
        "economic_evidence_level": "NONE_ENGINEERING_ONLY",
        "primary_engine": "discovery_v2_sprint3.volume_confirmed_momentum",
        "independent_engine": "volume_momentum_candidate.run_volume_momentum_candidate",
        "observations_primary": int(len(p)),
        "observations_independent": int(len(q)),
        "timestamp_match": timestamp_match,
        "end_timestamp_match": end_match,
        "max_observation_abs_diff": max_obs_abs_diff,
        "contribution_index_match": contribution_index_match,
        "max_contribution_abs_diff": max_contribution_abs_diff,
        "tolerance": tolerance,
        "zero_disagreement_pass": passed,
        "claims": {
            "independent_engine_replication_complete": passed,
            "persistent_edge_established": False,
            "future_oos": False,
            "live_eligible": False,
        },
    }
    (output / "REPRODUCTION_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    independent.weights.to_csv(output / "independent_weights.csv", index_label="timestamp")
    p.to_csv(output / "primary_observations.csv", index_label="timestamp")
    q.to_csv(output / "independent_observations.csv", index_label="timestamp")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not passed:
        raise SystemExit("independent reproduction disagreement")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.binance_vision import fetch_vision
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, variant_summary
from orderflow_edge_lab.range_shock_momentum_candidate import run_range_shock_momentum_candidate


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.floating): v = float(v)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def _write_frame(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_index().to_csv(path, index_label="timestamp")
    return {"path": str(path), "sha256": _sha256(path), "rows": int(len(frame)),
            "start": frame.index.min().isoformat() if len(frame) else None,
            "end": frame.index.max().isoformat() if len(frame) else None}


def _fetch(contract: Mapping[str, Any], out: Path):
    cfg = contract["data"]; symbols = list(cfg["symbols"]); start = str(cfg["start_utc"]); end = str(cfg["end_utc_exclusive"])
    daily, funding = {}, {}
    manifest = {"source": cfg["source"], "venue": cfg["venue"], "independence_level": contract["independence_level"],
                "start_utc": start, "end_utc_exclusive": end, "symbols": symbols,
                "archive_checksum_policy": cfg["archive_checksum_policy"], "files": {}, "archive_objects": {}}
    end_ts = pd.Timestamp(end); required_price_tail = end_ts - pd.Timedelta(days=1); required_funding_tail = end_ts - pd.Timedelta(days=1)
    for symbol in symbols:
        prices, funds, objects = fetch_vision(symbol, start, end)
        if prices.empty or funds.empty:
            raise RuntimeError(f"{symbol}: missing Binance history")
        if prices.index.has_duplicates or funds.index.has_duplicates or not prices.index.is_monotonic_increasing or not funds.index.is_monotonic_increasing:
            raise RuntimeError(f"{symbol}: invalid chronology")
        required = {"open", "high", "low", "close"}
        missing = required.difference(prices.columns)
        if missing:
            raise RuntimeError(f"{symbol}: missing fields {sorted(missing)}")
        if prices.index.max() < required_price_tail:
            raise RuntimeError(f"{symbol}: incomplete price tail")
        if funds.index.max() < required_funding_tail:
            raise RuntimeError(f"{symbol}: incomplete funding tail")
        daily[symbol], funding[symbol] = prices, funds
        manifest["files"][f"{symbol}:1d"] = _write_frame(prices, out / "data" / "daily" / f"{symbol}_1d.csv")
        manifest["files"][f"{symbol}:funding"] = _write_frame(funds, out / "data" / "funding" / f"{symbol}_funding.csv")
        manifest["archive_objects"][symbol] = objects
    mp = out / "data" / "dataset_manifest.json"; mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(_safe(manifest), indent=2, sort_keys=True), encoding="utf-8"); manifest["manifest_sha256"] = _sha256(mp)
    return daily, funding, manifest


def _to_variant(run) -> VariantRun:
    return VariantRun(run.observations.copy(), run.contributions.copy())


def _benchmarks(daily, candidate_obs, symbols):
    opens = pd.concat({s: pd.to_numeric(daily[s]["open"], errors="coerce") for s in symbols}, axis=1, join="inner").dropna().sort_index()
    nxt = opens.shift(-1) / opens - 1.0; idx = candidate_obs.index.intersection(nxt.index); alts = [s for s in symbols if s != "BTC_USDT"]
    btc = nxt.loc[idx, "BTC_USDT"].dropna(); ew = nxt.loc[idx, alts].mean(axis=1).dropna()
    return {
        "btc_open_to_open": {"observations": int(len(btc)), "mean_bps": float(btc.mean()*1e4), "compounded_return": float((1+btc).prod()-1)},
        "equal_weight_nine_alts_open_to_open": {"observations": int(len(ew)), "mean_bps": float(ew.mean()*1e4), "compounded_return": float((1+ew).prod()-1)},
    }


def run(candidate: Mapping[str, Any], contract: Mapping[str, Any], evaluation: Mapping[str, Any], out: Path) -> dict[str, Any]:
    if candidate["candidate_id"] != contract["candidate_id"]:
        raise RuntimeError("candidate/contract mismatch")
    out.mkdir(parents=True, exist_ok=True); daily, funding, manifest = _fetch(contract, out)
    rule = contract["rule"]; symbols = list(contract["data"]["symbols"])
    exact = run_range_shock_momentum_candidate(
        daily, symbols=symbols, funding_frames=funding,
        range_baseline_days=int(rule["range_baseline_days"]), fixed_evaluation_warmup_days=int(rule["fixed_evaluation_warmup_days"]),
        side_cost_bps=float(rule["transaction_cost_bps_per_side_on_actual_turnover"]), reverse=False, force_terminal_liquidation=True)
    control = run_range_shock_momentum_candidate(
        daily, symbols=symbols, funding_frames=funding,
        range_baseline_days=int(rule["range_baseline_days"]), fixed_evaluation_warmup_days=int(rule["fixed_evaluation_warmup_days"]),
        side_cost_bps=float(rule["transaction_cost_bps_per_side_on_actual_turnover"]), reverse=True, force_terminal_liquidation=True)
    ev, econ = evaluation["statistics"], evaluation["economics"]
    es = variant_summary(_to_variant(exact), cost_multipliers=econ["cost_multipliers"], bootstrap_cfg=ev)
    cs = variant_summary(_to_variant(control), cost_multipliers=econ["cost_multipliers"], bootstrap_cfg=ev)
    advantage = float(es["mean_net_bps"] - cs["mean_net_bps"]); g = contract["hard_gates"]
    gates = {
        "positive_net_baseline": float(es["cost_cases"]["1.0"]["mean_net_bps"]) > 0,
        "positive_net_1_5x_cost": float(es["cost_cases"]["1.5"]["mean_net_bps"]) > 0,
        "leave_one_symbol_out_positive": es["minimum_leave_one_symbol_out_mean_bps"] is not None and float(es["minimum_leave_one_symbol_out_mean_bps"]) > float(g["minimum_leave_one_symbol_out_mean_bps_gt"]),
        "best_symbol_share_le_50pct": es["best_symbol_positive_pnl_share"] is not None and float(es["best_symbol_positive_pnl_share"]) <= float(g["maximum_best_symbol_positive_pnl_share"]),
        "best_month_share_le_50pct": es["best_calendar_month_positive_pnl_share"] is not None and float(es["best_calendar_month_positive_pnl_share"]) <= float(g["maximum_best_calendar_month_positive_pnl_share"]),
        "top5_positive_period_share_le_50pct": es["top5_positive_period_share"] is not None and float(es["top5_positive_period_share"]) <= float(g["maximum_top5_positive_period_share"]),
        "principal_reversed_control_weaker_by_5bps": advantage >= float(g["minimum_candidate_minus_reversed_control_mean_bps"]),
        "chronology_valid": True, "data_complete": True, "funding_complete": True, "execution_valid": True,
    }
    level = str(contract["independence_level"])
    if level == "D2": state = "D2_SOURCE_REPLICATED" if all(gates.values()) else "D2_SOURCE_FAILED"
    elif level == "D3_TEMPORAL_HOLDOUT": state = "D3_TEMPORAL_REPLICATED" if all(gates.values()) else "D3_TEMPORAL_FAILED"
    else: raise RuntimeError(f"unsupported level: {level}")
    for name, obj in (("exact_candidate", exact), ("principal_reversed_control", control)):
        folder = out / "series" / name; folder.mkdir(parents=True, exist_ok=True)
        obj.observations.to_csv(folder / "observations.csv", index_label="timestamp"); obj.contributions.to_csv(folder / "symbol_contributions.csv", index=False); obj.weights.to_csv(folder / "weights.csv", index_label="timestamp")
    return {
        "candidate_id": candidate["candidate_id"], "candidate_freeze_commit": contract["candidate_freeze_commit"],
        "freeze_clarification_commit": contract["freeze_clarification_commit"], "contract_id": contract["contract_id"],
        "state": state, "independence_level": level, "dataset_manifest": manifest, "exact_candidate": es,
        "principal_reversed_control": cs, "candidate_minus_reversed_control_mean_net_bps": advantage,
        "benchmarks": _benchmarks(daily, exact.observations, symbols), "hard_gates": gates,
        "diagnostics": {"bootstrap_lower_bound_positive": float(es["bootstrap_lower_bps"]) > 0,
                        "two_x_cost_mean_net_bps": float(es["cost_cases"]["2.0"]["mean_net_bps"])},
        "claims": {"persistent_edge_established": False, "prospective_future_oos": False,
                   "live_eligible": False, "leverage_supported": False, "retuning_allowed": False},
    }


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--candidate", default="config/dv2_liquidity_range_shock_momentum_30d_v1.json"); p.add_argument("--contract", required=True)
    p.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json"); p.add_argument("--output-dir", required=True); a = p.parse_args()
    out = Path(a.output_dir); report = _safe(run(_load(a.candidate), _load(a.contract), _load(a.evaluation), out))
    (out / "VALIDATION_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"candidate_id": report["candidate_id"], "state": report["state"], "hard_gates": report["hard_gates"], "diagnostics": report["diagnostics"]}, indent=2, sort_keys=True))


if __name__ == "__main__": main()

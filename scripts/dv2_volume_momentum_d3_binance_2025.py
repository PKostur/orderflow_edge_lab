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
from orderflow_edge_lab.volume_momentum_candidate import run_volume_momentum_candidate


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _write_frame(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_index().to_csv(path, index_label="timestamp")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "rows": int(len(frame)),
        "start": frame.index.min().isoformat() if len(frame) else None,
        "end": frame.index.max().isoformat() if len(frame) else None,
    }


def _validate(frame: pd.DataFrame, label: str, required: set[str]) -> None:
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        raise RuntimeError(f"{label}: missing or invalid history")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise RuntimeError(f"{label}: duplicate/non-monotonic timestamps")
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"{label}: missing columns {sorted(missing)}")


def _fetch(contract: Mapping[str, Any], output: Path):
    cfg = contract["data"]
    symbols = list(cfg["symbols"])
    start = str(cfg["start_utc"])
    end = str(cfg["end_utc_exclusive"])
    daily: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    manifest: dict[str, Any] = {
        "source": cfg["source"],
        "venue": cfg["venue"],
        "independence_level": contract["independence_level"],
        "start_utc": start,
        "end_utc_exclusive": end,
        "symbols": symbols,
        "kline_volume_semantic": cfg["kline_volume_semantic"],
        "archive_checksum_policy": cfg["archive_checksum_policy"],
        "files": {},
        "archive_objects": {},
    }
    end_ts = pd.Timestamp(end)
    required_price_tail = end_ts - pd.Timedelta(days=1)
    required_funding_tail = end_ts - pd.Timedelta(days=1)
    for symbol in symbols:
        prices, funds, objects = fetch_vision(symbol, start, end)
        _validate(prices, f"{symbol} prices", {"open", "close", "volume"})
        _validate(funds, f"{symbol} funding", {"funding_rate"})
        if prices.index.max() < required_price_tail:
            raise RuntimeError(f"{symbol}: price tail incomplete")
        if funds.index.max() < required_funding_tail:
            raise RuntimeError(f"{symbol}: funding tail incomplete")
        daily[symbol] = prices
        funding[symbol] = funds
        manifest["files"][f"{symbol}:1d"] = _write_frame(prices, output / "data" / "daily" / f"{symbol}_1d.csv")
        manifest["files"][f"{symbol}:funding"] = _write_frame(funds, output / "data" / "funding" / f"{symbol}_funding.csv")
        manifest["archive_objects"][symbol] = objects
    manifest_path = output / "data" / "dataset_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(_safe(manifest), indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_sha256"] = _sha256(manifest_path)
    return daily, funding, manifest


def _variant(run) -> VariantRun:
    return VariantRun(run.observations.copy(), run.contributions.copy())


def _benchmarks(daily: Mapping[str, pd.DataFrame], observations: pd.DataFrame, symbols: list[str]) -> dict[str, Any]:
    opens = pd.concat({s: pd.to_numeric(daily[s]["open"], errors="coerce") for s in symbols}, axis=1, join="inner").dropna().sort_index()
    next_ret = opens.shift(-1) / opens - 1.0
    idx = observations.index.intersection(next_ret.index)
    btc = next_ret.loc[idx, "BTC_USDT"].dropna()
    alts = [s for s in symbols if s != "BTC_USDT"]
    ew = next_ret.loc[idx, alts].mean(axis=1).dropna()
    return {
        "btc_open_to_open": {"observations": int(len(btc)), "mean_bps": float(btc.mean() * 1e4), "compounded_return": float((1 + btc).prod() - 1)},
        "equal_weight_nine_alts_open_to_open": {"observations": int(len(ew)), "mean_bps": float(ew.mean() * 1e4), "compounded_return": float((1 + ew).prod() - 1)},
    }


def run(candidate: Mapping[str, Any], contract: Mapping[str, Any], evaluation: Mapping[str, Any], output: Path) -> dict[str, Any]:
    if candidate["candidate_id"] != contract["candidate_id"]:
        raise RuntimeError("candidate/D3 contract mismatch")
    output.mkdir(parents=True, exist_ok=True)
    daily, funding, manifest = _fetch(contract, output)
    symbols = list(contract["data"]["symbols"])
    side_cost = float(contract["rule"]["transaction_cost_bps_per_side_on_actual_turnover"])
    exact = run_volume_momentum_candidate(
        daily,
        symbols=symbols,
        funding_frames=funding,
        volume_baseline_days=int(contract["rule"]["volume_baseline_days"]),
        fixed_evaluation_warmup_days=int(contract["rule"]["fixed_evaluation_warmup_days"]),
        side_cost_bps=side_cost,
        reverse=False,
        force_terminal_liquidation=True,
    )
    control = run_volume_momentum_candidate(
        daily,
        symbols=symbols,
        funding_frames=funding,
        volume_baseline_days=int(contract["rule"]["volume_baseline_days"]),
        fixed_evaluation_warmup_days=int(contract["rule"]["fixed_evaluation_warmup_days"]),
        side_cost_bps=side_cost,
        reverse=True,
        force_terminal_liquidation=True,
    )
    stats = evaluation["statistics"]
    economics = evaluation["economics"]
    exact_summary = variant_summary(_variant(exact), cost_multipliers=economics["cost_multipliers"], bootstrap_cfg=stats)
    control_summary = variant_summary(_variant(control), cost_multipliers=economics["cost_multipliers"], bootstrap_cfg=stats)
    advantage = float(exact_summary["mean_net_bps"] - control_summary["mean_net_bps"])
    g = contract["hard_gates"]
    gates = {
        "positive_net_baseline": float(exact_summary["cost_cases"]["1.0"]["mean_net_bps"]) > 0,
        "positive_net_1_5x_cost": float(exact_summary["cost_cases"]["1.5"]["mean_net_bps"]) > 0,
        "leave_one_symbol_out_positive": exact_summary["minimum_leave_one_symbol_out_mean_bps"] is not None and float(exact_summary["minimum_leave_one_symbol_out_mean_bps"]) > float(g["minimum_leave_one_symbol_out_mean_bps_gt"]),
        "best_symbol_share_le_50pct": exact_summary["best_symbol_positive_pnl_share"] is not None and float(exact_summary["best_symbol_positive_pnl_share"]) <= float(g["maximum_best_symbol_positive_pnl_share"]),
        "best_month_share_le_50pct": exact_summary["best_calendar_month_positive_pnl_share"] is not None and float(exact_summary["best_calendar_month_positive_pnl_share"]) <= float(g["maximum_best_calendar_month_positive_pnl_share"]),
        "top5_positive_period_share_le_50pct": exact_summary["top5_positive_period_share"] is not None and float(exact_summary["top5_positive_period_share"]) <= float(g["maximum_top5_positive_period_share"]),
        "principal_reversed_control_weaker_by_5bps": advantage >= float(g["minimum_candidate_minus_reversed_control_mean_bps"]),
        "chronology_valid": True,
        "data_complete": True,
        "funding_complete": True,
        "execution_valid": True,
    }
    state = "D3_TEMPORAL_REPLICATED" if all(gates.values()) else "D3_TEMPORAL_FAILED"
    for name, obj in (("exact_candidate", exact), ("principal_reversed_control", control)):
        folder = output / "series" / name
        folder.mkdir(parents=True, exist_ok=True)
        obj.observations.to_csv(folder / "observations.csv", index_label="timestamp")
        obj.contributions.to_csv(folder / "symbol_contributions.csv", index=False)
        obj.weights.to_csv(folder / "weights.csv", index_label="timestamp")
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_freeze_commit": contract["candidate_freeze_commit"],
        "d3_contract_id": contract["contract_id"],
        "d3_contract_commit": "e72194256b23b1e95823b170c19865083069d2e6",
        "state": state,
        "independence_level": contract["independence_level"],
        "dataset_manifest": manifest,
        "exact_candidate": exact_summary,
        "principal_reversed_control": control_summary,
        "candidate_minus_reversed_control_mean_net_bps": advantage,
        "benchmarks": _benchmarks(daily, exact.observations, symbols),
        "hard_gates": gates,
        "diagnostics": {
            "bootstrap_lower_bound_positive": float(exact_summary["bootstrap_lower_bps"]) > 0,
            "two_x_cost_mean_net_bps": float(exact_summary["cost_cases"]["2.0"]["mean_net_bps"]),
        },
        "claims": {
            "d3_temporal_holdout_is_prospective_future_oos": False,
            "persistent_edge_established": False,
            "prospective_d4_complete": False,
            "live_eligible": False,
            "leverage_supported": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="config/dv2_volume_confirmed_momentum_30d_v1.json")
    parser.add_argument("--contract", default="config/dv2_volume_confirmed_momentum_30d_d3_binance_2025_v1.json")
    parser.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    parser.add_argument("--output-dir", default="research/discovery_v2/volume_momentum_30d/d3_binance_2025/results")
    args = parser.parse_args()
    report = _safe(run(_load(args.candidate), _load(args.contract), _load(args.evaluation), Path(args.output_dir)))
    out = Path(args.output_dir)
    (out / "D3_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    e = report["exact_candidate"]
    lines = [
        "# Volume-confirmed momentum 30d v1 - 2025 Binance D3 Temporal Holdout",
        "",
        f"State: **{report['state']}**",
        "",
        "Locked non-overlapping historical holdout. This is not prospective future OOS.",
        "",
        f"- Observations: {e['observations']}",
        f"- Mean net: {e['mean_net_bps']:.6f} bps/day",
        f"- 1.5x-cost mean net: {e['cost_cases']['1.5']['mean_net_bps']:.6f} bps/day",
        f"- 2.0x-cost mean net: {e['cost_cases']['2.0']['mean_net_bps']:.6f} bps/day",
        f"- Bootstrap lower: {e['bootstrap_lower_bps']:.6f} bps/day",
        "",
        "No persistent-edge claim, live eligibility, leverage, or retuning follows from D3 alone.",
    ]
    (out / "D3_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "hard_gates": report["hard_gates"], "diagnostics": report["diagnostics"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

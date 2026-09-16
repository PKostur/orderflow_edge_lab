from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.binance_history import fetch_binance_usdm_funding_history, fetch_binance_usdm_klines
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun, btc_residual_shock_reversal, variant_summary


START = "2026-01-01T00:00:00Z"
END = "2026-09-12T00:00:00Z"


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
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
        "start": frame.index.min().isoformat(),
        "end": frame.index.max().isoformat(),
    }


def _validate(frame: pd.DataFrame, label: str) -> None:
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        raise RuntimeError(f"{label}: missing/invalid history")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise RuntimeError(f"{label}: duplicate/non-monotonic timestamps")


def _dense(run: VariantRun, symbols: list[str]) -> VariantRun:
    obs = run.observations.copy()
    existing = run.contributions.copy()
    keyed = {}
    if not existing.empty:
        keyed = {
            (pd.Timestamp(row.timestamp), str(row.symbol)): float(row.net_contribution_bps)
            for row in existing.itertuples(index=False)
        }
    rows = []
    for timestamp in obs.index:
        for symbol in symbols:
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "net_contribution_bps": keyed.get((pd.Timestamp(timestamp), symbol), 0.0),
                }
            )
    return VariantRun(obs, pd.DataFrame(rows))


def _fetch(candidate: Mapping[str, Any], output: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, Any]]:
    symbols = list(candidate["universe"]["symbols"])
    daily: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    manifest: dict[str, Any] = {
        "source": "Binance public USD-M futures REST",
        "independence_level": "D2",
        "start_utc": START,
        "end_utc_exclusive": END,
        "symbols": symbols,
        "files": {},
    }
    for symbol in symbols:
        prices = fetch_binance_usdm_klines(symbol, "1d", START, END)
        funds = fetch_binance_usdm_funding_history(symbol, START, END)
        _validate(prices, f"{symbol} prices")
        _validate(funds, f"{symbol} funding")
        daily[symbol] = prices
        funding[symbol] = funds
        manifest["files"][f"{symbol}:1d"] = _write_frame(prices, output / "data" / "daily" / f"{symbol}_1d.csv")
        manifest["files"][f"{symbol}:funding"] = _write_frame(funds, output / "data" / "funding" / f"{symbol}_funding.csv")
    manifest_path = output / "data" / "dataset_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(_json_safe(manifest), indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_sha256"] = _sha256(manifest_path)
    return daily, funding, manifest


def _benchmarks(daily: Mapping[str, pd.DataFrame], candidate_obs: pd.DataFrame, symbols: list[str]) -> dict[str, Any]:
    opens = pd.concat({s: daily[s]["open"].astype(float) for s in symbols}, axis=1, join="inner").dropna().sort_index()
    next_ret = opens.shift(-1) / opens - 1.0
    idx = candidate_obs.index.intersection(next_ret.index)
    btc = next_ret.loc[idx, "BTC_USDT"].dropna()
    alts = [s for s in symbols if s != "BTC_USDT"]
    equal_alts = next_ret.loc[idx, alts].mean(axis=1).dropna()
    return {
        "btc_open_to_open": {
            "observations": int(len(btc)),
            "mean_bps": float(btc.mean() * 10_000.0),
            "compounded_return": float((1.0 + btc).prod() - 1.0),
        },
        "equal_weight_nine_alts_open_to_open": {
            "observations": int(len(equal_alts)),
            "mean_bps": float(equal_alts.mean() * 10_000.0),
            "compounded_return": float((1.0 + equal_alts).prod() - 1.0),
        },
    }


def run(candidate: Mapping[str, Any], evaluation: Mapping[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    daily, funding, manifest = _fetch(candidate, output)
    symbols = list(candidate["universe"]["symbols"])
    lookback = int(candidate["signal"]["beta_lookback_completed_days"])
    side_cost = float(candidate["execution"]["baseline_round_trip_cost_bps"]) / 2.0

    exact = _dense(
        btc_residual_shock_reversal(
            daily,
            symbols=symbols,
            funding_frames=funding,
            beta_lookback_days=lookback,
            quantile_fraction=float(candidate["signal"]["quantile_fraction"]),
            side_cost_bps=side_cost,
            reverse=True,
        ),
        symbols,
    )
    reversed_control = _dense(
        btc_residual_shock_reversal(
            daily,
            symbols=symbols,
            funding_frames=funding,
            beta_lookback_days=lookback,
            quantile_fraction=float(candidate["signal"]["quantile_fraction"]),
            side_cost_bps=side_cost,
            reverse=False,
        ),
        symbols,
    )
    raw_momentum = _dense(
        btc_residual_shock_reversal(
            daily,
            symbols=symbols,
            funding_frames=funding,
            beta_lookback_days=lookback,
            quantile_fraction=float(candidate["signal"]["quantile_fraction"]),
            side_cost_bps=side_cost,
            reverse=True,
            raw_return_control=True,
        ),
        symbols,
    )
    if exact.observations.empty:
        raise RuntimeError("exact candidate produced no completed observations")

    stats_cfg = evaluation["statistics"]
    econ_cfg = evaluation["economics"]
    exact_summary = variant_summary(exact, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    reverse_summary = variant_summary(reversed_control, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)
    raw_summary = variant_summary(raw_momentum, cost_multipliers=econ_cfg["cost_multipliers"], bootstrap_cfg=stats_cfg)

    control_advantage = float(exact_summary["mean_net_bps"] - reverse_summary["mean_net_bps"])
    hard_gates = {
        "positive_net_baseline": float(exact_summary["cost_cases"]["1.0"]["mean_net_bps"]) > 0,
        "positive_net_1_5x_cost": float(exact_summary["cost_cases"]["1.5"]["mean_net_bps"]) > 0,
        "leave_one_symbol_out_positive": exact_summary["minimum_leave_one_symbol_out_mean_bps"] is not None and float(exact_summary["minimum_leave_one_symbol_out_mean_bps"]) > 0,
        "best_symbol_share_le_50pct": exact_summary["best_symbol_positive_pnl_share"] is not None and float(exact_summary["best_symbol_positive_pnl_share"]) <= 0.50,
        "best_month_share_le_50pct": exact_summary["best_calendar_month_positive_pnl_share"] is not None and float(exact_summary["best_calendar_month_positive_pnl_share"]) <= 0.50,
        "top5_positive_period_share_le_50pct": exact_summary["top5_positive_period_share"] is not None and float(exact_summary["top5_positive_period_share"]) <= 0.50,
        "principal_reversed_control_weaker_by_5bps": control_advantage >= 5.0,
        "validity": True,
    }
    state = "D2_SOURCE_REPLICATED" if all(hard_gates.values()) else "D2_SOURCE_FAILED"

    series_dir = output / "series"
    for name, run_obj in (("exact_candidate", exact), ("principal_reversed_control", reversed_control), ("raw_return_momentum_control", raw_momentum)):
        folder = series_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        run_obj.observations.to_csv(folder / "observations.csv", index_label="timestamp")
        run_obj.contributions.to_csv(folder / "symbol_contributions.csv", index=False)

    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_freeze_commit": "db6bd6b06078ed52fb244a1efadb0ae6a8177718",
        "d2_contract_commit": "69805b22002c74f37c9e1a8ba7ab3e8fd49751e6",
        "state": state,
        "independence_level": "D2",
        "dataset_manifest": manifest,
        "exact_candidate": exact_summary,
        "principal_reversed_control": reverse_summary,
        "raw_return_momentum_control": raw_summary,
        "candidate_minus_reversed_control_mean_net_bps": control_advantage,
        "benchmarks": _benchmarks(daily, exact.observations, symbols),
        "hard_gates": hard_gates,
        "bootstrap_lower_bound_positive": float(exact_summary["bootstrap_lower_bps"]) > 0,
        "reference_only_mexc_hypothesis_generation": {
            "reverse_beta45_mean_net_bps": 20.098167747588995,
            "reverse_beta45_1_5x_mean_net_bps": 13.095740563122975,
            "reverse_beta45_2x_mean_net_bps": 6.093313378656958,
            "reverse_beta45_bootstrap_lower_bps": 3.381403337218931,
        },
        "claims": {
            "d2_same_period_is_future_oos": False,
            "persistent_edge_established": False,
            "independent_engine_replication_complete": False,
            "prospective_d4_complete": False,
            "live_eligible": False,
        },
    }


def _markdown(report: Mapping[str, Any]) -> str:
    e = report["exact_candidate"]
    lines = [
        "# BTC Residual Momentum beta45 v1 — Binance D2 Replication",
        "",
        f"State: **{report['state']}**",
        "",
        "This is independent-source, same-period **D2** evidence. It is not future OOS or prospective validation.",
        "",
        f"- Observations: {e['observations']}",
        f"- Mean gross: {e['mean_gross_bps']:.6f} bps/day",
        f"- Mean cost: {e['mean_cost_bps']:.6f} bps/day",
        f"- Mean net: {e['mean_net_bps']:.6f} bps/day",
        f"- 1.5x-cost mean net: {e['cost_cases']['1.5']['mean_net_bps']:.6f} bps/day",
        f"- 2.0x-cost mean net: {e['cost_cases']['2.0']['mean_net_bps']:.6f} bps/day",
        f"- 95% block-bootstrap mean CI: [{e['bootstrap_lower_bps']:.6f}, {e['bootstrap_upper_bps']:.6f}] bps/day",
        f"- Minimum leave-one-symbol-out mean: {e['minimum_leave_one_symbol_out_mean_bps']:.6f} bps/day",
        f"- Candidate minus principal reversed-control mean: {report['candidate_minus_reversed_control_mean_net_bps']:.6f} bps/day",
        "",
        "## Hard gates",
        "",
    ]
    for key, value in report["hard_gates"].items():
        lines.append(f"- {key}: **{value}**")
    lines.extend(
        [
            "",
            "## Claims boundary",
            "",
            "A D2 pass permits only further independent-engine and prospective testing. It does not establish a persistent edge and does not enable live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="config/dv2_residual_momentum_beta45_v1.json")
    parser.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    parser.add_argument("--output-dir", default="research/discovery_v2/residual_momentum_beta45/d2_binance")
    args = parser.parse_args()
    candidate = _load(args.candidate)
    evaluation = _load(args.evaluation)
    output = Path(args.output_dir)
    report = _json_safe(run(candidate, evaluation, output))
    (output / "D2_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (output / "D2_REPORT.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"candidate_id": report["candidate_id"], "state": report["state"], "hard_gates": report["hard_gates"]}, indent=2))


if __name__ == "__main__":
    main()

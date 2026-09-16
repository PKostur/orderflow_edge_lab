from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun
from orderflow_edge_lab.discovery_v2_sprint2 import (
    evaluate_sprint2_family,
    intraday_skewness,
    low_idiosyncratic_volatility,
    same_weekday_seasonality,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        "start": frame.index.min().isoformat() if len(frame) else None,
        "end": frame.index.max().isoformat() if len(frame) else None,
    }


def _validate_chronology(frame: pd.DataFrame, label: str) -> None:
    if frame.empty:
        raise RuntimeError(f"{label}: empty frame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise RuntimeError(f"{label}: DatetimeIndex required")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise RuntimeError(f"{label}: duplicate or non-monotonic timestamps")


def _fetch_all(protocol: Mapping[str, Any], data_dir: Path) -> tuple[
    dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, Any]
]:
    cfg = protocol["data"]
    symbols = list(cfg["symbols"])
    start = str(cfg["development_start_utc"])
    end = str(cfg["development_end_utc_exclusive"])
    daily: dict[str, pd.DataFrame] = {}
    four_hour: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    manifest: dict[str, Any] = {
        "protocol": protocol["protocol"],
        "source": "MEXC public REST",
        "venue": cfg["venue"],
        "requested_start_utc": start,
        "requested_end_utc_exclusive": end,
        "actual_public_funding_required": bool(cfg["actual_public_funding_required"]),
        "survivorship_warning": cfg["survivorship_warning"],
        "files": {},
    }
    for symbol in symbols:
        d = fetch_mexc_futures_klines(symbol, "1d", start, end, request_pause_seconds=0.10)
        h4 = fetch_mexc_futures_klines(symbol, "4h", start, end, request_pause_seconds=0.10)
        f = fetch_mexc_funding_history(symbol, start, end, page_size=1000, max_pages=20)
        _validate_chronology(d, f"{symbol} daily")
        _validate_chronology(h4, f"{symbol} 4h")
        _validate_chronology(f, f"{symbol} funding")
        if len(d) < 120:
            raise RuntimeError(f"{symbol}: insufficient daily history: {len(d)}")
        if len(h4) < 720:
            raise RuntimeError(f"{symbol}: insufficient 4h history: {len(h4)}")
        if len(f) < 100:
            raise RuntimeError(f"{symbol}: insufficient funding history: {len(f)}")
        daily[symbol], four_hour[symbol], funding[symbol] = d, h4, f
        manifest["files"][f"{symbol}:1d"] = _write_frame(d, data_dir / "daily" / f"{symbol}_1d.csv")
        manifest["files"][f"{symbol}:4h"] = _write_frame(h4, data_dir / "four_hour" / f"{symbol}_4h.csv")
        manifest["files"][f"{symbol}:funding"] = _write_frame(f, data_dir / "funding" / f"{symbol}_funding.csv")
    manifest_path = data_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(_json_safe(manifest), indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_sha256"] = _sha256(manifest_path)
    return daily, four_hour, funding, manifest


def _dense(run: VariantRun, symbols: list[str]) -> VariantRun:
    obs = run.observations.copy()
    existing = run.contributions.copy()
    if existing.empty:
        existing = pd.DataFrame(columns=["timestamp", "symbol", "net_contribution_bps"])
    keyed = {
        (pd.Timestamp(row.timestamp), str(row.symbol)): float(row.net_contribution_bps)
        for row in existing.itertuples(index=False)
    }
    rows = [
        {
            "timestamp": timestamp,
            "symbol": symbol,
            "net_contribution_bps": keyed.get((pd.Timestamp(timestamp), symbol), 0.0),
        }
        for timestamp in obs.index
        for symbol in symbols
    ]
    return VariantRun(obs, pd.DataFrame(rows))


def _persist_family(
    family: str,
    variants: Mapping[str, VariantRun],
    controls: Mapping[str, VariantRun],
    output_dir: Path,
) -> None:
    base = output_dir / "series" / family
    for category, runs in (("variants", variants), ("controls", controls)):
        for run_id, run in runs.items():
            folder = base / category / run_id
            folder.mkdir(parents=True, exist_ok=True)
            run.observations.to_csv(folder / "observations.csv", index_label="timestamp")
            run.contributions.to_csv(folder / "symbol_contributions.csv", index=False)


def _evaluate(
    variants: Mapping[str, VariantRun],
    controls: Mapping[str, VariantRun],
    ordered: list[str],
    evaluation: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    control_map = {variant_id: f"reverse_{variant_id}" for variant_id in ordered}
    return evaluate_sprint2_family(
        variants,
        controls,
        ordered_variant_ids=ordered,
        evaluation_config=evaluation,
        principal_control_for_variant=control_map,
        gate=gate,
    )


def run(protocol: Mapping[str, Any], evaluation: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    daily, four_hour, funding, manifest = _fetch_all(protocol, output_dir / "data")
    symbols = list(protocol["data"]["symbols"])
    side_cost = float(protocol["execution"]["transaction_cost_bps_per_side_on_turnover"])
    gate = protocol["family_falsification_gate"]
    reports: dict[str, Any] = {}

    cfg = protocol["families"]["same_weekday_seasonality"]
    variants: dict[str, VariantRun] = {}
    controls: dict[str, VariantRun] = {}
    ordered: list[str] = []
    for n in cfg["lookback_weeks_variants"]:
        variant_id = f"weekday_{int(n)}w"
        ordered.append(variant_id)
        variants[variant_id] = _dense(same_weekday_seasonality(
            daily, symbols=symbols, funding_frames=funding,
            lookback_weeks=int(n), common_warmup_weeks=int(cfg["common_comparison_warmup_weeks"]),
            side_cost_bps=side_cost, reverse=False,
        ), symbols)
        controls[f"reverse_{variant_id}"] = _dense(same_weekday_seasonality(
            daily, symbols=symbols, funding_frames=funding,
            lookback_weeks=int(n), common_warmup_weeks=int(cfg["common_comparison_warmup_weeks"]),
            side_cost_bps=side_cost, reverse=True,
        ), symbols)
    reports["same_weekday_seasonality"] = _evaluate(variants, controls, ordered, evaluation, gate)
    _persist_family("same_weekday_seasonality", variants, controls, output_dir)

    cfg = protocol["families"]["low_idiosyncratic_volatility"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["lookback_days_variants"]:
        variant_id = f"low_idiov_{int(n)}d"
        ordered.append(variant_id)
        variants[variant_id] = _dense(low_idiosyncratic_volatility(
            daily, symbols=symbols, funding_frames=funding,
            lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            side_cost_bps=side_cost, reverse=False,
        ), symbols)
        controls[f"reverse_{variant_id}"] = _dense(low_idiosyncratic_volatility(
            daily, symbols=symbols, funding_frames=funding,
            lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            side_cost_bps=side_cost, reverse=True,
        ), symbols)
    reports["low_idiosyncratic_volatility"] = _evaluate(variants, controls, ordered, evaluation, gate)
    _persist_family("low_idiosyncratic_volatility", variants, controls, output_dir)

    cfg = protocol["families"]["intraday_skewness"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["lookback_days_variants"]:
        variant_id = f"skew_{int(n)}d"
        ordered.append(variant_id)
        variants[variant_id] = _dense(intraday_skewness(
            daily, four_hour, symbols=symbols, funding_frames=funding,
            lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            side_cost_bps=side_cost, reverse=False,
        ), symbols)
        controls[f"reverse_{variant_id}"] = _dense(intraday_skewness(
            daily, four_hour, symbols=symbols, funding_frames=funding,
            lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            side_cost_bps=side_cost, reverse=True,
        ), symbols)
    reports["intraday_skewness"] = _evaluate(variants, controls, ordered, evaluation, gate)
    _persist_family("intraday_skewness", variants, controls, output_dir)

    return {
        "protocol": protocol["protocol"],
        "protocol_frozen_at_utc": protocol["frozen_at_utc"],
        "execution_commit": os.getenv("GITHUB_SHA"),
        "independence_level": "D0",
        "dataset_manifest": manifest,
        "families": reports,
        "claims": {
            "persistent_edge_established": False,
            "live_execution_supported": False,
            "leverage_supported": False,
            "beta45_modified": False,
        },
    }


def _write_markdown(report: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Discovery v2 Sprint 2 - D0 Falsification Report",
        "",
        f"Protocol: `{report['protocol']}`",
        f"Frozen at: `{report['protocol_frozen_at_utc']}`",
        f"Execution commit: `{report.get('execution_commit')}`",
        "",
        "Same-source historical D0 evidence only. No result here establishes a persistent edge or authorizes live trading.",
        "",
    ]
    for family_name, family in report["families"].items():
        lines += [
            f"## {family_name}",
            "",
            f"- State: **{family['state']}**",
            f"- Sprint 2 selected variant: `{family.get('sprint2_selected_variant')}`",
            f"- Baseline-positive variants: {', '.join(family.get('baseline_positive_variants', [])) or 'none'}",
            f"- Stable 1.5x neighborhood: {', '.join(family.get('stable_neighborhood', [])) or 'none'}",
            f"- Selected advantage vs reversed control: {family.get('sprint2_selected_advantage_bps')} bps/observation",
            f"- Hard checks: `{json.dumps(family.get('sprint2_hard_checks', {}), sort_keys=True)}`",
            "",
        ]
    lines += [
        "## Claims boundary",
        "",
        "- Failed families close under this frozen Sprint 2 hypothesis set.",
        "- Any D0 survivor is only REPLICATION_PENDING and must receive a new candidate freeze before D2/D3/D4.",
        "- No parameter grid expansion or post-result retuning is permitted.",
        "- beta45 remains unchanged.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="config/discovery_v2_sprint2_v1.json")
    parser.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    parser.add_argument("--output-dir", default="research/discovery_v2/sprint2/results")
    args = parser.parse_args()
    protocol = _load(args.protocol)
    evaluation = _load(args.evaluation)
    output_dir = Path(args.output_dir)
    report = _json_safe(run(protocol, evaluation, output_dir))
    report_path = output_dir / "sprint2_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(report, output_dir / "SPRINT2_REPORT.md")
    print(json.dumps({name: family["state"] for name, family in report["families"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

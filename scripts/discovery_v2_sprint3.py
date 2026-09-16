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
from orderflow_edge_lab.discovery_v2_sprint3 import (
    btc_downtrend_intraday_skewness,
    evaluate_sprint3_family,
    funding_carry_spread,
    volume_confirmed_momentum,
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
        {"timestamp": timestamp, "symbol": symbol, "net_contribution_bps": keyed.get((pd.Timestamp(timestamp), symbol), 0.0)}
        for timestamp in obs.index
        for symbol in symbols
    ]
    return VariantRun(obs, pd.DataFrame(rows))


def _persist_family(family: str, variants: Mapping[str, VariantRun], controls: Mapping[str, VariantRun], output_dir: Path) -> None:
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
    return evaluate_sprint3_family(
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

    cfg = protocol["families"]["btc_downtrend_intraday_skewness"]
    variants: dict[str, VariantRun] = {}
    controls: dict[str, VariantRun] = {}
    ordered: list[str] = []
    for n in cfg["lookback_days_variants"]:
        variant_id = f"downtrend_skew_{int(n)}d"
        ordered.append(variant_id)
        kwargs = dict(
            daily_frames=daily,
            four_hour_frames=four_hour,
            symbols=symbols,
            funding_frames=funding,
            lookback_days=int(n),
            common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            btc_trend_lookback_days=int(cfg["btc_trend_lookback_days"]),
            side_cost_bps=side_cost,
        )
        variants[variant_id] = _dense(btc_downtrend_intraday_skewness(**kwargs, reverse=False), symbols)
        controls[f"reverse_{variant_id}"] = _dense(btc_downtrend_intraday_skewness(**kwargs, reverse=True), symbols)
    reports["btc_downtrend_intraday_skewness"] = _evaluate(variants, controls, ordered, evaluation, gate)
    _persist_family("btc_downtrend_intraday_skewness", variants, controls, output_dir)

    cfg = protocol["families"]["funding_carry_spread"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["lookback_days_variants"]:
        variant_id = f"funding_carry_{int(n)}d"
        ordered.append(variant_id)
        kwargs = dict(
            daily_frames=daily,
            funding_frames=funding,
            symbols=symbols,
            lookback_days=int(n),
            common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            minimum_settlements_per_day=int(cfg["minimum_settlements_per_day_in_lookback"]),
            side_cost_bps=side_cost,
        )
        variants[variant_id] = _dense(funding_carry_spread(**kwargs, reverse=False), symbols)
        controls[f"reverse_{variant_id}"] = _dense(funding_carry_spread(**kwargs, reverse=True), symbols)
    reports["funding_carry_spread"] = _evaluate(variants, controls, ordered, evaluation, gate)
    _persist_family("funding_carry_spread", variants, controls, output_dir)

    cfg = protocol["families"]["volume_confirmed_momentum"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["volume_baseline_days_variants"]:
        variant_id = f"volume_momentum_{int(n)}d"
        ordered.append(variant_id)
        kwargs = dict(
            daily_frames=daily,
            symbols=symbols,
            funding_frames=funding,
            volume_baseline_days=int(n),
            common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            side_cost_bps=side_cost,
        )
        variants[variant_id] = _dense(volume_confirmed_momentum(**kwargs, reverse=False), symbols)
        controls[f"reverse_{variant_id}"] = _dense(volume_confirmed_momentum(**kwargs, reverse=True), symbols)
    reports["volume_confirmed_momentum"] = _evaluate(variants, controls, ordered, evaluation, gate)
    _persist_family("volume_confirmed_momentum", variants, controls, output_dir)

    return {
        "protocol": protocol["protocol"],
        "protocol_frozen_at_utc": protocol["frozen_at_utc"],
        "protocol_freeze_commit": "d5d8ac6f8964a12a15333e4c82e049bca9f478a4",
        "execution_commit": os.getenv("GITHUB_SHA"),
        "independence_level": "D0",
        "dataset_manifest": manifest,
        "families": reports,
        "claims": {
            "persistent_edge_established": False,
            "live_execution_supported": False,
            "leverage_supported": False,
            "beta45_modified": False,
            "sprint2_failed_family_modified": False,
        },
    }


def _write_markdown(report: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Discovery v2 Sprint 3 - D0 Falsification Report",
        "",
        f"Protocol: `{report['protocol']}`",
        f"Freeze commit: `{report['protocol_freeze_commit']}`",
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
            f"- Selected variant if survived: `{family.get('sprint3_selected_variant')}`",
            f"- Baseline-positive variants: {', '.join(family.get('baseline_positive_variants', [])) or 'none'}",
            f"- Stable 1.5x neighborhood: {', '.join(family.get('stable_neighborhood', [])) or 'none'}",
            f"- Selected advantage vs reversed control: {family.get('sprint3_selected_advantage_bps')} bps/observation",
            f"- Hard checks: `{json.dumps(family.get('sprint3_hard_checks', {}), sort_keys=True)}`",
            "",
        ]
    lines += [
        "## Claims boundary",
        "",
        "- The BTC-downtrend/skew family is a new D0 hypothesis generated from prior regime diagnostics, not a rescue of Sprint 2.",
        "- Failed families close under this frozen Sprint 3 hypothesis set.",
        "- Any D0 survivor is only REPLICATION_PENDING and requires a new candidate freeze plus independent reproduction and D2/D3/D4 evidence.",
        "- No parameter-grid expansion or post-result retuning is permitted.",
        "- beta45 and all Sprint 2 family definitions remain unchanged.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="config/discovery_v2_sprint3_v1.json")
    parser.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    parser.add_argument("--output-dir", default="research/discovery_v2/sprint3/results")
    args = parser.parse_args()
    protocol = _load(args.protocol)
    evaluation = _load(args.evaluation)
    output_dir = Path(args.output_dir)
    report = _json_safe(run(protocol, evaluation, output_dir))
    report_path = output_dir / "sprint3_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(report, output_dir / "SPRINT3_REPORT.md")
    print(json.dumps({name: family["state"] for name, family in report["families"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

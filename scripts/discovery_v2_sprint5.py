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
from orderflow_edge_lab.discovery_v2_sprint5 import (
    amihud_liquidity_premium,
    close_location_pressure,
    donchian_channel_position_continuation,
    evaluate_sprint5_family,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

FREEZE_COMMIT = "6a8b07ab7a9d8d3b629afc2a5f62e2c02782f273"


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


def _fetch_all(protocol: Mapping[str, Any], data_dir: Path):
    cfg = protocol["data"]; symbols = list(cfg["symbols"])
    start, end = str(cfg["development_start_utc"]), str(cfg["development_end_utc_exclusive"])
    daily, funding = {}, {}
    manifest = {"protocol": protocol["protocol"], "source": "MEXC public REST", "venue": cfg["venue"],
                "requested_start_utc": start, "requested_end_utc_exclusive": end,
                "actual_public_funding_required": bool(cfg["actual_public_funding_required"]),
                "survivorship_warning": cfg["survivorship_warning"], "files": {}}
    for symbol in symbols:
        d = fetch_mexc_futures_klines(symbol, "1d", start, end, request_pause_seconds=0.10)
        f = fetch_mexc_funding_history(symbol, start, end, page_size=1000, max_pages=20)
        if d.empty or f.empty or d.index.has_duplicates or f.index.has_duplicates:
            raise RuntimeError(f"{symbol}: invalid history")
        if not d.index.is_monotonic_increasing or not f.index.is_monotonic_increasing:
            raise RuntimeError(f"{symbol}: non-monotonic history")
        required = {"open", "high", "low", "close", "volume"}
        if required.difference(d.columns):
            raise RuntimeError(f"{symbol}: missing OHLCV fields")
        if len(d) < 120 or len(f) < 100:
            raise RuntimeError(f"{symbol}: insufficient history")
        daily[symbol], funding[symbol] = d, f
        manifest["files"][f"{symbol}:1d"] = _write_frame(d, data_dir / "daily" / f"{symbol}_1d.csv")
        manifest["files"][f"{symbol}:funding"] = _write_frame(f, data_dir / "funding" / f"{symbol}_funding.csv")
    p = data_dir / "dataset_manifest.json"; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_safe(manifest), indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_sha256"] = _sha256(p)
    return daily, funding, manifest


def _dense(run: VariantRun, symbols: list[str]) -> VariantRun:
    existing = run.contributions.copy()
    if existing.empty:
        existing = pd.DataFrame(columns=["timestamp", "symbol", "net_contribution_bps"])
    keyed = {(pd.Timestamp(r.timestamp), str(r.symbol)): float(r.net_contribution_bps)
             for r in existing.itertuples(index=False)}
    rows = [{"timestamp": t, "symbol": s, "net_contribution_bps": keyed.get((pd.Timestamp(t), s), 0.0)}
            for t in run.observations.index for s in symbols]
    return VariantRun(run.observations.copy(), pd.DataFrame(rows))


def _persist(family: str, variants, controls, out: Path) -> None:
    for category, runs in (("variants", variants), ("controls", controls)):
        for rid, run in runs.items():
            folder = out / "series" / family / category / rid; folder.mkdir(parents=True, exist_ok=True)
            run.observations.to_csv(folder / "observations.csv", index_label="timestamp")
            run.contributions.to_csv(folder / "symbol_contributions.csv", index=False)


def _evaluate(variants, controls, ordered, evaluation, gate):
    return evaluate_sprint5_family(
        variants, controls, ordered_variant_ids=ordered, evaluation_config=evaluation,
        principal_control_for_variant={v: f"reverse_{v}" for v in ordered}, gate=gate,
    )


def run(protocol: Mapping[str, Any], evaluation: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    daily, funding, manifest = _fetch_all(protocol, output_dir / "data")
    symbols = list(protocol["data"]["symbols"]); side_cost = float(protocol["execution"]["transaction_cost_bps_per_side_on_turnover"])
    gate = protocol["family_falsification_gate"]; reports = {}

    cfg = protocol["families"]["donchian_channel_position_continuation"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["channel_lookback_days_variants"]:
        vid = f"donchian_position_{int(n)}d"; ordered.append(vid)
        kwargs = dict(daily_frames=daily, symbols=symbols, funding_frames=funding,
                      channel_lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]), side_cost_bps=side_cost)
        variants[vid] = _dense(donchian_channel_position_continuation(**kwargs, reverse=False), symbols)
        controls[f"reverse_{vid}"] = _dense(donchian_channel_position_continuation(**kwargs, reverse=True), symbols)
    reports["donchian_channel_position_continuation"] = _evaluate(variants, controls, ordered, evaluation, gate); _persist("donchian_channel_position_continuation", variants, controls, output_dir)

    cfg = protocol["families"]["amihud_liquidity_premium"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["lookback_days_variants"]:
        vid = f"amihud_liquidity_{int(n)}d"; ordered.append(vid)
        kwargs = dict(daily_frames=daily, symbols=symbols, funding_frames=funding,
                      lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]), side_cost_bps=side_cost)
        variants[vid] = _dense(amihud_liquidity_premium(**kwargs, reverse=False), symbols)
        controls[f"reverse_{vid}"] = _dense(amihud_liquidity_premium(**kwargs, reverse=True), symbols)
    reports["amihud_liquidity_premium"] = _evaluate(variants, controls, ordered, evaluation, gate); _persist("amihud_liquidity_premium", variants, controls, output_dir)

    cfg = protocol["families"]["close_location_pressure"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["lookback_days_variants"]:
        vid = f"close_location_{int(n)}d"; ordered.append(vid)
        kwargs = dict(daily_frames=daily, symbols=symbols, funding_frames=funding,
                      lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]), side_cost_bps=side_cost)
        variants[vid] = _dense(close_location_pressure(**kwargs, reverse=False), symbols)
        controls[f"reverse_{vid}"] = _dense(close_location_pressure(**kwargs, reverse=True), symbols)
    reports["close_location_pressure"] = _evaluate(variants, controls, ordered, evaluation, gate); _persist("close_location_pressure", variants, controls, output_dir)

    return {"protocol": protocol["protocol"], "protocol_frozen_at_utc": protocol["frozen_at_utc"],
            "protocol_freeze_commit": FREEZE_COMMIT, "execution_commit": os.getenv("GITHUB_SHA"), "independence_level": "D0",
            "dataset_manifest": manifest, "families": reports,
            "claims": {"persistent_edge_established": False, "live_execution_supported": False,
                       "leverage_supported": False, "existing_candidates_modified": False, "failed_prior_family_rescued": False}}


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--protocol", default="config/discovery_v2_sprint5_v1.json")
    p.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    p.add_argument("--output-dir", default="research/discovery_v2/sprint5/results"); a = p.parse_args()
    protocol, evaluation, out = _load(a.protocol), _load(a.evaluation), Path(a.output_dir)
    report = _safe(run(protocol, evaluation, out)); (out / "sprint5_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Discovery v2 Sprint 5 - D0 Falsification Report", "", f"Freeze commit: `{FREEZE_COMMIT}`", "",
             "Same-source D0 evidence only. No result establishes persistent edge or live eligibility.", ""]
    for name, fam in report["families"].items():
        lines += [f"## {name}", "", f"- State: **{fam['state']}**", f"- Selected: `{fam.get('sprint5_selected_variant')}`",
                  f"- Baseline-positive: {', '.join(fam.get('baseline_positive_variants', [])) or 'none'}",
                  f"- Stable 1.5x neighborhood: {', '.join(fam.get('stable_neighborhood', [])) or 'none'}",
                  f"- Hard checks: `{json.dumps(fam.get('sprint5_hard_checks', {}), sort_keys=True)}`", ""]
    (out / "SPRINT5_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v["state"] for k, v in report["families"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__": main()

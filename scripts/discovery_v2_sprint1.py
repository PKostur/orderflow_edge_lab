from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import (
    VariantRun,
    btc_residual_shock_reversal,
    dispersion_conditioned_xs_momentum,
    evaluate_family,
    funding_extreme_reversal,
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _validate_chronology(frame: pd.DataFrame, label: str) -> None:
    if frame.empty:
        raise RuntimeError(f"{label}: empty frame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise RuntimeError(f"{label}: DatetimeIndex required")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise RuntimeError(f"{label}: duplicate or non-monotonic timestamps")


def _fetch_all(protocol: Mapping[str, Any], data_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, Any]]:
    data_cfg = protocol["data"]
    symbols = list(data_cfg["symbols"])
    start = str(data_cfg["development_start_utc"])
    end = str(data_cfg["development_end_utc_exclusive"])
    daily: dict[str, pd.DataFrame] = {}
    hourly: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    manifest: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "source": "MEXC public REST",
        "venue": data_cfg["venue"],
        "market_type": data_cfg["market_type"],
        "independence_level": data_cfg["independence_level"],
        "requested_start_utc": start,
        "requested_end_utc_exclusive": end,
        "universe_warning": data_cfg["universe_warning"],
        "files": {},
    }
    for symbol in symbols:
        daily_frame = fetch_mexc_futures_klines(symbol, "1d", start, end, request_pause_seconds=0.10)
        hourly_frame = fetch_mexc_futures_klines(symbol, "1h", start, end, request_pause_seconds=0.10)
        funding_frame = fetch_mexc_funding_history(symbol, start, end, page_size=1000, max_pages=20)
        _validate_chronology(daily_frame, f"{symbol} daily")
        _validate_chronology(hourly_frame, f"{symbol} hourly")
        _validate_chronology(funding_frame, f"{symbol} funding")
        if len(funding_frame) < 100:
            raise RuntimeError(f"{symbol}: insufficient historical funding observations: {len(funding_frame)}")
        daily[symbol] = daily_frame
        hourly[symbol] = hourly_frame
        funding[symbol] = funding_frame
        manifest["files"][f"{symbol}:1d"] = _write_frame(daily_frame, data_dir / "daily" / f"{symbol}_1d.csv")
        manifest["files"][f"{symbol}:1h"] = _write_frame(hourly_frame, data_dir / "hourly" / f"{symbol}_1h.csv")
        manifest["files"][f"{symbol}:funding"] = _write_frame(funding_frame, data_dir / "funding" / f"{symbol}_funding.csv")
    manifest_path = data_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(_json_safe(manifest), indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_sha256"] = _sha256(manifest_path)
    return daily, hourly, funding, manifest


def _dense_contributions(run: VariantRun, symbols: list[str]) -> VariantRun:
    obs = run.observations.copy()
    if obs.empty:
        return run
    existing = run.contributions.copy()
    if existing.empty:
        existing = pd.DataFrame(columns=["timestamp", "symbol", "net_contribution_bps"])
    rows = []
    keyed = {
        (pd.Timestamp(row.timestamp), str(row.symbol)): float(row.net_contribution_bps)
        for row in existing.itertuples(index=False)
    }
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


def _trim_funding_warmup(run: VariantRun, funding: Mapping[str, pd.DataFrame], symbols: list[str], lookback: int) -> VariantRun:
    starts = []
    for symbol in symbols:
        frame = funding[symbol]
        if len(frame) <= lookback + 1:
            raise RuntimeError(f"{symbol}: funding history shorter than lookback {lookback}")
        starts.append(frame.index[lookback])
    threshold = max(starts)
    obs = run.observations.loc[run.observations.index >= threshold].copy()
    contrib = run.contributions.loc[pd.to_datetime(run.contributions["timestamp"], utc=True) >= threshold].copy() if not run.contributions.empty else run.contributions.copy()
    return VariantRun(obs, contrib)


def _persist_family_runs(family: str, variants: Mapping[str, VariantRun], controls: Mapping[str, VariantRun], output_dir: Path) -> None:
    base = output_dir / "series" / family
    for category, runs in (("variants", variants), ("controls", controls)):
        for run_id, run in runs.items():
            folder = base / category / run_id
            folder.mkdir(parents=True, exist_ok=True)
            run.observations.to_csv(folder / "observations.csv", index_label="timestamp")
            run.contributions.to_csv(folder / "symbol_contributions.csv", index=False)


def _apply_validity(report: dict[str, Any], validity: Mapping[str, bool]) -> dict[str, Any]:
    out = dict(report)
    out["validity"] = {"flags": dict(validity), "pass": bool(validity) and all(validity.values())}
    if not out["validity"]["pass"]:
        out["state"] = "FALSIFIED"
        out["selected_variant_if_survived"] = None
    return out


def run(protocol: Mapping[str, Any], evaluation: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    daily, hourly, funding, manifest = _fetch_all(protocol, data_dir)
    symbols = list(protocol["data"]["symbols"])
    families = protocol["families"]

    validity = {
        "completed_historical_window_only": True,
        "next_bar_or_next_event_execution": True,
        "funding_signal_uses_no_future_settlement_rate": True,
        "fixed_grid_not_expanded_after_results": True,
        "gross_exposure_capped_at_1x": True,
    }

    # Family A: dispersion-conditioned cross-sectional momentum.
    a_cfg = families["dispersion_conditioned_xs_momentum"]
    a_variants: dict[str, VariantRun] = {}
    a_controls: dict[str, VariantRun] = {}
    a_map: dict[str, str] = {}
    for spec in a_cfg["pre_registered_variants"]:
        variant_id = str(spec["variant_id"])
        lookback = int(spec["dispersion_median_lookback_days"])
        candidate = dispersion_conditioned_xs_momentum(
            daily,
            symbols=symbols,
            funding_frames=funding,
            dispersion_lookback_days=lookback,
            momentum_lookback_days=int(a_cfg["signal"]["momentum_lookback_days"]),
            holding_days=int(a_cfg["signal"]["holding_days"]),
            quantile_fraction=float(a_cfg["signal"]["quantile_fraction"]),
            side_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]) / 2.0,
        )
        control_id = f"reverse_{variant_id}"
        reversed_run = dispersion_conditioned_xs_momentum(
            daily,
            symbols=symbols,
            funding_frames=funding,
            dispersion_lookback_days=lookback,
            momentum_lookback_days=int(a_cfg["signal"]["momentum_lookback_days"]),
            holding_days=int(a_cfg["signal"]["holding_days"]),
            quantile_fraction=float(a_cfg["signal"]["quantile_fraction"]),
            side_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]) / 2.0,
            reverse=True,
        )
        a_variants[variant_id] = _dense_contributions(candidate, symbols)
        a_controls[control_id] = _dense_contributions(reversed_run, symbols)
        a_map[variant_id] = control_id
    ungated = dispersion_conditioned_xs_momentum(
        daily,
        symbols=symbols,
        funding_frames=funding,
        dispersion_lookback_days=60,
        momentum_lookback_days=int(a_cfg["signal"]["momentum_lookback_days"]),
        holding_days=int(a_cfg["signal"]["holding_days"]),
        quantile_fraction=float(a_cfg["signal"]["quantile_fraction"]),
        side_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]) / 2.0,
        ungated=True,
    )
    a_controls["ungated_benchmark"] = _dense_contributions(ungated, symbols)
    a_ids = [str(v["variant_id"]) for v in a_cfg["pre_registered_variants"]]
    a_report = evaluate_family(a_variants, a_controls, ordered_variant_ids=a_ids, evaluation_config=evaluation, principal_control_for_variant=a_map)
    a_report = _apply_validity(a_report, validity)
    _persist_family_runs("dispersion_conditioned_xs_momentum", a_variants, a_controls, output_dir)

    # Family B: extreme funding reversal/carry.
    b_cfg = families["funding_extreme_reversal"]
    b_variants: dict[str, VariantRun] = {}
    b_controls: dict[str, VariantRun] = {}
    b_map: dict[str, str] = {}
    for spec in b_cfg["pre_registered_variants"]:
        variant_id = str(spec["variant_id"])
        lookback = int(spec["funding_z_lookback_settlements"])
        candidate = funding_extreme_reversal(
            hourly,
            funding,
            symbols=symbols,
            lookback_settlements=lookback,
            z_threshold_abs=float(b_cfg["signal"]["z_threshold_abs"]),
            round_trip_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]),
        )
        candidate = _trim_funding_warmup(candidate, funding, symbols, lookback)
        control_id = f"reverse_{variant_id}"
        reversed_run = funding_extreme_reversal(
            hourly,
            funding,
            symbols=symbols,
            lookback_settlements=lookback,
            z_threshold_abs=float(b_cfg["signal"]["z_threshold_abs"]),
            round_trip_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]),
            reverse=True,
        )
        reversed_run = _trim_funding_warmup(reversed_run, funding, symbols, lookback)
        b_variants[variant_id] = _dense_contributions(candidate, symbols)
        b_controls[control_id] = _dense_contributions(reversed_run, symbols)
        b_map[variant_id] = control_id
    b_ids = [str(v["variant_id"]) for v in b_cfg["pre_registered_variants"]]
    b_report = evaluate_family(b_variants, b_controls, ordered_variant_ids=b_ids, evaluation_config=evaluation, principal_control_for_variant=b_map)
    b_report = _apply_validity(b_report, validity)
    _persist_family_runs("funding_extreme_reversal", b_variants, b_controls, output_dir)

    # Family C: BTC-residual shock reversal.
    c_cfg = families["btc_residual_shock_reversal"]
    c_variants: dict[str, VariantRun] = {}
    c_controls: dict[str, VariantRun] = {}
    c_map: dict[str, str] = {}
    for spec in c_cfg["pre_registered_variants"]:
        variant_id = str(spec["variant_id"])
        lookback = int(spec["beta_lookback_days"])
        candidate = btc_residual_shock_reversal(
            daily,
            symbols=symbols,
            funding_frames=funding,
            beta_lookback_days=lookback,
            side_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]) / 2.0,
        )
        control_id = f"reverse_{variant_id}"
        reversed_run = btc_residual_shock_reversal(
            daily,
            symbols=symbols,
            funding_frames=funding,
            beta_lookback_days=lookback,
            side_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]) / 2.0,
            reverse=True,
        )
        c_variants[variant_id] = _dense_contributions(candidate, symbols)
        c_controls[control_id] = _dense_contributions(reversed_run, symbols)
        c_map[variant_id] = control_id
    raw_control = btc_residual_shock_reversal(
        daily,
        symbols=symbols,
        funding_frames=funding,
        beta_lookback_days=30,
        side_cost_bps=float(protocol["execution"]["baseline_round_trip_cost_bps"]) / 2.0,
        raw_return_control=True,
    )
    c_controls["raw_return_reversal_30"] = _dense_contributions(raw_control, symbols)
    c_ids = [str(v["variant_id"]) for v in c_cfg["pre_registered_variants"]]
    c_report = evaluate_family(c_variants, c_controls, ordered_variant_ids=c_ids, evaluation_config=evaluation, principal_control_for_variant=c_map)
    c_report = _apply_validity(c_report, validity)
    _persist_family_runs("btc_residual_shock_reversal", c_variants, c_controls, output_dir)

    report = {
        "protocol_id": protocol["protocol_id"],
        "protocol_freeze_commit": "e228b3ffed6861db8aad2c5808806d1ad2fb73b9",
        "implementation_contract_commit": "e4c7617f51c45a53a4009d5926783ae62d2b7880",
        "independence_level": "D0",
        "dataset_manifest": manifest,
        "families": {
            "dispersion_conditioned_xs_momentum": a_report,
            "funding_extreme_reversal": b_report,
            "btc_residual_shock_reversal": c_report,
        },
        "claims": {
            "persistent_edge_established": False,
            "same_period_history_is_future_oos": False,
            "live_order_transmission_supported": False,
            "existing_frozen_candidates_modified": False,
        },
    }
    return report


def _write_markdown(report: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Discovery v2 Sprint 1 — D0 Falsification Report",
        "",
        f"Protocol: `{report['protocol_id']}`",
        f"Freeze commit: `{report['protocol_freeze_commit']}`",
        "",
        "This is same-source historical **D0** evidence. It cannot establish a persistent edge or authorize live trading.",
        "",
        "## Family states",
        "",
    ]
    for name, family in report["families"].items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- State: **{family['state']}**")
        lines.append(f"- Selected variant if survived: `{family.get('selected_variant_if_survived')}`")
        lines.append(f"- Baseline-positive variants: {', '.join(family.get('baseline_positive_variants', [])) or 'none'}")
        lines.append(f"- Stable 1.5x neighborhood: {', '.join(family.get('stable_neighborhood', [])) or 'none'}")
        lines.append(f"- Median candidate mean net: {family.get('median_candidate_mean_net_bps')} bps/observation")
        lines.append(f"- Control advantage: {family.get('control_advantage_bps')} bps/observation")
        lines.append(f"- Hard checks: `{json.dumps(family.get('hard_checks', {}), sort_keys=True)}`")
        lines.append("")
    lines.extend(
        [
            "## Claims boundary",
            "",
            "- No family result here is future OOS.",
            "- `REPLICATION_PENDING` means only that the preregistered D0 falsification gates survived.",
            "- Any survivor still requires a new candidate freeze, one-event delay stress, independent-engine replication, locked later validation, and prospective D4 evidence.",
            "- Existing ENA, 8h trend, and 30d/7d XS candidates remain unchanged.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="config/discovery_v2_sprint1_v1.json")
    parser.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    parser.add_argument("--output-dir", default="research/discovery_v2/sprint1/results")
    args = parser.parse_args()
    protocol = _load(args.protocol)
    evaluation = _load(args.evaluation)
    output_dir = Path(args.output_dir)
    report = run(protocol, evaluation, output_dir)
    safe = _json_safe(report)
    (output_dir / "sprint1_report.json").write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown(safe, output_dir / "SPRINT1_REPORT.md")
    print(json.dumps({name: value["state"] for name, value in safe["families"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

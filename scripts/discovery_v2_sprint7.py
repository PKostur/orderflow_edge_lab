from __future__ import annotations

import argparse, hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun
from orderflow_edge_lab.discovery_v2_sprint7 import (
    vol_adjusted_short_term_reversal,
    momentum_acceleration,
    upside_downside_beta_asymmetry,
    evaluate_sprint7_family,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

FREEZE_COMMIT = "80122575a44116fff88045722b45438d43d97367"


def _load(path):
    return json.loads(Path(path).read_text())


def _safe(v):
    if isinstance(v, dict): return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.floating): v = float(v)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): return None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def _sha(path):
    h = hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()


def _write(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_index().to_csv(path, index_label="timestamp")
    return {
        "path": str(path), "sha256": _sha(path), "rows": len(frame),
        "start": frame.index.min().isoformat(), "end": frame.index.max().isoformat(),
    }


def _fetch(protocol, out):
    c = protocol["data"]; daily = {}; funding = {}; files = {}
    for symbol in c["symbols"]:
        d = fetch_mexc_futures_klines(symbol, "1d", c["development_start_utc"], c["development_end_utc_exclusive"], request_pause_seconds=0.10)
        f = fetch_mexc_funding_history(symbol, c["development_start_utc"], c["development_end_utc_exclusive"], page_size=1000, max_pages=20)
        if d.empty or f.empty or len(d) < 120 or len(f) < 100:
            raise RuntimeError(f"{symbol}: incomplete history")
        if {"open", "high", "low", "close"}.difference(d.columns):
            raise RuntimeError(f"{symbol}: missing OHLC")
        daily[symbol], funding[symbol] = d, f
        files[f"{symbol}:1d"] = _write(d, out / "daily" / f"{symbol}_1d.csv")
        files[f"{symbol}:funding"] = _write(f, out / "funding" / f"{symbol}_funding.csv")
    manifest = {
        "source": "MEXC public REST",
        "files": files,
        "survivorship_warning": c["survivorship_warning"],
        "temporal_holdout_protection": c["temporal_holdout_protection"],
    }
    p = out / "dataset_manifest.json"; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_safe(manifest), indent=2, sort_keys=True))
    manifest["manifest_sha256"] = _sha(p)
    return daily, funding, manifest


def _dense(run, symbols):
    x = run.contributions.copy()
    if x.empty:
        x = pd.DataFrame(columns=["timestamp", "symbol", "net_contribution_bps"])
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    keyed = {(pd.Timestamp(r.timestamp), str(r.symbol)): float(r.net_contribution_bps) for r in x.itertuples(index=False)}
    rows = [
        {"timestamp": t, "symbol": s, "net_contribution_bps": keyed.get((pd.Timestamp(t), s), 0.0)}
        for t in run.observations.index for s in symbols
    ]
    return VariantRun(run.observations.copy(), pd.DataFrame(rows))


def _eval(variants, controls, ordered, evaluation, gate):
    return evaluate_sprint7_family(
        variants, controls,
        ordered_variant_ids=ordered,
        evaluation_config=evaluation,
        principal_control_for_variant={x: f"reverse_{x}" for x in ordered},
        gate=gate,
    )


def _persist(name, variants, controls, out):
    for category, runs in (("variants", variants), ("controls", controls)):
        for rid, run in runs.items():
            p = out / "series" / name / category / rid; p.mkdir(parents=True, exist_ok=True)
            run.observations.to_csv(p / "observations.csv", index_label="timestamp")
            run.contributions.to_csv(p / "symbol_contributions.csv", index=False)


def run(protocol, evaluation, out):
    out.mkdir(parents=True, exist_ok=True)
    daily, funding, manifest = _fetch(protocol, out / "data")
    symbols = list(protocol["data"]["symbols"])
    alts = list(protocol["data"]["alt_symbols_for_beta_family"])
    cost = float(protocol["execution"]["transaction_cost_bps_per_side_on_turnover"])
    gate = protocol["family_falsification_gate"]
    reports = {}

    cfg = protocol["families"]["vol_adjusted_short_term_reversal"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["volatility_lookback_days_variants"]:
        vid = f"normrev_{int(n)}d"; ordered.append(vid)
        kw = dict(daily_frames=daily, symbols=symbols, funding_frames=funding, volatility_lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]), side_cost_bps=cost)
        variants[vid] = _dense(vol_adjusted_short_term_reversal(**kw, reverse=False), symbols)
        controls[f"reverse_{vid}"] = _dense(vol_adjusted_short_term_reversal(**kw, reverse=True), symbols)
    reports["vol_adjusted_short_term_reversal"] = _eval(variants, controls, ordered, evaluation, gate)
    _persist("vol_adjusted_short_term_reversal", variants, controls, out)

    cfg = protocol["families"]["momentum_acceleration"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["window_days_variants"]:
        vid = f"accel_{int(n)}d"; ordered.append(vid)
        kw = dict(daily_frames=daily, symbols=symbols, funding_frames=funding, window_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]), side_cost_bps=cost)
        variants[vid] = _dense(momentum_acceleration(**kw, reverse=False), symbols)
        controls[f"reverse_{vid}"] = _dense(momentum_acceleration(**kw, reverse=True), symbols)
    reports["momentum_acceleration"] = _eval(variants, controls, ordered, evaluation, gate)
    _persist("momentum_acceleration", variants, controls, out)

    cfg = protocol["families"]["upside_downside_beta_asymmetry"]
    variants, controls, ordered = {}, {}, []
    for n in cfg["lookback_days_variants"]:
        vid = f"betaasym_{int(n)}d"; ordered.append(vid)
        kw = dict(
            daily_frames=daily, symbols=symbols, alt_symbols=alts, funding_frames=funding,
            lookback_days=int(n), common_warmup_days=int(cfg["common_comparison_warmup_days"]),
            minimum_subset_observations=int(cfg["minimum_observations_per_btc_sign_subset"]), side_cost_bps=cost,
        )
        variants[vid] = _dense(upside_downside_beta_asymmetry(**kw, reverse=False), symbols)
        controls[f"reverse_{vid}"] = _dense(upside_downside_beta_asymmetry(**kw, reverse=True), symbols)
    reports["upside_downside_beta_asymmetry"] = _eval(variants, controls, ordered, evaluation, gate)
    _persist("upside_downside_beta_asymmetry", variants, controls, out)

    return {
        "protocol": protocol["protocol"],
        "protocol_freeze_commit": FREEZE_COMMIT,
        "execution_commit": os.getenv("GITHUB_SHA"),
        "independence_level": "D0",
        "dataset_manifest": manifest,
        "families": reports,
        "claims": {
            "persistent_edge_established": False,
            "live_execution_supported": False,
            "leverage_supported": False,
            "existing_candidates_modified": False,
            "failed_prior_family_rescued": False,
            "2025_temporal_data_used_for_selection": False,
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--protocol", default="config/discovery_v2_sprint7_v1.json")
    p.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    p.add_argument("--output-dir", default="research/discovery_v2/sprint7/results")
    a = p.parse_args(); out = Path(a.output_dir)
    report = _safe(run(_load(a.protocol), _load(a.evaluation), out))
    (out / "sprint7_report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({k: v["state"] for k, v in report["families"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

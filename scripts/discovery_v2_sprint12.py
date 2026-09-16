from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.discovery_v2_sprint1 import VariantRun
from orderflow_edge_lab.discovery_v2_sprint12 import MetaFamilyRun, evaluate_meta_family, run_meta_family
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

FREEZE_COMMIT = "3bcbcdf92c1de02111a19a22a0bf89c8f54a4661"
CLARIFICATION_COMMIT = "3ebc6e20148257089e324b78819a64c33e833fb4"


def _load(path):
    return json.loads(Path(path).read_text())


def _safe(value):
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


def _sha(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def _write(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_index().to_csv(path, index_label="timestamp")
    return {
        "path": str(path),
        "sha256": _sha(path),
        "rows": len(df),
        "start": df.index.min().isoformat(),
        "end": df.index.max().isoformat(),
    }


def _fetch(protocol, out):
    cfg = protocol["data"]
    daily = {}
    funding = {}
    files = {}
    for symbol in cfg["symbols"]:
        d = fetch_mexc_futures_klines(
            symbol,
            "1d",
            cfg["development_start_utc"],
            cfg["development_end_utc_exclusive"],
            request_pause_seconds=0.10,
        )
        f = fetch_mexc_funding_history(
            symbol,
            cfg["development_start_utc"],
            cfg["development_end_utc_exclusive"],
            page_size=1000,
            max_pages=20,
        )
        if d.empty or f.empty or len(d) < 120 or len(f) < 100:
            raise RuntimeError(f"{symbol}: incomplete history")
        daily[symbol], funding[symbol] = d, f
        files[f"{symbol}:1d"] = _write(d, out / "daily" / f"{symbol}_1d.csv")
        files[f"{symbol}:funding"] = _write(f, out / "funding" / f"{symbol}_funding.csv")
    manifest = {
        "source": "MEXC public REST",
        "files": files,
        "no_2025_data_for_discovery": cfg["no_2025_data_for_discovery"],
        "survivorship_warning": cfg["survivorship_warning"],
    }
    p = out / "dataset_manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_safe(manifest), indent=2, sort_keys=True))
    manifest["manifest_sha256"] = _sha(p)
    return daily, funding, manifest


def _dense(run: VariantRun, symbols):
    x = run.contributions.copy()
    if x.empty:
        x = pd.DataFrame(columns=["timestamp", "symbol", "net_contribution_bps"])
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    keyed = {
        (pd.Timestamp(r.timestamp), str(r.symbol)): float(r.net_contribution_bps)
        for r in x.itertuples(index=False)
    }
    rows = [
        {
            "timestamp": t,
            "symbol": s,
            "net_contribution_bps": keyed.get((pd.Timestamp(t), s), 0.0),
        }
        for t in run.observations.index
        for s in symbols
    ]
    return VariantRun(run.observations.copy(), pd.DataFrame(rows))


def _densify(meta: MetaFamilyRun, symbols):
    return MetaFamilyRun(
        candidate=_dense(meta.candidate, symbols),
        reversed_same_decisions=_dense(meta.reversed_same_decisions, symbols),
        ungated_parent=_dense(meta.ungated_parent, symbols),
        anti_meta=_dense(meta.anti_meta, symbols),
        predictions=meta.predictions.copy(),
    )


def _persist(family, meta: MetaFamilyRun, out):
    runs = {
        "candidate": meta.candidate,
        "reversed_same_decisions": meta.reversed_same_decisions,
        "ungated_parent": meta.ungated_parent,
        "anti_meta_diagnostic": meta.anti_meta,
    }
    for name, run in runs.items():
        p = out / "series" / family / name
        p.mkdir(parents=True, exist_ok=True)
        run.observations.to_csv(p / "observations.csv", index_label="timestamp")
        run.contributions.to_csv(p / "symbol_contributions.csv", index=False)
    pred = meta.predictions.drop(columns=[c for c in ["target", "reversed_target"] if c in meta.predictions.columns]).copy()
    pred.to_csv(out / "series" / family / "meta_predictions.csv", index=False)


def run(protocol, evaluation, out):
    out.mkdir(parents=True, exist_ok=True)
    daily, funding, manifest = _fetch(protocol, out / "data")
    symbols = list(protocol["data"]["symbols"])
    model_cfg = protocol["walk_forward_model"]
    gate = protocol["d0_research_candidate_gate"]
    side_cost = float(protocol["execution"]["transaction_cost_bps_per_side_on_actual_turnover"])
    candidate_ids = {
        "meta_trend_acceleration_5d": "dv2_meta_trend_acceleration_5d_v1",
        "meta_low_skew_90d": "dv2_meta_low_skew_90d_v1",
        "meta_funding_carry_14d": "dv2_meta_funding_carry_14d_v1",
    }
    reports = {}
    for family, candidate_id in candidate_ids.items():
        meta = run_meta_family(
            family,
            daily,
            symbols=symbols,
            funding_frames=funding,
            side_cost_bps=side_cost,
            training_window=int(model_cfg["training_window_prior_primary_setups"]),
            minimum_training=int(model_cfg["minimum_prior_primary_setups"]),
            accept_probability=float(model_cfg["accept_if_probability_positive_at_least"]),
        )
        meta = _densify(meta, symbols)
        reports[family] = evaluate_meta_family(
            meta,
            evaluation_config=evaluation,
            gate=gate,
            candidate_id=candidate_id,
        )
        _persist(family, meta, out)
    return {
        "protocol": protocol["protocol"],
        "protocol_freeze_commit": FREEZE_COMMIT,
        "pre_result_clarification_commit": CLARIFICATION_COMMIT,
        "execution_commit": os.getenv("GITHUB_SHA"),
        "independence_level": "D0_CAUSAL_META_SELECTION_DISCOVERY",
        "dataset_manifest": manifest,
        "families": reports,
        "claims": {
            "persistent_edge_established": False,
            "live_execution_supported": False,
            "leverage_supported": False,
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--protocol", default="config/discovery_v2_sprint12_meta_selection_v1.json")
    p.add_argument("--evaluation", default="config/discovery_v2_evaluation_v1.json")
    p.add_argument("--output-dir", default="research/discovery_v2/sprint12/results")
    args = p.parse_args()
    out = Path(args.output_dir)
    report = _safe(run(_load(args.protocol), _load(args.evaluation), out))
    (out / "sprint12_report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({k: v["state"] for k, v in report["families"].items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.payoff_meta_forward import build_forward_snapshot


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


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _fetch(config: dict, *, as_of: pd.Timestamp, output_dir: Path):
    data_cfg = config["data"]
    history_start = str(data_cfg["history_start_utc"])
    current_day = as_of.normalize()
    daily_end = current_day + pd.Timedelta(days=1)
    daily = {}
    funding = {}
    manifest_files = {}
    source_dir = output_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    for symbol in data_cfg["symbols"]:
        d = fetch_mexc_futures_klines(
            symbol,
            "1d",
            history_start,
            daily_end.isoformat(),
            request_pause_seconds=0.10,
        )
        d = d.loc[d.index <= current_day].copy()
        f = fetch_mexc_funding_history(
            symbol,
            history_start,
            as_of.isoformat(),
            page_size=1000,
            max_pages=20,
        )
        if d.empty or len(d) < 200 or f.empty:
            raise RuntimeError(f"{symbol}: incomplete forward-shadow source history")
        daily[symbol] = d
        funding[symbol] = f
        dp = source_dir / f"{symbol}_1d.csv"
        fp = source_dir / f"{symbol}_funding.csv"
        d.to_csv(dp, index_label="timestamp")
        f.to_csv(fp, index_label="timestamp")
        manifest_files[f"{symbol}:1d"] = {
            "path": str(dp),
            "sha256": _sha(dp),
            "rows": len(d),
            "start": d.index.min().isoformat(),
            "end": d.index.max().isoformat(),
        }
        manifest_files[f"{symbol}:funding"] = {
            "path": str(fp),
            "sha256": _sha(fp),
            "rows": len(f),
            "start": f.index.min().isoformat(),
            "end": f.index.max().isoformat(),
        }
    manifest = {
        "source": "MEXC public REST",
        "as_of_utc": as_of.isoformat(),
        "history_start_utc": history_start,
        "files": manifest_files,
        "no_2025_data": bool(data_cfg["no_2025_data"]),
    }
    return daily, funding, manifest


def run(config: dict, *, as_of: pd.Timestamp, output_dir: Path) -> dict:
    start = _utc(config["prospective_start_utc"])
    if as_of < start:
        return {
            "shadow_id": config["shadow_id"],
            "status": "PRE_START",
            "prospective_start_utc": start.isoformat(),
            "as_of_utc": as_of.isoformat(),
            "completed_forward_setups": 0,
            "accepted_completed_setups": 0,
            "source_fetch_skipped_before_start": True,
            "claims": dict(config["claims"]),
        }

    daily, funding, manifest = _fetch(config, as_of=as_of, output_dir=output_dir)
    model_cfg = config["payoff_model"]
    execution = config["execution"]
    report, tables = build_forward_snapshot(
        daily,
        symbols=list(config["data"]["symbols"]),
        funding_frames=funding,
        prospective_start_utc=str(config["prospective_start_utc"]),
        as_of_utc=as_of,
        side_cost_bps=float(execution["transaction_cost_bps_per_side_on_actual_turnover"]),
        ridge_alpha=float(model_cfg["ridge_alpha"]),
        training_window=int(model_cfg["training_window_prior_primary_setups"]),
        minimum_training=int(model_cfg["minimum_prior_primary_setups"]),
        threshold_bps=float(model_cfg["trade_if_predicted_standalone_net_bps_greater_than"]),
    )
    report["shadow_id"] = config["shadow_id"]
    report["source_manifest"] = manifest
    report["claims"] = dict(config["claims"])
    table_dir = output_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        path = table_dir / f"{name}.csv"
        frame.to_csv(path, index=False if "contributions" in name or name == "completed_setup_ledger" else True)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/dv2_payoff_meta_trend_accel_shadow_v1.json")
    p.add_argument("--output-dir", default="research/discovery_v2/payoff_meta_shadow_v1/latest")
    p.add_argument("--as-of-utc", default=None)
    args = p.parse_args()
    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text())
    as_of = _utc(args.as_of_utc) if args.as_of_utc else pd.Timestamp(datetime.now(timezone.utc))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = _safe(run(cfg, as_of=as_of, output_dir=out))
    report["config_sha256"] = _sha(cfg_path)
    report_path = out / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({
        "shadow_id": report["shadow_id"],
        "status": report["status"],
        "as_of_utc": report["as_of_utc"],
        "completed_forward_setups": report.get("completed_forward_setups", 0),
        "accepted_completed_setups": report.get("accepted_completed_setups", 0),
        "latest_open_decision": report.get("latest_open_decision"),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

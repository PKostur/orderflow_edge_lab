from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import run_gold_strategy_discovery_v1 as base


def clean_json(value):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_json(v) for v in value]
    if isinstance(value, tuple):
        return [clean_json(v) for v in value]
    return value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    frames = {
        tf: base.load_csv(data_dir / f"XAUUSD_{tf}_2010_2026.csv")
        for tf in ["M15", "H1", "H4", "D1"]
    }
    integrity = {
        tf: {
            "rows": len(df),
            "start": str(df.index.min()),
            "end": str(df.index.max()),
            "median_bars_per_day": float(
                pd.Series(1, index=df.index).groupby(df.index.floor("D")).sum().median()
            ),
        }
        for tf, df in frames.items()
    }

    results = []
    for family, timeframe, grid in base.grids():
        for params, hold in grid:
            try:
                row = base.evaluate_fixed(frames[timeframe], family, params, hold)
                if row:
                    row["timeframe"] = timeframe
                    results.append(row)
            except Exception as exc:
                results.append(
                    {
                        "family": family,
                        "timeframe": timeframe,
                        "params": params | {"hold": hold},
                        "error": repr(exc),
                        "dev_prelim_pass": False,
                    }
                )

    valid = [r for r in results if r is not None and "error" not in r]
    valid.sort(
        key=lambda r: (
            r.get("dev_prelim_pass", False),
            r.get("net_5_median_fold", -1e99),
            r.get("state_median_rho", -1e99),
        ),
        reverse=True,
    )

    output = {
        "schema_version": 1,
        "protocol": "gold-strategy-discovery-v1.0.1",
        "base_protocol": "gold-strategy-discovery-v1",
        "serialization_only_amendment": True,
        "integrity": integrity,
        "trial_count": len(results),
        "error_count": sum(isinstance(r, dict) and "error" in r for r in results),
        "prelim_pass_count": sum(bool(r.get("dev_prelim_pass")) for r in valid),
        "top_development": valid[:50],
        "all_trials": results,
        "holdout_opened": False,
        "claims": {
            "verified_oos": False,
            "profitable_edge_established": False,
            "live_enabled": False,
        },
    }

    cleaned = clean_json(output)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cleaned, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            clean_json(
                {
                    "trial_count": output["trial_count"],
                    "error_count": output["error_count"],
                    "prelim_pass_count": output["prelim_pass_count"],
                    "integrity": integrity,
                    "top": valid[:10],
                    "holdout_opened": False,
                }
            ),
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

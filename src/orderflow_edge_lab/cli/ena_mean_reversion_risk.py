from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from orderflow_edge_lab.ena_mean_reversion_risk import (
    RiskExperimentConfig,
    analyze_risk_experiment,
    write_report,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def _config_from_payload(payload: dict) -> RiskExperimentConfig:
    signal = payload["signal"]["parameters"]
    risk = payload["risk_trials"]
    gate = payload["development_gate"]
    economics = payload["economics"]
    return RiskExperimentConfig(
        period=int(signal["period"]),
        std=float(signal["std"]),
        rsi_period=int(signal["rsi_period"]),
        rsi_low=float(signal["rsi_low"]),
        rsi_high=float(signal["rsi_high"]),
        max_hold=int(signal["max_hold"]),
        atr_period=int(risk["atr_period"]),
        round_trip_cost_bps=float(economics["round_trip_cost_bps"]),
        fold_days=int(gate["fold_days"]),
        stop_atr_multiples=tuple(float(value) for value in risk["stop_atr_multiples"]),
        target_r_multiples=tuple(float(value) for value in risk["target_r_multiples"]),
        reference_stop_atr_multiple=float(risk["reference_stop_atr_multiple"]),
        minimum_trades=int(gate["minimum_trades"]),
        minimum_folds=int(gate["minimum_folds"]),
        minimum_positive_fold_fraction=float(gate["minimum_positive_fold_fraction"]),
        minimum_tail_loss_reduction_fraction=float(
            gate["minimum_tail_loss_reduction_fraction_vs_unstopped_baseline"]
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the bounded ENA 1h mean-reversion risk-control development experiment."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-output", required=True)
    args = parser.parse_args()

    config_path = Path(args.config)
    config_bytes = config_path.read_bytes()
    payload = json.loads(config_bytes.decode("utf-8"))
    if payload.get("protocol_name") != "ena-mean-reversion-risk-v1":
        raise SystemExit("unexpected risk experiment protocol")

    data = payload["data"]
    frame = fetch_mexc_futures_klines(
        str(data["symbol"]),
        str(data["interval"]),
        str(data["start"]),
        str(data["end_exclusive"]),
    )
    source_output = Path(args.source_output)
    source_output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(source_output, index_label="timestamp")
    source_bytes = source_output.read_bytes()

    config = _config_from_payload(payload)
    report = analyze_risk_experiment(
        frame,
        config,
        source_name=str(source_output),
        source_sha256=sha256(source_bytes).hexdigest(),
    )
    report["protocol"] = {
        "path": str(config_path),
        "sha256": sha256(config_bytes).hexdigest(),
        "status": payload.get("status"),
        "created_after_inspecting_historical_development_results": bool(
            payload.get("created_after_inspecting_historical_development_results")
        ),
    }
    write_report(report, args.output)

    reference = report["reference_risk_variant"]
    print(
        json.dumps(
            {
                "experiment": report["experiment"],
                "baseline": report["baseline"]["full_period"],
                "reference_risk_variant": reference,
                "claims": report["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

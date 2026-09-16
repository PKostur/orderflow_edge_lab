from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.discovery_v2_calibration import build_calibration_report, canonical_json_sha256
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen Discovery v2 reference-vs-independent engine calibration.")
    parser.add_argument("--config", default="config/discovery_v2_engine_calibration_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-dir", default="research/discovery_v2/calibration_data")
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    data = protocol["data"]
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    frames = {}
    for symbol in data["symbols"]:
        frame = fetch_mexc_futures_klines(
            str(symbol),
            str(data["interval"]),
            str(data["start_utc"]),
            str(data["end_exclusive_utc"]),
            request_pause_seconds=0.15,
        )
        frames[str(symbol)] = frame
        frame.to_csv(data_dir / f"{symbol}_{data['interval']}.csv", index=True)

    report = build_calibration_report(frames, protocol)
    report["protocol_sha256"] = canonical_json_sha256(protocol)
    report["source"] = "MEXC public futures klines"
    report["data_window"] = {
        "start_utc": data["start_utc"],
        "end_exclusive_utc": data["end_exclusive_utc"],
        "interval": data["interval"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "reference_independent_parity_pass": report["reference_independent_parity_pass"],
        "symbols": {k: {
            "bars": v["bars"],
            "raw_disagreements": v["raw_target_disagreements"],
            "execution_disagreements": v["execution_target_disagreements"],
            "transition_match": v["transition_timestamps_match"],
        } for k, v in report["symbols"].items()},
    }, indent=2))
    if not report["reference_independent_parity_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

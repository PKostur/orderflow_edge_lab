from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.set_index("timestamp").sort_index()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--freqtrade-dir", required=True)
    parser.add_argument("--nautilus-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    engines = {
        "freqtrade": Path(args.freqtrade_dir),
        "nautilus": Path(args.nautilus_dir),
    }
    report = {
        "schema_version": 1,
        "protocol_name": protocol["protocol_name"],
        "candidate_id": protocol["candidate_id"],
        "engines": {},
    }
    overall = True

    for engine, root in engines.items():
        summary_path = root / f"{engine}_summary.json"
        if engine == "nautilus":
            summary_path = root / "nautilus_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        symbol_rows = {}
        engine_ok = True
        suffix = "freqtrade" if engine == "freqtrade" else "nautilus"
        for symbol in protocol["data"]["symbols"]:
            expected = _load(Path(args.data_dir) / f"{symbol}_{protocol['data']['interval']}_targets.csv")
            actual = _load(root / f"{symbol}_{suffix}.csv")
            same_index = expected.index.equals(actual.index)
            if same_index:
                raw_diff = int((expected["reference_raw_target"].astype(float) != actual["raw_target"].astype(float)).sum())
                exec_diff = int((expected["reference_execution_target"].astype(float) != actual["execution_target"].astype(float)).sum())
                expected_transitions = list(expected.index[expected["reference_execution_target"].ne(expected["reference_execution_target"].shift(1).fillna(0.0))])
                actual_transitions = list(actual.index[actual["execution_target"].ne(actual["execution_target"].shift(1).fillna(0.0))])
                transition_match = expected_transitions == actual_transitions
            else:
                raw_diff = max(len(expected), len(actual))
                exec_diff = raw_diff
                transition_match = False
            ok = same_index and raw_diff == 0 and exec_diff == 0 and transition_match
            engine_ok = engine_ok and ok
            symbol_rows[str(symbol)] = {
                "timestamp_set_match": same_index,
                "raw_target_disagreements": raw_diff,
                "execution_target_disagreements": exec_diff,
                "transition_timestamps_match": transition_match,
                "pass": ok,
            }
        report["engines"][engine] = {
            "version": summary.get("version", "unknown"),
            "signal_api_parity_pass": engine_ok,
            "symbols": symbol_rows,
        }
        overall = overall and engine_ok and summary.get("version", "unknown") != "unknown"

    report["external_signal_parity_pass"] = overall
    report["status"] = "external_signal_parity_pass" if overall else "external_signal_parity_fail"
    report["claims"] = {
        "signal_api_parity_is_full_engine_replication": False,
        "full_event_driven_replication_complete": False,
        "calibration_is_strategy_edge_evidence": False,
        "profitable_edge_established": False,
        "live_order_transmission_supported": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "external_signal_parity_pass": overall,
        "engines": {name: {"version": row["version"], "pass": row["signal_api_parity_pass"]} for name, row in report["engines"].items()},
    }, indent=2))
    if not overall:
        raise SystemExit(3)


if __name__ == "__main__":
    main()

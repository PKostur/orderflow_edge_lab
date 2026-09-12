from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.strategy_tournament import TournamentConfig, fetch_binance_usdm_klines, run_family_tournament


def _load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    if "timestamp" not in frame.columns:
        raise ValueError(f"{path}: missing timestamp column")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.set_index("timestamp").sort_index()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one frozen strategy-family/interval tournament cell.")
    parser.add_argument("--config", default="config/strategy_tournament_v1.json")
    parser.add_argument("--family", required=True)
    parser.add_argument("--interval", required=True)
    parser.add_argument("--data-dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    families = protocol.get("families", {})
    if args.family not in families:
        raise SystemExit(f"family {args.family!r} is not frozen in {protocol.get('protocol_name')}")
    if args.interval not in protocol["data"]["intervals"]:
        raise SystemExit(f"interval {args.interval!r} is not frozen in {protocol.get('protocol_name')}")

    symbols = [str(value).upper() for value in protocol["data"]["symbols"]]
    frames: dict[str, pd.DataFrame] = {}
    failures: list[dict[str, str]] = []
    data_dir = Path(args.data_dir) if args.data_dir else None
    for symbol in symbols:
        try:
            if data_dir is not None:
                path = data_dir / f"{symbol}_{args.interval}.csv"
                if not path.exists():
                    raise FileNotFoundError(path)
                frame = _load_frame(path)
            else:
                frame = fetch_binance_usdm_klines(
                    symbol,
                    args.interval,
                    str(protocol["data"]["start"]),
                    str(protocol["data"]["end_exclusive"]),
                )
            frames[symbol] = frame
        except Exception as exc:
            failures.append({"symbol": symbol, "error_type": type(exc).__name__})

    if len(frames) < 6:
        raise SystemExit(f"only {len(frames)} symbols available; require at least 6")

    family_spec = families[args.family]
    report = run_family_tournament(
        frames,
        args.family,
        family_spec["grid"],
        TournamentConfig(
            source=str(protocol["data"]["source"]),
            start=str(protocol["data"]["start"]),
            end=str(protocol["data"]["end_exclusive"]),
            fold_days=int(protocol["dependence_and_trials"]["fold_days"]),
            min_folds=int(protocol["dependence_and_trials"]["minimum_fold_observations"]),
            round_trip_cost_bps=tuple(float(value) for value in protocol["economics"]["round_trip_cost_bps"]),
        ),
    )
    report.update(
        {
            "protocol_name": protocol["protocol_name"],
            "interval": args.interval,
            "loaded_symbols": sorted(frames),
            "load_failures": failures,
            "parameter_grid": family_spec["grid"],
            "market_state_hypothesis": family_spec["market_state_hypothesis"],
            "specialist_pod": family_spec["pod"],
            "historical_source_is_target_venue": False,
            "target_execution_venue": protocol["data"]["target_execution_venue"],
        }
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

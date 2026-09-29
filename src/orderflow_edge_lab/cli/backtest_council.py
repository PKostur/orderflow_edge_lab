from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.backtest_council import CouncilInputs, load_thresholds, render_markdown, run_council
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy

DEFAULT_CONFIG = Path("config/backtest_council_v1.json")


def _load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        raise SystemExit(f"{path} has no timestamp column")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()


def _load_frames(data_dir: str | None, data: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    if data_dir:
        for p in sorted(Path(data_dir).glob("*.csv")):
            frames[p.stem] = _load_csv(p)
    for item in data:
        symbol, _, path = item.partition("=")
        if not path:
            raise SystemExit(f"--data expects SYMBOL=path, got {item!r}")
        frames[symbol] = _load_csv(Path(path))
    if not frames:
        raise SystemExit("no market data supplied; use --data-dir or --data SYMBOL=path")
    return frames


def _load_strategy(family: str | None, plugin: str | None):
    if bool(family) == bool(plugin):
        raise SystemExit("supply exactly one of --family or --strategy module:attribute")
    if family:
        return legacy_strategy(family)
    module_name, _, attr = str(plugin).partition(":")
    obj = getattr(importlib.import_module(module_name), attr)
    return obj() if callable(obj) and not hasattr(obj, "generate_target") else obj


def main() -> None:
    ap = argparse.ArgumentParser(description="Adversarial backtest council: deterministic members plus a rule-based judge")
    ap.add_argument("--data-dir")
    ap.add_argument("--data", action="append", default=[], help="SYMBOL=path.csv (repeatable)")
    ap.add_argument("--family", help="Existing strategy_tournament family, e.g. donchian_breakout")
    ap.add_argument("--strategy", help="Custom StrategyPlugin as module:attribute")
    ap.add_argument("--params-json", default="{}")
    ap.add_argument("--grid-json", help="Parameter grid actually tried, for multiple-testing and neighborhood checks")
    ap.add_argument("--trial-count", type=int, help="Total variants tried across all research on this hypothesis")
    ap.add_argument("--cost-bps", type=float, required=True, help="Round-trip cost in bps (fees plus spread)")
    ap.add_argument("--slippage-bps", type=float, default=0.0)
    ap.add_argument("--leverage", type=float, help="Intended leverage for the liquidation path check")
    ap.add_argument("--data-role", default="development", choices=["development", "validation", "holdout"])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--output", required=True, help="JSON report path")
    ap.add_argument("--markdown", help="Optional Markdown summary path")
    ap.add_argument("--strict", action="store_true", help="Exit nonzero unless the verdict is SHADOW_ELIGIBLE")
    args = ap.parse_args()

    config = Path(args.config)
    thresholds = load_thresholds(config if config.exists() else None)
    report = run_council(
        CouncilInputs(
            frames=_load_frames(args.data_dir, args.data),
            strategy=_load_strategy(args.family, args.strategy),
            params=json.loads(args.params_json),
            execution=ExecutionModel(args.cost_bps, args.slippage_bps),
            parameter_grid=json.loads(args.grid_json) if args.grid_json else None,
            trial_count=args.trial_count,
            leverage=args.leverage,
            data_role=args.data_role,
        ),
        thresholds,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md = render_markdown(report)
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(md, encoding="utf-8")
    print(md)
    if args.strict and report["judgement"]["verdict"] != "SHADOW_ELIGIBLE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

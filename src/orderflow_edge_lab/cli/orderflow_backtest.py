from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.orderflow_backtest import BacktestConfig, evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description="Exploratory event backtest for MEXC order-flow feature JSONL")
    parser.add_argument("features")
    parser.add_argument("--symbol", default="ENA_USDT")
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = evaluate(args.features, BacktestConfig(symbol=args.symbol, context_symbol=args.context_symbol))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing report: {out}")
    out.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("feature_rows", "signals", "claims")}, indent=2))
    for row in report["summary"]:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

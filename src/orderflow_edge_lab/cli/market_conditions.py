from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.market_conditions import analyze_market_conditions
from orderflow_edge_lab.orderflow_backtest import BacktestConfig


def _ints(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def _floats(value: str) -> tuple[float, ...]:
    return tuple(float(part.strip()) for part in value.split(",") if part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Stratify frozen order-flow results by pre-registered market conditions across independent capture batches.")
    parser.add_argument("features", nargs="+")
    parser.add_argument("--symbol", default="ENA_USDT")
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--horizons-ms", default="5000,15000,30000")
    parser.add_argument("--fees-bps", default="4,8")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    cfg = BacktestConfig(symbol=args.symbol, context_symbol=args.context_symbol)
    report = analyze_market_conditions(
        args.features,
        cfg,
        horizons_ms=_ints(args.horizons_ms),
        fees_bps=_floats(args.fees_bps),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

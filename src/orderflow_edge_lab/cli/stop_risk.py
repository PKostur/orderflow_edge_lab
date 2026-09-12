from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.orderflow_backtest import BacktestConfig
from orderflow_edge_lab.stop_risk import StopRiskConfig, evaluate_stop_risk


def _floats(value: str) -> tuple[float, ...]:
    return tuple(float(part) for part in value.split(",") if part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run stop-based MAE/MFE and equity-risk stress testing on order-flow features.")
    parser.add_argument("features")
    parser.add_argument("--symbol", default="ENA_USDT")
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--lookback-ms", type=int, default=15_000)
    parser.add_argument("--time-stop-ms", type=int, default=30_000)
    parser.add_argument("--rr", default="1,2,3")
    parser.add_argument("--risk-pct", default="0.25,0.5,1,1.5,2,3,5")
    parser.add_argument("--fees-bps", default="4,8")
    parser.add_argument("--max-exposure", type=float, default=100.0)
    parser.add_argument("--starting-equity", type=float, default=100.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    backtest_cfg = BacktestConfig(symbol=args.symbol, context_symbol=args.context_symbol)
    risk_cfg = StopRiskConfig(
        lookback_ms=args.lookback_ms,
        time_stop_ms=args.time_stop_ms,
        rr_targets=_floats(args.rr),
        risk_fractions=tuple(value / 100.0 for value in _floats(args.risk_pct)),
        fee_bps_round_trip=_floats(args.fees_bps),
        max_exposure_multiple=args.max_exposure,
        starting_equity=args.starting_equity,
    )
    report = evaluate_stop_risk(args.features, backtest_cfg, risk_cfg)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.market_state_scan import MarketStateScanConfig, scan_market_state


def _ints(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate pre-registered future market-state targets before strategy-PnL conditioning."
    )
    parser.add_argument("features", help="Causal MEXC feature JSONL capture")
    parser.add_argument("--symbol", default="ENA_USDT")
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--batch-id")
    parser.add_argument("--sample-seconds", type=int, default=5)
    parser.add_argument("--directionality-horizons", default="15,30,60,300")
    parser.add_argument("--volatility-horizons", default="30,60,300")
    parser.add_argument("--liquidity-horizons", default="5,15,30,60")
    parser.add_argument("--continuation-horizons", default="15,30,60,300")
    parser.add_argument("--minimum-association-observations", type=int, default=20)
    parser.add_argument("--redundancy-abs-spearman-threshold", type=float, default=0.80)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = scan_market_state(
        args.features,
        MarketStateScanConfig(
            symbol=args.symbol,
            context_symbol=args.context_symbol,
            sample_seconds=args.sample_seconds,
            directionality_horizons_seconds=_ints(args.directionality_horizons),
            volatility_horizons_seconds=_ints(args.volatility_horizons),
            liquidity_horizons_seconds=_ints(args.liquidity_horizons),
            continuation_horizons_seconds=_ints(args.continuation_horizons),
            minimum_association_observations=args.minimum_association_observations,
            redundancy_abs_spearman_threshold=args.redundancy_abs_spearman_threshold,
        ),
        batch_id=args.batch_id,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

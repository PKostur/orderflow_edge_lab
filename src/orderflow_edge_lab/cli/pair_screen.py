from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.pair_screen import PairScreenConfig, screen_pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen MEXC USDT perpetuals for research compatibility using public market data only.")
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--max-spread-bps", type=float, default=5.0)
    parser.add_argument("--min-turnover-usdt", type=float, default=10_000_000.0)
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--rest-base", default="https://api.mexc.com")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = screen_pairs(
        PairScreenConfig(
            top_n=args.top,
            max_spread_bps=args.max_spread_bps,
            min_turnover_usdt_24h=args.min_turnover_usdt,
            context_symbol=args.context_symbol,
            rest_base=args.rest_base,
        )
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

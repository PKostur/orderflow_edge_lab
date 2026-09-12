from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.ema15m_hypothesis import evaluate_ema15m_hypothesis


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the causal 15-minute EMA20/EMA50 regime as a filter on the preserved ENA Bollinger/BTC strategy.")
    parser.add_argument("--ena", required=True)
    parser.add_argument("--btc", required=True)
    parser.add_argument("--start", default="2026-08-09")
    parser.add_argument("--split", default="2026-08-18")
    parser.add_argument("--end", default="2026-08-28")
    parser.add_argument("--tick-size", type=float, default=0.00001)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = evaluate_ema15m_hypothesis(
        args.ena,
        args.btc,
        start=args.start,
        split=args.split,
        end=args.end,
        tick_size=args.tick_size,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

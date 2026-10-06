from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.zero_fee_scalping import ScalpingError, evaluate, screen_promotional_pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Development-only zero-fee scalping replay; no orders.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    screen = subcommands.add_parser("screen", help="Screen advertised zero-fee pairs without strategy PnL")
    screen.add_argument("--contracts", required=True)
    screen.add_argument("--tickers", required=True)
    screen.add_argument("--output", required=True)
    replay = subcommands.add_parser("replay", help="Replay a completed capture")
    replay.add_argument("features", help="MEXC schema-v2 feature JSONL")
    replay.add_argument("--symbol", required=True)
    replay.add_argument("--contracts", required=True, help="Saved public contract/detail response")
    replay.add_argument("--funding", required=True, help="Saved public funding_rate/SYMBOL response before capture")
    replay.add_argument("--fees", required=True, help="Fee eligibility record, including normal taker fee")
    replay.add_argument("--protocol", default="config/zero_fee_scalping_v1.json")
    replay.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        report = (screen_promotional_pairs(args.contracts, args.tickers) if args.command == "screen" else
                  evaluate(args.features, args.contracts, args.funding, args.fees, args.protocol, symbol=args.symbol))
    except (ScalpingError, ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve previous reports rather than silently replacing evidence.
    with output.open("x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")
    print(json.dumps({"output": str(output), "status": report.get("status", "development_only")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

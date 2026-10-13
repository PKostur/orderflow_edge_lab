"""Download + checksum-verify the 1m Binance USDT-M klines and funding for leverage-bracket-study-v1 (data only).

Prints coverage and validation counts, computes no returns.  Usage:
PYTHONPATH=src .venv/Scripts/python scripts/leverage_bracket_download.py [--workers 8] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab import leverage_bracket_data as bdata

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "research" / "strategy_search_v3" / "round2_universe.json"
DEFAULT_OUT = ROOT / "artifacts" / "leverage_bracket_cache"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    symbols = list(json.loads(UNIVERSE.read_text(encoding="utf-8"))["symbols"])
    manifest = bdata.download_universe(symbols, Path(args.out), workers=args.workers)
    total = sum(e["zip_bytes"] for e in manifest["symbols"])
    print(f"symbols {len(symbols)}, zip bytes {total / 1e6:.0f} MB, seconds {manifest['seconds']}")
    for e in manifest["symbols"]:
        print(e["symbol"], e["bars"], "missing", e.get("missing_inside_span"), "gaps", e.get("gap_count"),
              "longest", e.get("longest_gap_minutes"), "violations", e["ohlc_violations"],
              "first", e.get("first_bar_end"), "last", e.get("last_bar_end"), "funding", e["funding_rows"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

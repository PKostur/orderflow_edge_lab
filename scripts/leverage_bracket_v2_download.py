"""Download + checksum-verify the 2021-2023 1m Binance USDT-M klines and funding for leverage-bracket-study-v2 (data only).

float32 storage, zips deleted after parsing, stops cleanly if free disk would fall below 1.0 GB.  Prints coverage and
validation counts, computes no returns.  Usage:
PYTHONPATH=src .venv/Scripts/python scripts/leverage_bracket_v2_download.py [--workers 4] [--out DIR] [--report-only]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab import leverage_bracket_v2_data as bd2

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "research" / "strategy_search_v3" / "round2_universe.json"
DEFAULT_OUT = ROOT / "artifacts" / "leverage_bracket_cache_2021"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--refresh-funding", action="store_true")
    parser.add_argument("--repair-gaps", action="store_true",
                        help="apply the amendment-1 daily-file fill to the stored symbols")
    args = parser.parse_args(argv)
    out = Path(args.out)
    symbols = list(json.loads(UNIVERSE.read_text(encoding="utf-8"))["symbols"])
    out.mkdir(parents=True, exist_ok=True)
    print(f"free disk before: {bd2.free_bytes(out) / 1e9:.2f} GB")
    if args.refresh_funding:
        print("funding rows added:", bd2.refresh_funding(symbols, out))
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    elif args.repair_gaps:
        manifest = bd2.repair_universe(symbols, out, workers=args.workers)
    elif args.report_only:
        manifest = bd2.write_manifest(out, symbols, complete=all((out / "_entries" / f"{s}.json").exists() for s in symbols),
                                      seconds=0.0, stopped=None)
    else:
        manifest = bd2.download_universe(symbols, out, workers=args.workers)
    print(f"complete {manifest['complete']} stopped {manifest['stopped_reason']}")
    print(f"free disk after: {bd2.free_bytes(out) / 1e9:.2f} GB")
    total = sum(e["zip_bytes"] for e in manifest["symbols"])
    print(f"symbols {len(manifest['symbols'])}/{len(symbols)}, zip bytes {total / 1e6:.0f} MB, "
          f"seconds {manifest['seconds']}")
    for e in manifest["symbols"]:
        f32 = e["float32"]
        print(e["symbol"], e["bars"], "missing", e.get("missing_inside_span"), "gaps", e.get("gap_count"),
              "longest", e.get("longest_gap_minutes"), "violations", e["ohlc_violations"],
              "first", e.get("first_bar_end"), "last", e.get("last_bar_end"), "funding", e["funding_rows"],
              "f32 rel", f"{f32['max_rel_error']:.2e}", "collapsed", f32["range_collapsed_bars"],
              "inverted", f32["high_below_low_after"], "tail same", f32["stale_tail_unchanged"],
              "daily fill", {k: (len(v) if isinstance(v, list) else v) for k, v in e.get("daily_fill", {}).items()})
    print("--- coverage after the stale-tail rule ---")
    for row in bd2.coverage_report(out, [e["symbol"] for e in manifest["symbols"]]):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

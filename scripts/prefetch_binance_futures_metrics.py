"""Build the round-2 universe and download + checksum-verify its Binance futures metrics (5-minute open interest).

Fetches into ``%TEMP%/binance_futures_metrics/`` (and the perp / funding / mark klines of the same symbols into
``%TEMP%/binance_futures_archive/``, mostly cached already) so the single-look strategy-search-v3 round-2 runner reads
the cache.  The universe is the top 30 USDT-M perps by mean daily perp quote volume over 2020-10-01..2020-12-31 that list
a metrics file for 2021-12-01 (amended registration); it is written once to ``research/strategy_search_v3/round2_universe.json`` (an existing
file is only compared).  Prints coverage only (rows, first / last record, missing days); it computes no returns and
looks at no performance.
Usage: PYTHONPATH=src .venv/Scripts/python scripts/prefetch_binance_futures_metrics.py [--workers 24]
       [--universe-only] [--symbols BTCUSDT --oi-start 2021-12-01 --end 2021-12-05]   (smoke test)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from orderflow_edge_lab import binance_futures_metrics as bfm
from orderflow_edge_lab import liquidation_cascade as lc

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_FILE = ROOT / "research" / "strategy_search_v3" / "round2_universe.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch the round-2 universe and its futures metrics.")
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--oi-start", default=bfm.OI_LOAD_START,
                        help="first metrics day to load (one day before the sample start 2021-12-01)")
    parser.add_argument("--mark-start", default="2023-06-01")
    parser.add_argument("--universe-only", action="store_true")
    parser.add_argument("--universe-file", default=str(UNIVERSE_FILE))
    parser.add_argument("--metrics-day", default=bfm.DATA_START,
                        help="a universe member must list a metrics file for this day (registered: 2021-12-01)")
    parser.add_argument("--symbols", default=None, help="comma separated symbols (smoke tests; skips the universe)")
    args = parser.parse_args(argv)
    started = time.time()

    def progress(done: int, total: int) -> None:
        print(f"{done}/{total}  {time.time() - started:.0f}s", file=sys.stderr, flush=True)

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        path = Path(args.universe_file)
        definition = bfm.build_universe(workers=args.workers, metrics_day=args.metrics_day)
        if len(definition["symbols"]) < definition["size"]:
            print(f"UNIVERSE TOO SHORT: only {len(definition['symbols'])} of {definition['size']} ranked perps list a "
                  f"metrics file for {args.metrics_day} ({definition['symbols']}); nothing written.", file=sys.stderr)
            return 3
        if path.exists():
            registered = json.loads(path.read_text(encoding="utf-8"))
            if not bfm.universe_matches(registered, definition):
                print(f"UNIVERSE MISMATCH: {path} differs from the rebuilt ranking", file=sys.stderr)
                return 2
            print(f"universe file {path.name} matches the rebuilt ranking")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(definition, handle, indent=2, sort_keys=True)
                handle.write("\n")
            print(f"wrote {path}")
        symbols = list(definition["symbols"])
        print(f"universe: {len(symbols)} symbols  ({definition['candidates_ranked']} ranked candidates, "
              f"{len(definition['skipped_no_metrics'])} higher-ranked without a {definition['metrics_day']} metrics file)")
        print(", ".join(symbols))
        if args.universe_only:
            return 0
    data = lc.load_data(symbols, end=args.end, mark_start=args.mark_start, workers=args.workers,
                        oi_start=args.oi_start, progress=progress)
    rows = data["provenance"]["oi"]
    print(f"{'symbol':16s} {'rows':>8s} {'first':>20s} {'last':>20s} {'missing_days':>12s} {'dups':>6s} {'zeros':>6s}")
    for sym in symbols:
        v = rows[sym]
        print(f"{sym:16s} {v['rows']:8d} {str(v['first'])[:19]:>20s} {str(v['last'])[:19]:>20s} "
              f"{v['days_missing_within_span']:12d} {v['duplicate_rows_dropped']:6d} {v['zero_or_negative_rows']:6d}")
    print(f"perp {len(data['perp'])}, funding {len(data['funding'])}, mark {len(data['mark'])}, "
          f"oi {sum(1 for s in data['oi'].values() if len(s))}  {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

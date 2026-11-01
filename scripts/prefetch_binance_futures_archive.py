"""Download and checksum-verify the Binance USDT-M perp / mark / funding / spot 1h archive into
%TEMP%/binance_futures_archive/.

Run this before the single-look strategy-search-v3 round-1 runner so the runner reads the cache.  Prints coverage only
(symbol and row counts); it computes no returns and looks at no performance.  The runner loads mark prices from
``--mark-start`` (default the validation start); perp, funding and spot data from ``--start`` (default: all).
Usage: PYTHONPATH=src .venv/Scripts/python scripts/prefetch_binance_futures_archive.py [--workers 24]
       [--symbols BTCUSDT,ETHUSDT --start 2023-03-01 --end 2023-03-31]   (smoke test)
"""

from __future__ import annotations

import argparse
import sys
import time

from orderflow_edge_lab import binance_futures_archive as archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch the Binance USDT-M futures + spot 1h archive.")
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--end", default=archive.END_DATE)
    parser.add_argument("--start", default=None, help="first month to load for perp/funding/spot (default: all)")
    parser.add_argument("--mark-start", default="2023-07-02", help="first month of mark-price klines")
    parser.add_argument("--no-mark", action="store_true")
    parser.add_argument("--symbols", default=None, help="comma separated perp symbols (smoke tests)")
    args = parser.parse_args(argv)
    started = time.time()

    def progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            print(f"{done}/{total} symbols  {time.time() - started:.0f}s", file=sys.stderr, flush=True)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    universe = archive.load_universe(end=args.end, start=args.start, symbols=symbols, workers=args.workers,
                                     include_mark=not args.no_mark, mark_start=args.mark_start, progress=progress)
    prov = universe["provenance"]
    print(f"perp symbols listed {prov['perp_symbols_listed']}, excluded {len(prov['symbols_excluded'])}, "
          f"without exact spot pair {len(prov['perps_without_spot'])}, matched {prov['symbols_matched']}, "
          f"instruments {prov['instruments_used']}; funding series {len(universe['funding'])}, "
          f"mark series {len(universe['mark'])}, spot series {len(universe['spot'])}")
    firsts = [v["first_bar_end"] for v in prov["per_instrument"].values()]
    lasts = [v["last_bar_end"] for v in prov["per_instrument"].values()]
    print(f"bars {min(firsts)} .. {max(lasts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

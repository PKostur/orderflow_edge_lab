"""Download and checksum-verify the Binance spot USDT daily kline archive into %TEMP%/binance_spot_archive/.

Run this before the single-look round-2 runner so the runner reads the cache.  Prints coverage only (symbol and date
counts); it computes no returns and looks at no performance.
Usage: PYTHONPATH=src .venv/Scripts/python scripts/prefetch_binance_spot_archive.py [--workers 24]
"""

from __future__ import annotations

import argparse
import sys
import time

from orderflow_edge_lab import binance_spot_archive as archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch the Binance spot 1d kline archive.")
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--end", default=archive.END_DATE)
    args = parser.parse_args(argv)
    started = time.time()

    def progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            print(f"{done}/{total} symbols  {time.time() - started:.0f}s", file=sys.stderr, flush=True)

    panel = archive.load_universe(end=args.end, workers=args.workers, progress=progress)
    prov = panel["provenance"]
    print(f"symbols listed {prov['symbols_listed']}, excluded {len(prov['symbols_excluded'])}, "
          f"loaded {prov['symbols_used']}; frame {panel['close'].shape}; "
          f"{panel['close'].index[0].date()} .. {panel['close'].index[-1].date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

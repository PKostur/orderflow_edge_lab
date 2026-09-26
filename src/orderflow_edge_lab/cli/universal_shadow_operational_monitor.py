from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.universal_shadow_operational_monitor import (
    UniversalShadowOperationalMonitorError,
    build_operational_monitor,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explain current frozen-strategy position state without altering prospective evidence."
    )
    parser.add_argument(
        "--config",
        default="config/universal_session_alignment_shadow_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
        as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
        symbols = [str(value) for value in config["source"]["symbols"]]
        interval = str(config["source"]["interval"])
        warmup = str(config["source"]["warmup_start_utc"])
        frames: dict[str, pd.DataFrame] = {}

        def load(symbol: str) -> tuple[str, pd.DataFrame]:
            return symbol, fetch_mexc_futures_klines(
                symbol,
                interval,
                warmup,
                as_of.isoformat(),
            )

        with ThreadPoolExecutor(max_workers=max(1, min(args.max_workers, len(symbols)))) as pool:
            futures = {pool.submit(load, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol, frame = future.result()
                frames[symbol] = frame

        report = build_operational_monitor(config, frames, as_of_utc=as_of)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "watch_id": report["watch_id"],
                    "as_of_utc": report["as_of_utc"],
                    "latest_execution_boundary_utc": report[
                        "latest_execution_boundary_utc"
                    ],
                    "execution_boundaries_since_start_including_start": report[
                        "execution_boundaries_since_start_including_start"
                    ],
                    "strategies": {
                        row["audit_id"]: {
                            "current_nonzero_symbol_count": row[
                                "current_nonzero_symbol_count"
                            ],
                            "carried_pre_start_position_count": row[
                                "carried_pre_start_position_count"
                            ],
                            "current_long_symbol_count": row[
                                "current_long_symbol_count"
                            ],
                            "current_short_symbol_count": row[
                                "current_short_symbol_count"
                            ],
                            "current_flat_symbol_count": row[
                                "current_flat_symbol_count"
                            ],
                            "long_symbol_fraction": row[
                                "long_symbol_fraction"
                            ],
                            "median_position_age_hours": row[
                                "median_position_age_hours"
                            ],
                            "post_start_position_change_count": row[
                                "post_start_position_change_count"
                            ],
                            "symbols_with_post_start_change": row[
                                "symbols_with_post_start_change"
                            ],
                        }
                        for row in report["strategies"]
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        UniversalShadowOperationalMonitorError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

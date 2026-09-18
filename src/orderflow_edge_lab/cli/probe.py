#!/usr/bin/env python3
"""Safe dxFeed/DeepCharts data-access probe.

This script never places an order.

Zero-cost paths:
1. `--export FILE.csv` validates a dxFeed/DeepCharts CSV export locally.
2. If an existing entitlement includes external dxFeed REST access, set
   DXFEED_REST_ENDPOINT, DXFEED_TOKEN, and DXFEED_SYMBOL locally, then run
   this script without --export.
3. Add both `--from-time` and `--to-time` to test a bounded historical
   TimeAndSale window (maximum 10 minutes).

Do not commit tokens or paste them into chat.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
import os
from pathlib import Path
import urllib.request

from orderflow_edge_lab.dxfeed import (
    NoRedirect,
    probe_connection,
    probe_depth_snapshot,
    probe_history,
)
from orderflow_edge_lab.adapters import normalize_dxfeed_rows
from orderflow_edge_lab.data import DataQualityPolicy, quality_report


FUTURES_V1_MAX_QUOTE_AGE_SECONDS = 1.0


def probe_export(
    path: str,
    symbol: str | None,
    *,
    max_quote_age_seconds: float = FUTURES_V1_MAX_QUOTE_AGE_SECONDS,
) -> int:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        adapted = normalize_dxfeed_rows(
            csv.DictReader(handle),
            default_symbol=symbol,
            max_quote_age_seconds=max_quote_age_seconds,
        )
    report = quality_report(
        adapted.events,
        DataQualityPolicy(
            min_events=1,
            max_unknown_trade_side_fraction=1.0,
            max_tick_rule_trade_fraction=1.0,
            min_trade_bbo_fraction_when_explicit_side_low=0.0,
        ),
    )
    print(
        json.dumps(
            {
                "mode": "export",
                "file": str(Path(path)),
                "max_quote_age_seconds": max_quote_age_seconds,
                "adapter": asdict(adapted.stats),
                "quality": asdict(report),
            },
            indent=2,
        )
    )
    return 0 if report.passed else 2


_NoRedirect = NoRedirect


def probe_rest(
    endpoint: str,
    token: str | None,
    symbol: str,
    *,
    username: str | None = None,
    password: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    depth: bool = False,
) -> int:
    if depth and (from_time is not None or to_time is not None):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": "InvalidConfiguration",
                    "note": "--depth cannot be combined with --from-time/--to-time.",
                },
                indent=2,
            )
        )
        return 2
    if (from_time is None) != (to_time is None):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": "InvalidConfiguration",
                    "missing": ["--from-time and --to-time must be supplied together"],
                },
                indent=2,
            )
        )
        return 2
    if depth:
        code, result = probe_depth_snapshot(
            endpoint,
            token,
            symbol,
            username=username,
            password=password,
        )
    elif from_time is not None and to_time is not None:
        code, result = probe_history(
            endpoint,
            token,
            symbol,
            from_time,
            to_time,
            username=username,
            password=password,
        )
    else:
        code, result = probe_connection(
            endpoint, token, symbol, username=username, password=password
        )
    print(json.dumps(result, indent=2))
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", help="Local dxFeed/DeepCharts CSV export")
    parser.add_argument("--symbol", help="Default symbol for exports missing a symbol column")
    parser.add_argument(
        "--max-quote-age-seconds",
        type=float,
        default=FUTURES_V1_MAX_QUOTE_AGE_SECONDS,
        help=(
            "Maximum age of a prior BBO attached to a later trade in export mode "
            "(cross-market futures v1 freeze: 1.0 second)"
        ),
    )
    parser.add_argument(
        "--from-time",
        help="Historical TimeAndSale window start, timezone-aware ISO 8601; requires --to-time",
    )
    parser.add_argument(
        "--to-time",
        help="Historical TimeAndSale window end, timezone-aware ISO 8601; max window 10 minutes",
    )
    parser.add_argument(
        "--depth",
        action="store_true",
        help="Probe current futures AGGREGATE Order depth; this does not verify historical depth",
    )
    args = parser.parse_args()

    if args.export:
        if args.from_time is not None or args.to_time is not None or args.depth:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "error_type": "InvalidConfiguration",
                        "note": "Historical REST options cannot be combined with --export.",
                    },
                    indent=2,
                )
            )
            return 2
        return probe_export(
            args.export,
            args.symbol,
            max_quote_age_seconds=args.max_quote_age_seconds,
        )

    endpoint = os.environ.get("DXFEED_REST_ENDPOINT")
    token = os.environ.get("DXFEED_TOKEN")
    username = os.environ.get("DXFEED_USERNAME")
    password = os.environ.get("DXFEED_PASSWORD")
    symbol = os.environ.get("DXFEED_SYMBOL")
    missing = [
        name
        for name, value in (
            ("DXFEED_REST_ENDPOINT", endpoint),
            ("DXFEED_SYMBOL", symbol),
        )
        if not value
    ]
    if not token and not (username and password):
        missing.append("DXFEED_TOKEN or DXFEED_USERNAME + DXFEED_PASSWORD")
    if missing:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "missing": missing,
                    "smallest_action": (
                        "Either export a small dxFeed/DeepCharts trade/BBO CSV and run "
                        "`python scripts/dxfeed_entitlement_probe.py --export FILE.csv`, "
                        "or set the external dxFeed REST endpoint, supported authentication, and symbol "
                        "as local environment variables if your subscription provides them."
                    ),
                },
                indent=2,
            )
        )
        return 2
    return probe_rest(
        endpoint,
        token,
        symbol,
        username=username,
        password=password,
        from_time=args.from_time,
        to_time=args.to_time,
        depth=args.depth,
    )


if __name__ == "__main__":
    raise SystemExit(main())

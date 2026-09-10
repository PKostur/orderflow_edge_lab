#!/usr/bin/env python3
"""Safe dxFeed/DeepCharts data-access probe.

This script never places an order.

Zero-cost paths:
1. `--export FILE.csv` validates a dxFeed/DeepCharts CSV export locally.
2. If an existing entitlement includes external dxFeed REST access, set
   DXFEED_REST_ENDPOINT, DXFEED_TOKEN, and DXFEED_SYMBOL locally, then run
   this script without --export.

Do not commit tokens or paste them into chat.
"""

from __future__ import annotations

import argparse
import base64
import csv
from dataclasses import asdict
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

from orderflow_edge_lab.dxfeed import NoRedirect, probe_connection
from orderflow_edge_lab.adapters import normalize_dxfeed_rows
from orderflow_edge_lab.data import DataQualityPolicy, quality_report


def probe_export(path: str, symbol: str | None, *, max_quote_age_seconds: float = 2.0) -> int:
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
    print(json.dumps({
        "mode": "export",
        "file": str(Path(path)),
        "adapter": asdict(adapted.stats),
        "quality": asdict(report),
    }, indent=2))
    return 0 if report.passed else 2


_NoRedirect = NoRedirect


def probe_rest(endpoint: str, token: str | None, symbol: str, *,
               username: str | None = None, password: str | None = None) -> int:
    code, result = probe_connection(endpoint, token, symbol, username=username, password=password)
    print(json.dumps(result, indent=2))
    return code

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", help="Local dxFeed/DeepCharts CSV export")
    parser.add_argument("--symbol", help="Default symbol for exports missing a symbol column")
    parser.add_argument(
        "--max-quote-age-seconds",
        type=float,
        default=2.0,
        help="Maximum age of a prior BBO attached to a later trade in export mode",
    )
    args = parser.parse_args()

    if args.export:
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
        name for name, value in (
            ("DXFEED_REST_ENDPOINT", endpoint),
            ("DXFEED_SYMBOL", symbol),
        ) if not value
    ]
    if not token and not (username and password):
        missing.append("DXFEED_TOKEN or DXFEED_USERNAME + DXFEED_PASSWORD")
    if missing:
        print(json.dumps({
            "status": "blocked",
            "missing": missing,
            "smallest_action": (
                "Either export a small dxFeed/DeepCharts trade/BBO CSV and run "
                "`python scripts/dxfeed_entitlement_probe.py --export FILE.csv`, "
                "or set the external dxFeed REST endpoint, supported authentication, and symbol "
                "as local environment variables if your subscription provides them."
            ),
        }, indent=2))
        return 2
    return probe_rest(endpoint, token, symbol, username=username, password=password)


if __name__ == "__main__":
    raise SystemExit(main())

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
from dataclasses import asdict
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

from orderflow_edge_lab.data import DataQualityPolicy, load_export_csv, quality_report


def probe_export(path: str, symbol: str | None) -> int:
    events = load_export_csv(path, default_symbol=symbol)
    report = quality_report(
        events,
        DataQualityPolicy(
            min_events=1,
            max_unknown_trade_side_fraction=1.0,
            max_tick_rule_trade_fraction=1.0,
            min_trade_bbo_fraction_when_explicit_side_low=0.0,
        ),
    )
    print(json.dumps({"mode": "export", "file": str(Path(path)), **asdict(report)}, indent=2))
    return 0 if report.passed else 2


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A bearer token must never follow a redirect to another endpoint.
        return None


def probe_rest(endpoint: str, token: str, symbol: str) -> int:
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() for c in endpoint)
                or not token.strip() or any(c in token for c in "\r\n")
                or not symbol.strip()):
            raise ValueError("invalid endpoint or credentials")
        parsed.port
    except ValueError:
        print(json.dumps({"mode": "rest", "status": "failed", "error_type": "InvalidConfiguration"}))
        return 3
    params = urllib.parse.urlencode([("event", "Quote"), ("symbol", symbol)])
    separator = "&" if "?" in endpoint else "?"
    request = urllib.request.Request(
        endpoint + separator + params,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "orderflow-edge-lab/0.9"},
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=15) as response:
            body = response.read(64_000)
            status = response.status
    except Exception as exc:
        print(json.dumps({
            "mode": "rest",
            "status": "failed",
            "error_type": type(exc).__name__,
            "note": "Failure may mean endpoint/token/symbol entitlement is unavailable; no credentials were printed.",
        }, indent=2))
        return 3

    print(json.dumps({
        "mode": "rest",
        "status": "ok" if 200 <= status < 300 else "failed",
        "http_status": status,
        "symbol": symbol,
        "response_bytes_read": len(body),
        "note": "HTTP access only; does not establish historical trade entitlement or data validity.",
    }, indent=2))
    return 0 if 200 <= status < 300 else 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", help="Local dxFeed/DeepCharts CSV export")
    parser.add_argument("--symbol", help="Default symbol for exports missing a symbol column")
    args = parser.parse_args()

    if args.export:
        return probe_export(args.export, args.symbol)

    endpoint = os.environ.get("DXFEED_REST_ENDPOINT")
    token = os.environ.get("DXFEED_TOKEN")
    symbol = os.environ.get("DXFEED_SYMBOL")
    missing = [
        name for name, value in (
            ("DXFEED_REST_ENDPOINT", endpoint),
            ("DXFEED_TOKEN", token),
            ("DXFEED_SYMBOL", symbol),
        ) if not value
    ]
    if missing:
        print(json.dumps({
            "status": "blocked",
            "missing": missing,
            "smallest_action": (
                "Either export a small dxFeed/DeepCharts trade/BBO CSV and run "
                "`python scripts/dxfeed_entitlement_probe.py --export FILE.csv`, "
                "or set the external dxFeed REST endpoint, bearer token, and symbol "
                "as local environment variables if your subscription provides them."
            ),
        }, indent=2))
        return 2
    return probe_rest(endpoint, token, symbol)


if __name__ == "__main__":
    raise SystemExit(main())

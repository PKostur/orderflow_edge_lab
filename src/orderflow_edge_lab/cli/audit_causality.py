"""CLI for auditing outcome maturity across sequential validation windows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from orderflow_edge_lab.causal_audit import audit_outcome_maturity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect validation observations whose outcomes complete after their event window closes."
    )
    parser.add_argument("registry", help="Frozen candidate registry JSON")
    parser.add_argument("observations", help="Future observations JSONL")
    parser.add_argument("--window-days", type=int, default=7, help="Sequential validation window length")
    parser.add_argument("--output", help="Optional JSON report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_outcome_maturity(
            args.registry,
            args.observations,
            window_days=args.window_days,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}),
            file=sys.stderr,
        )
        return 2

    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded + "\n", encoding="utf-8")
    return 0 if report["causal_window_summaries_safe"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

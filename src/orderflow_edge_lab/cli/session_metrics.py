from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.session_metrics import (
    SessionMetricsError,
    analyze_bar_sessions,
    analyze_trade_sessions,
    load_rows,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze strategy or market behavior by Asia, London and New York trading sessions."
    )
    parser.add_argument("input", help="CSV, JSON or JSONL input file.")
    parser.add_argument("--mode", choices=("auto", "trades", "bars"), default="auto")
    parser.add_argument("--timestamp-field")
    parser.add_argument("--return-field")
    parser.add_argument("--open-field", default="open")
    parser.add_argument("--high-field", default="high")
    parser.add_argument("--low-field", default="low")
    parser.add_argument("--close-field", default="close")
    parser.add_argument("--volume-field", default="volume")
    parser.add_argument("--output", help="Optional JSON output path.")
    return parser


def _infer_mode(rows: list[dict[str, object]], explicit: str) -> str:
    if explicit != "auto":
        return explicit
    if not rows:
        raise SessionMetricsError("input is empty")
    first = rows[0]
    if all(key in first for key in ("open", "high", "low", "close")):
        return "bars"
    return "trades"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = load_rows(args.input)
        mode = _infer_mode(rows, args.mode)
        if mode == "bars":
            result = analyze_bar_sessions(
                rows,
                timestamp_field=args.timestamp_field,
                open_field=args.open_field,
                high_field=args.high_field,
                low_field=args.low_field,
                close_field=args.close_field,
                volume_field=args.volume_field,
            )
        else:
            result = analyze_trade_sessions(
                rows,
                timestamp_field=args.timestamp_field,
                return_field=args.return_field,
            )

        text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    except (OSError, ValueError, TypeError, KeyError, SessionMetricsError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.export_bundle import build_export_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministically merge overlapping DeepCharts/dxFeed CSV exports with provenance."
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--symbol", help="Default symbol only when source rows omit one")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_export_bundle(args.inputs, args.output, default_symbol=args.symbol)
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    print(json.dumps({"status": "ok", "output": str(args.output), **result.as_dict()}, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

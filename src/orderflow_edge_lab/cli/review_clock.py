from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.review_clock import (
    DEFAULT_CONFIG,
    ReviewClockError,
    clock_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report elapsed-time observability for preregistered prospective "
            "watches. Computes no strategy verdicts and inspects no PnL."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Clock configuration JSON (frozen watch list).",
    )
    parser.add_argument(
        "--output",
        help="Optional path for an exclusive-create JSON report.",
    )
    return parser


def _write_exclusive(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = clock_report(Path(args.config))
        if args.output:
            _write_exclusive(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, ReviewClockError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

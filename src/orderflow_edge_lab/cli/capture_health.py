from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.capture_health import DEFAULT_DATA_DIR, CaptureHealthError, build_health_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Descriptive health summary of recorded MEXC order-flow captures: "
            "counts, symbols, gaps, staleness. Reporting only; counts no "
            "prospective evidence and certifies no data quality."
        )
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory containing recorded captures (default: data/mexc_orderflow).",
    )
    parser.add_argument(
        "--stale-after-hours",
        type=float,
        default=26.0,
        help="Flag 'no_recent_capture' when the newest capture is older than this (default: 26).",
    )
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON report.")
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
        payload = build_health_summary(
            Path(args.data_dir), stale_after_hours=float(args.stale_after_hours)
        )
        if args.output:
            _write_exclusive(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, CaptureHealthError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

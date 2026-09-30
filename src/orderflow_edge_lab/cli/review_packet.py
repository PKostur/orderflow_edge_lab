from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.review_packet import (
    DEFAULT_FORWARD_WATCH_CONFIG,
    DEFAULT_SESSION_WATCH_CONFIG,
    ReviewPacketError,
    build_review_packet,
    review_packet_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble a hash-pinned review skeleton for a predeclared prospective "
            "watch from the frozen counting report and the frozen watch config. "
            "Pipeline numbers are copied verbatim; every verdict cell is left "
            "empty for a human decision."
        )
    )
    parser.add_argument(
        "report",
        help="Frozen counting report (frozen session-watch report or frozen forward-watch report).",
    )
    parser.add_argument(
        "--session-watch-config",
        default=str(DEFAULT_SESSION_WATCH_CONFIG),
        help="Frozen session watch config used to quote predeclared metrics.",
    )
    parser.add_argument(
        "--forward-watch-config",
        default=str(DEFAULT_FORWARD_WATCH_CONFIG),
        help="Frozen forward watch config used to quote the review window and metrics.",
    )
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON packet.")
    parser.add_argument("--markdown", help="Optional path for the markdown review skeleton.")
    return parser


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        packet = build_review_packet(
            Path(args.report),
            session_watch_config=Path(args.session_watch_config),
            forward_watch_config=Path(args.forward_watch_config),
        )
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(packet, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), review_packet_markdown(packet))
        print(json.dumps(packet, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, ReviewPacketError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

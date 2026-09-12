from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.session_audit import SessionAuditError, close_paper_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close a paper session by proving journal history stayed append-only."
    )
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--state", default="runtime/paper-state.json")
    parser.add_argument("--journal", default="runtime/paper-journal.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--allow-active",
        action="store_true",
        help="Allow pending proposals or open paper positions at closeout.",
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
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        result = close_paper_session(
            snapshot,
            Path(args.state),
            Path(args.journal),
            require_flat=not args.allow_active,
        )
        _write_exclusive(Path(args.output), result)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result["verified"] else 2
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, SessionAuditError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

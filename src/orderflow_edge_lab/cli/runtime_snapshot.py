from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.runtime_snapshot import (
    RuntimeSnapshotError,
    create_runtime_snapshot,
    verify_runtime_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze or verify exact approval-bound paper runtime bytes."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create an immutable pre-session runtime snapshot")
    create.add_argument("--state", default="runtime/paper-state.json")
    create.add_argument("--journal", default="runtime/paper-journal.jsonl")
    create.add_argument("--output", required=True)
    create.add_argument(
        "--allow-active",
        action="store_true",
        help="Allow pending proposals or open paper positions. Clean-session snapshots are flat by default.",
    )

    verify = sub.add_parser("verify", help="Verify runtime bytes against a prior snapshot")
    verify.add_argument("--snapshot", required=True)
    verify.add_argument("--state", default="runtime/paper-state.json")
    verify.add_argument("--journal", default="runtime/paper-journal.jsonl")
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
        if args.command == "create":
            payload = create_runtime_snapshot(
                Path(args.state),
                Path(args.journal),
                require_flat=not args.allow_active,
            )
            _write_exclusive(Path(args.output), payload)
            print(json.dumps(payload, sort_keys=True, indent=2))
            return 0

        snapshot_path = Path(args.snapshot)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        result = verify_runtime_snapshot(snapshot, Path(args.state), Path(args.journal))
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result["verified"] else 2
    except (OSError, ValueError, TypeError, KeyError, RuntimeSnapshotError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

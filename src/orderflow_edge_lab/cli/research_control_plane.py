from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.research_control_plane import (
    ResearchControlPlaneError,
    build_control_plane_status,
)


def _load(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResearchControlPlaneError(f"{path}: expected JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Combine frozen shadow, Jev, and operational telemetry into one status."
    )
    parser.add_argument("--shadow-report", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--operational", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        result = build_control_plane_status(
            _load(args.shadow_report),
            _load(args.decision),
            _load(args.action),
            _load(args.operational),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        ResearchControlPlaneError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

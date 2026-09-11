from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.research_freeze import build_research_freeze


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze a strategy configuration before collecting prospective out-of-sample data. "
            "This creates an auditable registration hash and performs no trading or network access."
        )
    )
    parser.add_argument("strategy_config", type=Path)
    parser.add_argument("--strategy-id")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        freeze = build_research_freeze(args.strategy_config, strategy_id=args.strategy_id)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    payload = json.dumps(freeze, indent=2, allow_nan=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

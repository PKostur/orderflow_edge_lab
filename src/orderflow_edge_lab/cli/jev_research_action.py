from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.jev_research_action import (
    JevResearchActionError,
    execute_research_action,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one bounded Jev-selected research action."
    )
    parser.add_argument("--shadow-report", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        shadow = json.loads(Path(args.shadow_report).read_text(encoding="utf-8"))
        decision = json.loads(Path(args.decision).read_text(encoding="utf-8"))
        result = execute_research_action(shadow, decision)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "selected_action": result["selected_action"],
                    "result": result["result"],
                    "authority_boundary": result["authority_boundary"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        JevResearchActionError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

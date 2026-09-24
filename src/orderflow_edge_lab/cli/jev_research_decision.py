from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.jev_research_decision import (
    JevDecisionConfig,
    JevResearchDecisionError,
    decide_sync,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Jev research-decision layer over a frozen shadow report."
    )
    parser.add_argument("--shadow-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", choices=("auto", "jev", "offline"), default="auto")
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--min-choice-confidence", type=float, default=0.65)
    parser.add_argument("--timeout-s", type=float, default=3.0)
    args = parser.parse_args(argv)

    try:
        shadow = json.loads(Path(args.shadow_report).read_text(encoding="utf-8"))
        result = decide_sync(
            shadow,
            provider=args.provider,
            config=JevDecisionConfig(
                model=args.model,
                min_choice_confidence=args.min_choice_confidence,
                timeout_s=args.timeout_s,
            ),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "decision_id": result["decision_id"],
                    "provider": result["provider"],
                    "model": result["model"],
                    "selected_action": result["policy"]["selected_action"],
                    "selection_source": result["policy"]["selection_source"],
                    "proposed_action": result["policy"]["proposed_action"],
                    "proposed_action_confidence": result["policy"][
                        "proposed_action_confidence"
                    ],
                    "hard_vetoes": result["policy"]["hard_vetoes"],
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
        JevResearchDecisionError,
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

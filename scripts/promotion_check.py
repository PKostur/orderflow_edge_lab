#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.promotion import assess_candidate_promotion_files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed candidate promotion check using validation evidence and project economics."
    )
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--economics", default="config/economics.json")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        assessment = assess_candidate_promotion_files(
            args.validation_report,
            args.candidate_id,
            args.economics,
        )
        payload = assessment.as_dict()
        if args.output:
            output = Path(args.output)
            protected = {
                Path(args.validation_report).resolve(),
                Path(args.economics).resolve(),
            }
            if output.resolve() in protected:
                raise ValueError("output must not overwrite inputs")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 0 if assessment.promotable else 3
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "promotable": False,
            "research_only": True,
            "error_type": type(exc).__name__,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

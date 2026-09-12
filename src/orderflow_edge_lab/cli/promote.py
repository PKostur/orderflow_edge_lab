#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.promotion_binding import assess_bound_promotion


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed candidate promotion check bound to frozen holdout evidence, trial accounting, and project economics."
    )
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--economics", default="config/economics.json")
    parser.add_argument("--candidate-freeze", required=True)
    parser.add_argument("--holdout-audit", required=True)
    parser.add_argument("--trial-ledger", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        assessment, binding_reasons = assess_bound_promotion(
            args.validation_report,
            args.candidate_id,
            args.economics,
            args.candidate_freeze,
            args.holdout_audit,
            args.trial_ledger,
        )
        payload = assessment.as_dict()
        payload["holdout_binding_verified"] = not binding_reasons
        payload["trial_ledger_verified"] = not any(
            reason.startswith("trial_ledger_") or reason == "holdout_trial_not_uniquely_counted"
            for reason in binding_reasons
        )
        payload["promotable"] = assessment.promotable and not binding_reasons
        payload["research_only"] = not payload["promotable"]
        payload["reasons"] = list(dict.fromkeys([*assessment.reasons, *binding_reasons]))
        if args.output:
            output = Path(args.output)
            protected = {
                Path(args.validation_report).resolve(),
                Path(args.economics).resolve(),
                Path(args.candidate_freeze).resolve(),
                Path(args.holdout_audit).resolve(),
                Path(args.trial_ledger).resolve(),
            }
            if output.resolve() in protected:
                raise ValueError("output must not overwrite inputs")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 0 if payload["promotable"] else 3
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "promotable": False,
            "research_only": True,
            "holdout_binding_verified": False,
            "trial_ledger_verified": False,
            "error_type": type(exc).__name__,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

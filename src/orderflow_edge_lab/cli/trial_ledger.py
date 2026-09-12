#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.trial_ledger import (
    TrialLedgerError,
    append_holdout_trial_files,
    new_trial_ledger,
    verify_trial_ledger,
)


def _write_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Count holdout inspections and expose the corresponding multiple-testing burden.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--family", required=True)
    create.add_argument("--alpha", type=float, default=0.05)
    create.add_argument("--output", required=True)

    append = sub.add_parser("append")
    append.add_argument("--ledger", required=True)
    append.add_argument("--holdout-audit", required=True)
    append.add_argument("--output", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--ledger", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            payload = new_trial_ledger(family_name=args.family, alpha=args.alpha)
            _write_new(Path(args.output), payload)
        elif args.command == "append":
            ledger = Path(args.ledger).resolve()
            holdout = Path(args.holdout_audit).resolve()
            output = Path(args.output).resolve()
            if output in {ledger, holdout}:
                raise TrialLedgerError("output must not overwrite inputs")
            payload = append_holdout_trial_files(ledger, holdout)
            _write_new(output, payload)
        else:
            payload = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not verify_trial_ledger(payload):
                raise TrialLedgerError("trial ledger is invalid")

        trials = payload.get("trials", [])
        current_alpha = payload.get("family_alpha") if not trials else trials[-1].get("bonferroni_alpha")
        print(json.dumps({
            "status": "ok",
            "family_name": payload.get("family_name"),
            "trial_count": len(trials),
            "family_alpha": payload.get("family_alpha"),
            "current_bonferroni_alpha": current_alpha,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
        }, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, TrialLedgerError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

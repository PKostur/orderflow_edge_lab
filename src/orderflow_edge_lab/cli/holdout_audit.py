from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.holdout_audit import HoldoutAuditError, build_holdout_audit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove that candidate observations remain inside a pre-frozen holdout interval."
    )
    parser.add_argument("--observations", required=True)
    parser.add_argument("--candidate-freeze", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        output = Path(args.output)
        protected = {
            Path(args.observations).resolve(),
            Path(args.candidate_freeze).resolve(),
            *(Path(path).resolve() for path in args.source_file),
        }
        if output.resolve() in protected:
            raise HoldoutAuditError("output must not overwrite inputs")
        manifest = build_holdout_audit(
            args.observations,
            args.candidate_freeze,
            args.candidate_id,
            source_files=args.source_file or None,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
        print(json.dumps(manifest, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, HoldoutAuditError) as exc:
        print(json.dumps({
            "holdout_partition_respected": False,
            "research_only": True,
            "error_type": type(exc).__name__,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

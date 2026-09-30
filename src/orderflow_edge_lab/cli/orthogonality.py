from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.orthogonality import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    OrthogonalityError,
    build_orthogonality_report,
    load_rows,
    orthogonality_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Indicator orthogonality, incremental information and leave-one-out stability: is a proposed "
            "feature already carried by the existing regime variables, and does the result survive removing "
            "a symbol, batch or cluster? The redundancy threshold is required from the caller."
        )
    )
    parser.add_argument("rows", help="JSON-lines or JSON array of observation objects.")
    parser.add_argument("--feature", required=True, help="Numeric column holding the proposed indicator.")
    parser.add_argument("--baseline", required=True, help="Comma-separated existing regime variables.")
    parser.add_argument("--target", required=True, help="Numeric column holding the state label or metric.")
    parser.add_argument(
        "--redundancy-threshold",
        type=float,
        required=True,
        help="Caller-declared absolute rank-correlation threshold for clustering.",
    )
    parser.add_argument("--cluster", help="Column naming the dependence cluster (batch, bar or era).")
    parser.add_argument("--group-key", help="Column to leave one unit of out for the stability block.")
    parser.add_argument("--stability-value-key", help="Column to measure stability on (default: --target).")
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON report.")
    parser.add_argument("--markdown", help="Optional path for a human-readable report.")
    return parser


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        baseline = [part.strip() for part in args.baseline.split(",") if part.strip()]
        report = build_orthogonality_report(
            load_rows(args.rows),
            feature=args.feature,
            baseline=baseline,
            target=args.target,
            redundancy_threshold=float(args.redundancy_threshold),
            cluster=args.cluster,
            group_key=args.group_key,
            stability_value_key=args.stability_value_key,
            resamples=int(args.resamples),
            confidence=float(args.confidence),
            seed=int(args.seed),
        )
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), orthogonality_markdown(report))
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, OrthogonalityError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

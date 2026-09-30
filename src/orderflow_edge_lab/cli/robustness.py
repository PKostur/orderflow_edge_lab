from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.robustness import (
    DEFAULT_CONFIDENCE,
    DEFAULT_COST_MULTIPLIERS,
    DEFAULT_RESAMPLES,
    DEFAULT_ROLE,
    DEFAULT_SEED,
    CLUSTER_KEYS,
    RobustnessError,
    build_robustness_report,
    robustness_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Post-hoc descriptive robustness for a frozen forward report: cluster bootstrap interval, "
            "minimum detectable effect at the frozen gate, concentration, friction sensitivity, control "
            "arms and negative controls. Analysis only: no verdict, no invented threshold."
        )
    )
    parser.add_argument("report", help="Frozen forward report JSON.")
    parser.add_argument("--audit-id", help="Variant audit id to analyse (default: first with the requested role).")
    parser.add_argument("--role", default=DEFAULT_ROLE, help=f"Variant role to select (default: {DEFAULT_ROLE}).")
    parser.add_argument(
        "--cluster",
        default="bar",
        choices=list(CLUSTER_KEYS),
        help="Dependence cluster unit used for resampling (default: bar).",
    )
    parser.add_argument("--bucket", help="Restrict to one session bucket.")
    parser.add_argument("--watch-config", help="Watch config, used only to report the decision-rule status.")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE)
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--family-size", type=int, help="Declared trial family size for the multiplicity bound.")
    parser.add_argument(
        "--design-clusters",
        type=int,
        help="Cluster count the frozen review gate implies, for the minimum-detectable-effect line.",
    )
    parser.add_argument(
        "--cost-multipliers",
        help=f"Comma-separated friction multipliers (default: {','.join(str(m) for m in DEFAULT_COST_MULTIPLIERS)}).",
    )
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
        multipliers = DEFAULT_COST_MULTIPLIERS
        if args.cost_multipliers:
            multipliers = tuple(float(part) for part in args.cost_multipliers.split(",") if part.strip())
        report = build_robustness_report(
            args.report,
            audit_id=args.audit_id,
            role=args.role,
            cluster=args.cluster,
            bucket=args.bucket,
            watch_config=args.watch_config,
            confidence=float(args.confidence),
            resamples=int(args.resamples),
            seed=int(args.seed),
            family_size=args.family_size,
            design_clusters=args.design_clusters,
            cost_multipliers=multipliers,
        )
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), robustness_markdown(report))
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RobustnessError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

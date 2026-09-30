from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.artifact_coverage import (
    DEFAULT_REQUIREMENTS,
    ArtifactCoverageError,
    audit_from_paths,
    coverage_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit whether the artifacts and local canonical files a predeclared "
            "prospective review needs are still retrievable. Reporting only: it "
            "deletes nothing, extends nothing, counts no evidence, and computes "
            "no strategy verdict."
        )
    )
    parser.add_argument(
        "--requirements",
        default=str(DEFAULT_REQUIREMENTS),
        help="Frozen retention requirements JSON (default: config/evidence_retention_requirements_v1.json).",
    )
    parser.add_argument(
        "--inventory",
        help=(
            "Observed artifact inventory: a 'gh api .../actions/artifacts' payload, a JSON list, "
            "or JSON-lines of artifact objects. Omit to audit local files only."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Root used to resolve declared local canonical file paths (default: .).",
    )
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON report.")
    parser.add_argument("--markdown", help="Optional path for a human-readable markdown summary.")
    return parser


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_from_paths(
            Path(args.requirements),
            Path(args.inventory) if args.inventory else None,
            repo_root=Path(args.repo_root),
        )
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), coverage_markdown(report))
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, ArtifactCoverageError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

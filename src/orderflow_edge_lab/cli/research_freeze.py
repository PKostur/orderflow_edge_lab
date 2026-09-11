from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from orderflow_edge_lab.research_protocol import (
    ResearchProtocolError,
    _parse_utc,
    build_research_freeze,
    load_audit,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze discovery, validation and untouched holdout boundaries against exact audited source bytes. "
            "This creates research provenance only and does not certify an edge."
        )
    )
    parser.add_argument("audit", nargs="+", help="One or more orderflow-export-audit JSON artifacts")
    parser.add_argument("--discovery-end", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--validation-end", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--holdout-end", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--embargo-seconds", type=int, default=0)
    parser.add_argument("--name", default="default")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    audit_paths = [Path(item) for item in args.audit]
    try:
        protected = {path.expanduser().resolve() for path in audit_paths}
        if output.expanduser().resolve() in protected:
            raise ResearchProtocolError("output must not overwrite an input audit")
        reports = [load_audit(path) for path in audit_paths]
        manifest = build_research_freeze(
            reports,
            discovery_end=_parse_utc(args.discovery_end),
            validation_end=_parse_utc(args.validation_end),
            holdout_end=_parse_utc(args.holdout_end),
            embargo_seconds=args.embargo_seconds,
            protocol_name=args.name,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except (OSError, ValueError, TypeError, KeyError, ResearchProtocolError) as exc:
        print(json.dumps({"created": False, "research_only": True, "error_type": type(exc).__name__, "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({
        "created": True,
        "research_only": True,
        "manifest_sha256": manifest["manifest_sha256"],
        "output": str(output),
        "source_count": len(manifest["sources"]),
        "verified_out_of_sample_evidence": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

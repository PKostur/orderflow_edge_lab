from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.candidate_freeze import CandidateFreezeError, build_candidate_freeze


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze exact candidate specifications against an existing research freeze before holdout inspection. "
            "This records provenance only and does not certify profitability or enable live trading."
        )
    )
    parser.add_argument("--registry", default="config/candidates.json")
    parser.add_argument("--research-freeze", required=True)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    registry = Path(args.registry)
    research_freeze = Path(args.research_freeze)
    try:
        protected = {registry.expanduser().resolve(), research_freeze.expanduser().resolve()}
        if output.expanduser().resolve() in protected:
            raise CandidateFreezeError("output must not overwrite an input")
        manifest = build_candidate_freeze(
            registry,
            research_freeze,
            candidate_ids=args.candidate_id or None,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except (OSError, ValueError, TypeError, KeyError, CandidateFreezeError) as exc:
        print(json.dumps({
            "created": False,
            "research_only": True,
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }, sort_keys=True))
        return 2
    print(json.dumps({
        "created": True,
        "research_only": True,
        "manifest_sha256": manifest["manifest_sha256"],
        "candidate_count": len(manifest["candidates"]),
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
        "live_order_transmission_supported": False,
        "output": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

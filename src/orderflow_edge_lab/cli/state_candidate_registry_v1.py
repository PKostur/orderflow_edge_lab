from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.state_candidate_registry_v1 import build_state_candidate_registry_v1_from_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic PnL-independent single-candidate registry from a v1.2 state promotion report."
    )
    parser.add_argument("promotion_report", help="state_promotion_report_v1_2 JSON")
    parser.add_argument("--protocol", default="config/state_candidate_registry_v1.json")
    parser.add_argument("--prior-registry", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    registry = build_state_candidate_registry_v1_from_paths(
        args.promotion_report,
        args.protocol,
        prior_registry_paths=args.prior_registry,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "eligible_candidate_count": registry["eligible_candidate_count"],
                "locked_candidate": registry["locked_candidate"],
                "selection_newly_locked": registry["selection_newly_locked"],
                "claims": registry["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

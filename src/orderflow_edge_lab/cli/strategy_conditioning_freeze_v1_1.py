from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.strategy_conditioning_freeze_v1_1 import build_strategy_conditioning_freeze_v1_1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze one regime-research-v1.2 state hypothesis for a strategy-conditioning-v1.1 trial."
    )
    parser.add_argument("state_screen", help="regime-research-v1.2 state aggregate JSON")
    parser.add_argument("--protocol", default="config/strategy_conditioning_v1_1.json")
    parser.add_argument("--research-family", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    frozen = build_strategy_conditioning_freeze_v1_1(
        args.state_screen,
        args.protocol,
        research_family=args.research_family,
        feature=args.feature,
        target=args.target,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(frozen, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "protocol_name": frozen["protocol_name"],
                "state_hypothesis": frozen["state_hypothesis"],
                "manifest_sha256": frozen["manifest_sha256"],
                "claims": frozen["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

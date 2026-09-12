from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.strategy_conditioning_freeze import build_strategy_conditioning_freeze


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze one regime-research-v1.1-qualified market-state hypothesis before strategy-conditioning PnL is inspected."
    )
    parser.add_argument("--state-screen", required=True)
    parser.add_argument("--protocol", default="config/strategy_conditioning_v1.json")
    parser.add_argument("--research-family", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = build_strategy_conditioning_freeze(
        args.state_screen,
        args.protocol,
        research_family=args.research_family,
        feature=args.feature,
        target=args.target,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "protocol_name": report["protocol_name"],
        "state_hypothesis": report["state_hypothesis"],
        "manifest_sha256": report["manifest_sha256"],
        "claims": report["claims"],
    }, indent=2))


if __name__ == "__main__":
    main()

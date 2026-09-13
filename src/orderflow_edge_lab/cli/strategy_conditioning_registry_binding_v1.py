from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.strategy_conditioning_registry_binding_v1 import build_registry_bound_conditioning_freeze_v1


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind strategy-conditioning-v1.1 to the deterministic state-candidate-registry-v1 lock.")
    parser.add_argument("state_screen")
    parser.add_argument("registry")
    parser.add_argument("--binding-protocol", default="config/strategy_conditioning_registry_binding_v1.json")
    parser.add_argument("--conditioning-protocol", default="config/strategy_conditioning_v1_1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_registry_bound_conditioning_freeze_v1(
        args.state_screen,
        args.registry,
        args.binding_protocol,
        args.conditioning_protocol,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result["status"], "manifest_sha256": result["manifest_sha256"]}, indent=2))


if __name__ == "__main__":
    main()

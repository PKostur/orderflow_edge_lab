from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.state_threshold_freeze_v1 import build_state_threshold_freeze_v1


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze PnL-independent market-state thresholds for the deterministic v1.2 conditioning candidate.")
    parser.add_argument("state_screen")
    parser.add_argument("registry_binding")
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--protocol", default="config/state_threshold_freeze_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_state_threshold_freeze_v1(
        args.state_screen,
        args.registry_binding,
        args.protocol,
        args.reports,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result["status"], "manifest_sha256": result["manifest_sha256"]}, indent=2))


if __name__ == "__main__":
    main()

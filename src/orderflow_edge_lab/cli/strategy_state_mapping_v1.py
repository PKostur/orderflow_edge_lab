from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.strategy_state_mapping_v1 import build_strategy_state_mapping_v1


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the PnL-independent market-state bucket used by the conditioning trial.")
    parser.add_argument("threshold_freeze")
    parser.add_argument("--protocol", default="config/strategy_state_mapping_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_strategy_state_mapping_v1(args.threshold_freeze, args.protocol)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result["status"], "manifest_sha256": result["manifest_sha256"]}, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.conditioned_experiment_v1 import run_conditioned_experiment_v1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the frozen discovery-v1 baseline versus the PnL-independently conditioned arm."
    )
    parser.add_argument("features")
    parser.add_argument("market_state")
    parser.add_argument("strategy_state_mapping")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = run_conditioned_experiment_v1(
        args.features,
        args.market_state,
        args.strategy_state_mapping,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

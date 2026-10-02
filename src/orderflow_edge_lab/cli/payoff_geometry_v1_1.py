from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.payoff_geometry_v1_1 import build_payoff_geometry_v1_1_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run universal-payoff-geometry-diagnostics-v1 (payoff geometry v1.1)."
    )
    parser.add_argument(
        "--protocol",
        default="config/universal_existing_strategy_backtests_v1.json",
    )
    parser.add_argument("--config", default="config/payoff_geometry_v1_1.json")
    parser.add_argument("--v1-config", default="config/payoff_geometry_v1.json")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)

    report = build_payoff_geometry_v1_1_report(
        args.protocol,
        args.config,
        args.v1_config,
        args.data_dir,
        as_of=args.as_of,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "analysis": report["analysis"],
                "protocol_id": report["protocol_id"],
                "fixed_cell_count_per_strategy_direction": report[
                    "fixed_cell_count_per_strategy_direction"
                ],
                "cell_set_sha256": report["cell_set_sha256"],
                "output": str(output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

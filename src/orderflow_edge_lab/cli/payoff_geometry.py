from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.payoff_geometry import build_payoff_geometry_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run predeclared non-gating payoff geometry diagnostics."
    )
    parser.add_argument(
        "--protocol",
        default="config/universal_existing_strategy_backtests_v1.json",
    )
    parser.add_argument(
        "--geometry-config",
        default="config/payoff_geometry_v1.json",
    )
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    report = build_payoff_geometry_report(
        args.protocol,
        args.geometry_config,
        args.data_dir,
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
                "status": report["status"],
                "fixed_cell_count_per_strategy": report["fixed_cell_count_per_strategy"],
                "cell_set_sha256": report["cell_set_sha256"],
                "cost_cases": [row["cost_bps"] for row in report["cost_cases"]],
                "output": str(output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

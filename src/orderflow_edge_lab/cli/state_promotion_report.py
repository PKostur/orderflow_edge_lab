from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.state_promotion_report import build_state_promotion_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a PnL-independent promotion report from a regime-research-v1.1 state aggregate."
    )
    parser.add_argument("aggregate", help="regime-research-v1.1 market-state aggregate JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    aggregate = json.loads(Path(args.aggregate).read_text(encoding="utf-8"))
    report = build_state_promotion_report(aggregate)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "source_status": report["source_status"],
                "independent_batch_count": report["independent_batch_count"],
                "candidate_count": report["candidate_count"],
                "claims": report["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

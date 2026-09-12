from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.risk_ladder import DEFAULT_EXPOSURE_MULTIPLES, DEFAULT_FEES_BPS, evaluate_risk_ladder


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental exposure stress test for paired original/reversed order-flow reports")
    parser.add_argument("paired_report")
    parser.add_argument("--output", required=True)
    parser.add_argument("--starting-equity", type=float, default=100.0)
    parser.add_argument("--exposure", type=float, action="append", dest="exposures")
    parser.add_argument("--fee-bps", type=float, action="append", dest="fees")
    args = parser.parse_args()

    report = evaluate_risk_ladder(
        args.paired_report,
        exposure_multiples=tuple(args.exposures or DEFAULT_EXPOSURE_MULTIPLES),
        fee_bps_cases=tuple(args.fees or DEFAULT_FEES_BPS),
        starting_equity=args.starting_equity,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing report: {out}")
    out.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": report["experiment"],
        "starting_equity": report["starting_equity"],
        "exposure_multiples": report["exposure_multiples"],
        "fee_bps_cases": report["fee_bps_cases"],
        "claims": report["claims"],
    }, indent=2))
    for row in report["results"]:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

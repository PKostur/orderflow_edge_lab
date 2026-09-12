from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.discovery_aggregate import aggregate, verify_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate fixed-protocol order-flow discovery reports by capture batch"
    )
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = aggregate(args.reports, args.protocol)
    if not verify_manifest(report):
        raise SystemExit("generated aggregate manifest failed verification")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing aggregate: {out}")
    out.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "batches": report["batches"],
        "feature_rows_total": report["feature_rows_total"],
        "signals_total": report["signals_total"],
        "manifest_sha256": report["manifest_sha256"],
        "claims": report["claims"],
    }, indent=2))
    for row in report["summary"]:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

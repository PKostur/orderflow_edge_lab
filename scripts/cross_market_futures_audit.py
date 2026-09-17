from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path

from orderflow_edge_lab.adapters import normalize_dxfeed_rows
from orderflow_edge_lab.cross_market_futures import audit_native_futures_events, futures_spec
from orderflow_edge_lab.data import DataQualityPolicy, quality_report


def _parse_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("input must be ROOT=path.csv, for example ES=data/ESZ26.csv")
    root, raw_path = value.split("=", 1)
    root = root.strip().upper()
    futures_spec(root)
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file does not exist: {path}")
    return root, path


def audit_file(root: str, path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        adapted = normalize_dxfeed_rows(
            csv.DictReader(handle),
            reject_timestamp_regressions=True,
        )
    policy = DataQualityPolicy(
        min_events=100,
        require_monotonic_timestamps=True,
        require_trades=True,
    )
    quality = quality_report(adapted.events, policy)
    native = audit_native_futures_events(adapted.events, root=root, require_single_symbol=True)
    return {
        "root": root,
        "path": str(path),
        "adapter_stats": asdict(adapted.stats),
        "quality": asdict(quality),
        "native_contract_audit": native,
        "passed": bool(quality.passed and native["passed"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit native-contract dxFeed/DeepCharts futures exports before any cross-market PnL research."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=_parse_input,
        metavar="ROOT=CSV",
        help="Repeat for ES, NQ, GC or CL. CSV must retain its native contract symbol.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = {
        "research_id": "cross_market_futures_v1",
        "stage": "DATA_INTEGRITY_ONLY",
        "results": [audit_file(root, path) for root, path in args.input],
    }
    report["passed"] = all(item["passed"] for item in report["results"])
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

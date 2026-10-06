from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.capture_health import DEFAULT_DATA_DIR
from orderflow_edge_lab.ops_digest_v2 import (
    DEFAULT_LEDGER_MANIFEST,
    OpsDigestError,
    build_ops_digest,
    digest_markdown,
)
from orderflow_edge_lab.review_clock import DEFAULT_CONFIG as DEFAULT_CLOCK_CONFIG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One daily digest of the wait window: elapsed watch time, capture "
            "freshness, cumulative ledger batch count, and optional retention "
            "coverage findings. Aggregation and reporting only."
        )
    )
    parser.add_argument(
        "--clock-config",
        default=str(DEFAULT_CLOCK_CONFIG),
        help="Frozen prospective review clock config.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory containing recorded captures (default: data/mexc_orderflow).",
    )
    parser.add_argument(
        "--ledger-manifest",
        default=str(DEFAULT_LEDGER_MANIFEST),
        help="Cumulative discovery ledger manifest to report batch counts from.",
    )
    parser.add_argument(
        "--coverage-report",
        help="Optional artifact coverage report JSON to fold into the digest.",
    )
    parser.add_argument(
        "--inventory-acquisition",
        help="Explicit CI artifact inventory acquisition JSON; FAILED is an operational error, never an empty inventory.",
    )
    parser.add_argument(
        "--ledger-retrieval",
        help="Optional newest-ledger artifact retrieval metadata JSON.",
    )
    parser.add_argument(
        "--stale-after-hours",
        type=float,
        default=26.0,
        help="Capture staleness threshold used for the digest alerts (default: 26).",
    )
    parser.add_argument(
        "--ledger-heartbeat-cadence-hours",
        type=float,
        help="Caller-declared ledger heartbeat cadence; provide with --ledger-heartbeat-grace-hours.",
    )
    parser.add_argument(
        "--ledger-heartbeat-grace-hours",
        type=float,
        help="Caller-declared ledger heartbeat grace; provide with --ledger-heartbeat-cadence-hours.",
    )
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON digest.")
    parser.add_argument("--markdown", help="Optional path for a human-readable digest.")
    return parser


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        coverage = None
        if args.coverage_report:
            coverage_path = Path(args.coverage_report)
            if coverage_path.is_file():
                coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        inventory_acquisition = None
        if args.inventory_acquisition:
            inventory_acquisition = json.loads(Path(args.inventory_acquisition).read_text(encoding="utf-8"))
        ledger_retrieval = None
        if args.ledger_retrieval:
            ledger_retrieval = json.loads(Path(args.ledger_retrieval).read_text(encoding="utf-8"))
        digest = build_ops_digest(
            clock_config=Path(args.clock_config),
            data_dir=Path(args.data_dir),
            ledger_manifest=Path(args.ledger_manifest) if args.ledger_manifest else None,
            coverage_report=coverage,
            inventory_acquisition=inventory_acquisition,
            ledger_retrieval=ledger_retrieval,
            stale_after_hours=float(args.stale_after_hours),
            ledger_heartbeat_cadence_hours=args.ledger_heartbeat_cadence_hours,
            ledger_heartbeat_grace_hours=args.ledger_heartbeat_grace_hours,
        )
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(digest, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), digest_markdown(digest))
        print(json.dumps(digest, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, OpsDigestError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

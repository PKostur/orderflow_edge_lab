from __future__ import annotations

import argparse
import json

from orderflow_edge_lab.mexc_capture_audit import CaptureAuditError, CaptureAuditPolicy, audit_capture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed integrity audit for a recorded MEXC order-flow capture.")
    parser.add_argument("raw")
    parser.add_argument("features")
    parser.add_argument("--min-duration-seconds", type=float, default=60.0)
    parser.add_argument("--min-depth-apply-fraction", type=float, default=0.95)
    parser.add_argument("--max-gap-rate-per-minute", type=float, default=1.0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    policy = CaptureAuditPolicy(
        min_duration_seconds=args.min_duration_seconds,
        min_depth_apply_fraction=args.min_depth_apply_fraction,
        max_gap_rate_per_minute=args.max_gap_rate_per_minute,
    )
    try:
        report = audit_capture(args.raw, args.features, policy=policy)
    except (ValueError, CaptureAuditError) as exc:
        parser.error(str(exc))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from orderflow_edge_lab.adapters import normalize_dxfeed_rows
from orderflow_edge_lab.cross_market_futures import audit_native_futures_events, futures_spec
from orderflow_edge_lab.cross_market_futures_transfer import evaluate_feature_rows
from orderflow_edge_lab.data import DataQualityPolicy, quality_report
from orderflow_edge_lab.dxfeed_futures_features import build_dxfeed_level1_feature_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run frozen cross-market futures v1 H1/H3 transfer replay on one native-contract dxFeed/DeepCharts CSV."
    )
    parser.add_argument("--root", required=True, choices=["ES", "NQ", "GC", "CL"])
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--default-symbol", default=None)
    args = parser.parse_args()

    spec = futures_spec(args.root)
    if not args.input.is_file():
        raise SystemExit(f"input file does not exist: {args.input}")
    raw_bytes = args.input.read_bytes()
    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if not rows:
        raise SystemExit("input CSV has no rows")

    adapted = normalize_dxfeed_rows(
        rows,
        default_symbol=args.default_symbol,
        reject_timestamp_regressions=True,
    )
    quality = quality_report(
        adapted.events,
        DataQualityPolicy(min_events=100, require_monotonic_timestamps=True, require_trades=True),
    )
    native = audit_native_futures_events(adapted.events, root=args.root, require_single_symbol=True)
    if not quality.passed or not native["passed"]:
        payload = {
            "research_id": "cross_market_futures_v1",
            "stage": "DATA_INTEGRITY_FAILED",
            "root": spec.root,
            "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "quality": {
                "passed": quality.passed,
                "failures": list(quality.failures),
                "total_events": quality.total_events,
                "trade_events": quality.trade_events,
            },
            "native_contract_audit": native,
            "claims": {
                "persistent_edge_established": False,
                "candidate_promoted": False,
                "live_execution_supported": False,
                "leverage_supported": False,
            },
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2

    built = build_dxfeed_level1_feature_rows(rows, default_symbol=args.default_symbol)
    replay = evaluate_feature_rows(built.rows, root=args.root)
    report = {
        **replay,
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "source_file_name": args.input.name,
        "native_contract_audit": native,
        "data_quality": {
            "passed": quality.passed,
            "failures": list(quality.failures),
            "total_events": quality.total_events,
            "trade_events": quality.trade_events,
            "quote_events": quality.quote_events,
        },
        "level1_build": {
            "trade_rows": built.trade_rows,
            "quote_rows": built.quote_rows,
            "trades_with_size": built.trades_with_size,
            "trades_with_classified_side": built.trades_with_classified_side,
            "trades_with_eligible_prior_bbo_sizes": built.trades_with_eligible_prior_bbo_sizes,
            "ambiguous_same_timestamp_bbo_uses_blocked": built.ambiguous_same_timestamp_bbo_uses_blocked,
            "stale_bbo_uses_blocked": built.stale_bbo_uses_blocked,
            "H1_data_eligible": built.h1_eligible,
            "H2_data_eligible": False,
            "H2_reason": "Level-1 runner does not synthesize frozen top-10 displayed depth imbalance.",
            "H3_data_eligible": built.h3_eligible,
        },
        "research_boundary": {
            "transfer_discovery_only": True,
            "single_file_result_cannot_pass_D0_transfer_gate": True,
            "requires_multi_market_multi_session_aggregation": True,
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "feature_rows.jsonl").open("w", encoding="utf-8") as handle:
        for row in built.rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "root": report["root"],
                "source_sha256": report["source_sha256"],
                "signals": report["signals"],
                "signal_counts_by_family": report["signal_counts_by_family"],
                "level1_build": report["level1_build"],
                "claims": report["claims"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

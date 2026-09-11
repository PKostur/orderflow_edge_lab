from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path

from orderflow_edge_lab.adapters import normalize_dxfeed_rows
from orderflow_edge_lab.data import DataQualityPolicy, quality_report
from orderflow_edge_lab.dxfeed_bbo import compute_bbo_ofi, extract_bbo_samples


def _read_rows(path: Path) -> tuple[bytes, list[dict[str, str]]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ValueError("export contains no data rows")
    return raw, rows


def audit_export(
    path: Path,
    *,
    default_symbol: str | None,
    min_events: int,
    min_bbo_size_samples: int,
    allow_quote_only: bool,
) -> dict[str, object]:
    raw, rows = _read_rows(path)
    adapted = normalize_dxfeed_rows(
        rows,
        default_symbol=default_symbol,
        reject_timestamp_regressions=True,
    )
    quality = quality_report(
        adapted.events,
        DataQualityPolicy(
            min_events=min_events,
            require_trades=not allow_quote_only,
            require_monotonic_timestamps=True,
        ),
    )
    extracted = extract_bbo_samples(
        rows,
        default_symbol=default_symbol,
        reject_timestamp_regressions=True,
    )
    ofi_events, ofi_stats = compute_bbo_ofi(extracted.samples)

    symbols = sorted({event.symbol for event in adapted.events})
    by_symbol: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        symbol_ofi = [event.ofi for event in ofi_events if event.symbol == symbol]
        by_symbol[symbol] = {
            "events": sum(event.symbol == symbol for event in adapted.events),
            "trades": sum(event.symbol == symbol and event.kind == "TRADE" for event in adapted.events),
            "quotes": sum(event.symbol == symbol and event.kind == "QUOTE" for event in adapted.events),
            "bbo_size_samples": sum(sample.symbol == symbol for sample in extracted.samples),
            "ofi_events": len(symbol_ofi),
            "ofi_sum": sum(symbol_ofi),
            "ofi_mean": (sum(symbol_ofi) / len(symbol_ofi)) if symbol_ofi else None,
        }

    trade_flow_eligible = quality.passed
    bbo_ofi_eligible = (
        quality.passed
        and extracted.stats.complete_size_samples >= min_bbo_size_samples
        and extracted.stats.locked_or_crossed_rows == 0
        and extracted.stats.timestamp_regressions == 0
        and ofi_stats.timestamp_regressions == 0
    )

    return {
        "schema_version": 1,
        "source_file": path.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(rows),
        "symbols": symbols,
        "adapter": asdict(adapted.stats),
        "quality": asdict(quality),
        "bbo": {
            **asdict(extracted.stats),
            "size_coverage_fraction": extracted.stats.size_coverage_fraction,
        },
        "ofi": asdict(ofi_stats),
        "by_symbol": by_symbol,
        "research_eligibility": {
            "trade_flow": trade_flow_eligible,
            "bbo_ofi": bbo_ofi_eligible,
            "minimum_bbo_size_samples": min_bbo_size_samples,
            "interpretation": (
                "Eligibility only means the export passed structural and causal data checks. "
                "It is not evidence of a profitable trading edge."
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit a local dxFeed/DeepCharts CSV export for causal trade-flow and best-level OFI research. "
            "No network or broker access is used."
        )
    )
    parser.add_argument("export", type=Path)
    parser.add_argument("--symbol", help="Default symbol when the export omits a symbol column")
    parser.add_argument("--min-events", type=int, default=100)
    parser.add_argument("--min-bbo-size-samples", type=int, default=100)
    parser.add_argument("--allow-quote-only", action="store_true")
    parser.add_argument(
        "--require-ofi-eligible",
        action="store_true",
        help="Return a failing exit code unless the export is eligible for BBO OFI research",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.min_events < 1 or args.min_bbo_size_samples < 1:
        parser.error("minimum sample counts must be positive")
    try:
        report = audit_export(
            args.export,
            default_symbol=args.symbol,
            min_events=args.min_events,
            min_bbo_size_samples=args.min_bbo_size_samples,
            allow_quote_only=args.allow_quote_only,
        )
    except (OSError, UnicodeError, csv.Error, ValueError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2

    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.require_ofi_eligible and not report["research_eligibility"]["bbo_ofi"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

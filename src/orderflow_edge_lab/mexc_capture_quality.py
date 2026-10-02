from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


class MexcCaptureQualityError(ValueError):
    pass


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def audit_mexc_feature_capture(
    feature_path: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    path = Path(feature_path)
    raw = path.read_bytes()
    expected = [str(v) for v in config["expected_symbols"]]
    per_symbol: dict[str, dict[str, Any]] = {
        symbol: {
            "feature_rows": 0,
            "event_counts": Counter(),
            "valid_book_rows": 0,
            "received_at_ns_first": None,
            "received_at_ns_last": None,
            "timestamp_regressions": 0,
            "_last_received_at_ns": None,
        }
        for symbol in expected
    }
    summary: Mapping[str, Any] | None = None
    malformed_rows = 0
    unknown_symbols: set[str] = set()
    total_lines = 0

    for lineno, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        total_lines += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MexcCaptureQualityError(f"invalid JSON at line {lineno}") from exc
        if not isinstance(row, dict):
            malformed_rows += 1
            continue
        if row.get("record_type") == "session_summary":
            summary = row
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str):
            malformed_rows += 1
            continue
        if symbol not in per_symbol:
            unknown_symbols.add(symbol)
            continue
        state = per_symbol[symbol]
        state["feature_rows"] += 1
        event_type = str(row.get("event_type") or "unknown")
        state["event_counts"][event_type] += 1

        bid = _finite(row.get("best_bid"))
        ask = _finite(row.get("best_ask"))
        if bid is not None and ask is not None and bid > 0 and ask > bid:
            state["valid_book_rows"] += 1

        received = row.get("received_at_ns")
        if isinstance(received, int) and received > 0:
            if state["received_at_ns_first"] is None:
                state["received_at_ns_first"] = received
            state["received_at_ns_last"] = received
            previous = state["_last_received_at_ns"]
            if previous is not None and received < previous:
                state["timestamp_regressions"] += 1
            state["_last_received_at_ns"] = received

    if summary is None:
        raise MexcCaptureQualityError("session_summary is missing")
    depth_stats = summary.get("depth_stats")
    if not isinstance(depth_stats, dict):
        raise MexcCaptureQualityError("session_summary.depth_stats is missing")
    reconnects = int(summary.get("reconnects") or 0)

    rows: list[dict[str, Any]] = []
    hard_fail_reasons: list[str] = []
    warning_reasons: list[str] = []
    minimum_book_fraction = float(config["minimum_valid_book_fraction"])
    for symbol in expected:
        state = per_symbol[symbol]
        count = int(state["feature_rows"])
        fraction = state["valid_book_rows"] / count if count else 0.0
        stats = depth_stats.get(symbol) if isinstance(depth_stats.get(symbol), dict) else {}
        depth_messages = int(stats.get("depth_messages_seen") or 0)
        true_gaps = int(stats.get("true_depth_gaps_seen") or 0)
        stale = int(stats.get("stale_depth_messages_seen") or 0)
        compressed = int(stats.get("compressed_depth_ranges_seen") or 0)
        duration_seconds = None
        if state["received_at_ns_first"] is not None and state["received_at_ns_last"] is not None:
            duration_seconds = (
                state["received_at_ns_last"] - state["received_at_ns_first"]
            ) / 1_000_000_000.0

        if count == 0:
            hard_fail_reasons.append(f"missing_symbol_rows:{symbol}")
        if int(state["timestamp_regressions"]) > 0:
            hard_fail_reasons.append(f"timestamp_regression:{symbol}")
        if fraction < minimum_book_fraction:
            warning_reasons.append(f"low_valid_book_fraction:{symbol}")
        if true_gaps > 0:
            warning_reasons.append(f"recovered_depth_gaps:{symbol}")

        rows.append(
            {
                "symbol": symbol,
                "feature_rows": count,
                "event_counts": dict(sorted(state["event_counts"].items())),
                "valid_book_rows": int(state["valid_book_rows"]),
                "valid_book_fraction": fraction,
                "timestamp_regressions": int(state["timestamp_regressions"]),
                "capture_duration_seconds": duration_seconds,
                "depth_messages_seen": depth_messages,
                "compressed_depth_ranges_seen": compressed,
                "true_depth_gaps_seen": true_gaps,
                "stale_depth_messages_seen": stale,
                "stale_depth_fraction": stale / depth_messages if depth_messages else None,
                "true_depth_gap_fraction": true_gaps / depth_messages if depth_messages else None,
            }
        )

    if unknown_symbols:
        warning_reasons.append("unknown_symbols:" + ",".join(sorted(unknown_symbols)))
    if malformed_rows:
        hard_fail_reasons.append(f"malformed_feature_rows:{malformed_rows}")
    if reconnects:
        warning_reasons.append(f"reconnects:{reconnects}")

    status = "FAIL" if hard_fail_reasons else "WARN" if warning_reasons else "PASS"
    return {
        "schema_version": 1,
        "analysis": "mexc_capture_quality_v1",
        "source_file": path.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_symbols": expected,
        "observed_expected_symbol_count": sum(row["feature_rows"] > 0 for row in rows),
        "total_nonblank_lines": total_lines,
        "malformed_feature_rows": malformed_rows,
        "reconnects": reconnects,
        "status": status,
        "hard_fail_reasons": hard_fail_reasons,
        "warning_reasons": warning_reasons,
        "per_symbol": rows,
        "claims": {
            "data_integrity_diagnostic_only": True,
            "strategy_pnl_used": False,
            "retroactive_evidence_exclusion_authorized": False,
            "strategy_parameters_changed": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
        },
    }


def aggregate_capture_quality(
    report_paths: list[str | Path],
) -> dict[str, Any]:
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in report_paths]
    if not reports:
        raise MexcCaptureQualityError("no quality reports supplied")
    for row in reports:
        if row.get("analysis") != "mexc_capture_quality_v1":
            raise MexcCaptureQualityError("unexpected quality report")
    status_counts = Counter(str(row.get("status")) for row in reports)
    symbol_stats: dict[str, dict[str, float]] = {}
    symbols = sorted({
        str(item["symbol"])
        for report in reports
        for item in report.get("per_symbol") or []
    })
    for symbol in symbols:
        items=[
            item
            for report in reports
            for item in report.get("per_symbol") or []
            if str(item.get("symbol")) == symbol
        ]
        fractions=[float(item["valid_book_fraction"]) for item in items]
        gaps=sum(int(item.get("true_depth_gaps_seen") or 0) for item in items)
        stale=sum(int(item.get("stale_depth_messages_seen") or 0) for item in items)
        messages=sum(int(item.get("depth_messages_seen") or 0) for item in items)
        symbol_stats[symbol]={
            "report_count":len(items),
            "median_valid_book_fraction":sorted(fractions)[len(fractions)//2] if fractions else 0.0,
            "total_true_depth_gaps":gaps,
            "total_stale_depth_messages":stale,
            "total_depth_messages":messages,
            "aggregate_true_depth_gap_fraction":gaps/messages if messages else 0.0,
            "aggregate_stale_depth_fraction":stale/messages if messages else 0.0,
        }
    return {
        "schema_version":1,
        "analysis":"mexc_capture_quality_aggregate_v1",
        "report_count":len(reports),
        "status_counts":dict(sorted(status_counts.items())),
        "total_reconnects":sum(int(row.get("reconnects") or 0) for row in reports),
        "total_hard_fail_reasons":sum(len(row.get("hard_fail_reasons") or []) for row in reports),
        "total_warning_reasons":sum(len(row.get("warning_reasons") or []) for row in reports),
        "per_symbol":symbol_stats,
        "claims":{
            "data_integrity_diagnostic_only":True,
            "strategy_pnl_used":False,
            "retroactive_evidence_exclusion_authorized":False,
            "profitable_edge_established":False,
            "live_trading_authorized":False,
        },
    }

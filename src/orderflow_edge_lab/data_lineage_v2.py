"""Exact-nanosecond v2 CSV lineage diagnostics.

The legacy v1 profiler remains untouched.  This opt-in successor reuses the
repository's Decimal-based timestamp parser and records integer UTC nanoseconds
for ordering comparisons, so adjacent nanoseconds cannot collapse through a
float/datetime projection.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
from pathlib import Path
from typing import Any

from orderflow_edge_lab.data import parse_timestamp_ns
from orderflow_edge_lab.data_lineage import (
    ExportProfileError,
    _HashingReader,
    _canonical,
    _find_column,
    verify_csv_export,
)


LINEAGE_V2_SCHEMA_VERSION = 2


def _format_ns(timestamp_ns: int) -> str:
    seconds, nanos = divmod(timestamp_ns, 1_000_000_000)
    base = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return base.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


def _unsigned_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "manifest_sha256"}


def profile_csv_export_v2(
    path: str | Path,
    *,
    delimiter: str = ",",
    timestamp_column: str | None = None,
    symbol_column: str | None = None,
    max_symbol_samples: int = 32,
) -> dict[str, Any]:
    """Profile one local CSV stream with exact integer-nanosecond diagnostics."""
    source = Path(path)
    if len(delimiter) != 1:
        raise ValueError("delimiter must be exactly one character")
    if type(max_symbol_samples) is not int or max_symbol_samples < 1:
        raise ValueError("max_symbol_samples must be a positive integer")
    digest = hashlib.sha256()
    row_chain = "GENESIS"
    row_count = timestamp_count = timestamp_parse_errors = timestamp_regressions = 0
    first_ns: int | None = None
    last_ns: int | None = None
    minimum_ns: int | None = None
    maximum_ns: int | None = None
    previous_ns: int | None = None
    symbols: set[str] = set()
    symbol_overflow = False
    try:
        raw = source.open("rb")
    except OSError as exc:
        raise ExportProfileError(f"cannot open export: {source}") from exc
    try:
        hashing_raw = _HashingReader(raw, digest)
        buffered = io.BufferedReader(hashing_raw)
        text = io.TextIOWrapper(buffered, encoding="utf-8-sig", errors="strict", newline="")
        try:
            reader = csv.reader(text, delimiter=delimiter, strict=True)
            try:
                columns = next(reader)
            except StopIteration as exc:
                raise ExportProfileError("export is empty") from exc
            if not columns or not any(column.strip() for column in columns):
                raise ExportProfileError("export header is empty")
            if any(not column.strip() for column in columns):
                raise ExportProfileError("export contains a blank column name")
            folded = [column.strip().casefold() for column in columns]
            if len(set(folded)) != len(folded):
                raise ExportProfileError("export contains duplicate column names")
            chosen_timestamp = timestamp_column or _find_column(columns, ("timestamp", "time", "datetime", "event_time", "eventtime", "trade_time", "tradetime"))
            chosen_symbol = symbol_column or _find_column(columns, ("symbol", "instrument", "contract"))
            if chosen_timestamp is not None and chosen_timestamp not in columns:
                raise ExportProfileError(f"timestamp column not found: {chosen_timestamp}")
            if chosen_symbol is not None and chosen_symbol not in columns:
                raise ExportProfileError(f"symbol column not found: {chosen_symbol}")
            timestamp_index = columns.index(chosen_timestamp) if chosen_timestamp else None
            symbol_index = columns.index(chosen_symbol) if chosen_symbol else None
            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(columns):
                    raise ExportProfileError(f"row {line_number} has {len(row)} fields; expected {len(columns)}")
                row_count += 1
                payload = _canonical(row)
                row_chain = hashlib.sha256((bytes.fromhex(row_chain) if row_chain != "GENESIS" else b"GENESIS") + payload).hexdigest()
                if timestamp_index is not None:
                    try:
                        parsed_ns = parse_timestamp_ns(row[timestamp_index])
                    except (ValueError, OverflowError, OSError):
                        timestamp_parse_errors += 1
                    else:
                        timestamp_count += 1
                        if first_ns is None:
                            first_ns = parsed_ns
                        last_ns = parsed_ns
                        minimum_ns = parsed_ns if minimum_ns is None else min(minimum_ns, parsed_ns)
                        maximum_ns = parsed_ns if maximum_ns is None else max(maximum_ns, parsed_ns)
                        if previous_ns is not None and parsed_ns < previous_ns:
                            timestamp_regressions += 1
                        previous_ns = parsed_ns
                if symbol_index is not None:
                    symbol = row[symbol_index].strip()
                    if symbol:
                        if len(symbols) < max_symbol_samples or symbol in symbols:
                            symbols.add(symbol)
                        else:
                            symbol_overflow = True
        finally:
            text.close()
    except UnicodeDecodeError as exc:
        raise ExportProfileError("export must be UTF-8 encoded") from exc
    except csv.Error as exc:
        raise ExportProfileError(f"invalid CSV: {exc}") from exc
    stat = source.stat()
    manifest: dict[str, Any] = {
        "schema_version": LINEAGE_V2_SCHEMA_VERSION,
        "analysis": "csv_export_lineage_v2",
        "timestamp_precision": "exact_integer_utc_nanoseconds",
        "source_kind": "deepcharts_dxfeed_export",
        "file": {"name": source.name, "size_bytes": stat.st_size, "sha256": digest.hexdigest()},
        "csv": {
            "delimiter": delimiter, "columns": columns, "column_count": len(columns),
            "schema_sha256": hashlib.sha256(_canonical(columns)).hexdigest(),
            "row_count": row_count, "normalized_row_chain_sha256": row_chain,
        },
        "timestamps": {
            "column": chosen_timestamp, "parsed_count": timestamp_count,
            "parse_error_count": timestamp_parse_errors, "regression_count": timestamp_regressions,
            "first_ns": first_ns, "last_ns": last_ns, "minimum_ns": minimum_ns, "maximum_ns": maximum_ns,
            "first": _format_ns(first_ns) if first_ns is not None else None,
            "last": _format_ns(last_ns) if last_ns is not None else None,
            "minimum": _format_ns(minimum_ns) if minimum_ns is not None else None,
            "maximum": _format_ns(maximum_ns) if maximum_ns is not None else None,
        },
        "symbols": {"column": chosen_symbol, "samples": sorted(symbols), "sample_truncated": symbol_overflow},
        "limitations": [
            "The manifest proves identity and structural properties of supplied local bytes only.",
            "It does not prove provider authenticity, completeness, entitlement coverage, durable external retention, or executable fills.",
            "Exact timestamp ordering diagnostics do not establish exchange sequence ordering across event types.",
        ],
    }
    return {**manifest, "manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest()}


def verify_csv_export_v2(path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify v1 unchanged or v2 byte/row/exact-time diagnostics fail closed."""
    version = manifest.get("schema_version")
    if version == 1:
        return verify_csv_export(path, manifest)
    if version != LINEAGE_V2_SCHEMA_VERSION or manifest.get("analysis") != "csv_export_lineage_v2":
        raise ExportProfileError("unsupported export manifest schema")
    stored_hash = manifest.get("manifest_sha256")
    if not isinstance(stored_hash, str) or stored_hash != hashlib.sha256(_canonical(_unsigned_manifest(manifest))).hexdigest():
        return {"matches": False, "checks": {"manifest_sha256": False}, "current": None}
    csv_meta = manifest.get("csv")
    timestamps = manifest.get("timestamps")
    if not isinstance(csv_meta, dict) or not isinstance(timestamps, dict):
        raise ExportProfileError("v2 manifest is missing csv or timestamps metadata")
    current = profile_csv_export_v2(
        path,
        delimiter=csv_meta.get("delimiter", ","),
        timestamp_column=timestamps.get("column"),
        symbol_column=manifest.get("symbols", {}).get("column"),
    )
    checks = {
        "manifest_sha256": True,
        "sha256": current["file"] == manifest.get("file"),
        "schema_sha256": current["csv"]["schema_sha256"] == csv_meta.get("schema_sha256"),
        "row_count": current["csv"]["row_count"] == csv_meta.get("row_count"),
        "row_chain": current["csv"]["normalized_row_chain_sha256"] == csv_meta.get("normalized_row_chain_sha256"),
        "exact_timestamp_diagnostics": current["timestamps"] == timestamps,
        "manifest_recompute": current["manifest_sha256"] == stored_hash,
    }
    return {"matches": all(checks.values()), "checks": checks, "current": current}

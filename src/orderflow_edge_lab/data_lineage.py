from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Iterable


UTC = timezone.utc
_TIMESTAMP_NAMES = (
    "timestamp",
    "time",
    "datetime",
    "event_time",
    "eventtime",
    "trade_time",
    "tradetime",
)
_SYMBOL_NAMES = ("symbol", "instrument", "contract")


class ExportProfileError(ValueError):
    pass


class _HashingReader(io.RawIOBase):
    def __init__(self, raw: io.BufferedReader, digest: "hashlib._Hash") -> None:
        self.raw = raw
        self.digest = digest

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        count = self.raw.readinto(buffer)
        if count:
            self.digest.update(memoryview(buffer)[:count])
        return count

    def close(self) -> None:
        try:
            super().close()
        finally:
            self.raw.close()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _find_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    by_folded: dict[str, list[str]] = {}
    for column in columns:
        by_folded.setdefault(column.strip().casefold(), []).append(column)
    for candidate in candidates:
        matches = by_folded.get(candidate.casefold(), [])
        if len(matches) > 1:
            raise ExportProfileError(f"ambiguous column name for {candidate}")
        if matches:
            return matches[0]
    return None


def _parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("blank timestamp")
    try:
        number = float(text)
    except ValueError:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return parsed.astimezone(UTC)
    if not math.isfinite(number):
        raise ValueError("nonfinite timestamp")
    magnitude = abs(number)
    if magnitude >= 1e18:
        seconds = number / 1e9
    elif magnitude >= 1e15:
        seconds = number / 1e6
    elif magnitude >= 1e12:
        seconds = number / 1e3
    else:
        seconds = number
    return datetime.fromtimestamp(seconds, tz=UTC)


def profile_csv_export(
    path: str | Path,
    *,
    delimiter: str = ",",
    timestamp_column: str | None = None,
    symbol_column: str | None = None,
    max_symbol_samples: int = 32,
) -> dict[str, Any]:
    """Profile one exact CSV byte stream without modifying it.

    The SHA-256 is calculated over the same stream consumed by the CSV parser, so
    the manifest cannot accidentally describe a different read of a changing file.
    Timestamp diagnostics are descriptive only and do not establish export
    completeness or upstream dxFeed authenticity.
    """
    source = Path(path)
    if len(delimiter) != 1:
        raise ValueError("delimiter must be exactly one character")
    if type(max_symbol_samples) is not int or max_symbol_samples < 1:
        raise ValueError("max_symbol_samples must be a positive integer")

    digest = hashlib.sha256()
    row_chain = "GENESIS"
    row_count = 0
    timestamp_count = 0
    timestamp_parse_errors = 0
    timestamp_regressions = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    minimum_timestamp: datetime | None = None
    maximum_timestamp: datetime | None = None
    previous_timestamp: datetime | None = None
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

            chosen_timestamp = timestamp_column or _find_column(columns, _TIMESTAMP_NAMES)
            chosen_symbol = symbol_column or _find_column(columns, _SYMBOL_NAMES)
            if chosen_timestamp is not None and chosen_timestamp not in columns:
                raise ExportProfileError(f"timestamp column not found: {chosen_timestamp}")
            if chosen_symbol is not None and chosen_symbol not in columns:
                raise ExportProfileError(f"symbol column not found: {chosen_symbol}")
            timestamp_index = columns.index(chosen_timestamp) if chosen_timestamp else None
            symbol_index = columns.index(chosen_symbol) if chosen_symbol else None

            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(columns):
                    raise ExportProfileError(
                        f"row {line_number} has {len(row)} fields; expected {len(columns)}"
                    )
                row_count += 1
                row_payload = _canonical(row)
                row_chain = (
                    hashlib.sha256(bytes.fromhex(row_chain) + row_payload).hexdigest()
                    if row_chain != "GENESIS"
                    else hashlib.sha256(b"GENESIS" + row_payload).hexdigest()
                )

                if timestamp_index is not None:
                    raw_timestamp = row[timestamp_index]
                    try:
                        parsed = _parse_timestamp(raw_timestamp)
                    except (ValueError, OverflowError, OSError):
                        timestamp_parse_errors += 1
                    else:
                        timestamp_count += 1
                        if first_timestamp is None:
                            first_timestamp = parsed
                        last_timestamp = parsed
                        minimum_timestamp = parsed if minimum_timestamp is None else min(minimum_timestamp, parsed)
                        maximum_timestamp = parsed if maximum_timestamp is None else max(maximum_timestamp, parsed)
                        if previous_timestamp is not None and parsed < previous_timestamp:
                            timestamp_regressions += 1
                        previous_timestamp = parsed

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
    schema_sha256 = hashlib.sha256(_canonical(columns)).hexdigest()
    return {
        "schema_version": 1,
        "source_kind": "deepcharts_dxfeed_export",
        "file": {
            "name": source.name,
            "size_bytes": stat.st_size,
            "sha256": digest.hexdigest(),
        },
        "csv": {
            "delimiter": delimiter,
            "columns": columns,
            "column_count": len(columns),
            "schema_sha256": schema_sha256,
            "row_count": row_count,
            "normalized_row_chain_sha256": row_chain,
        },
        "timestamps": {
            "column": chosen_timestamp,
            "parsed_count": timestamp_count,
            "parse_error_count": timestamp_parse_errors,
            "regression_count": timestamp_regressions,
            "first": first_timestamp.isoformat() if first_timestamp else None,
            "last": last_timestamp.isoformat() if last_timestamp else None,
            "minimum": minimum_timestamp.isoformat() if minimum_timestamp else None,
            "maximum": maximum_timestamp.isoformat() if maximum_timestamp else None,
        },
        "symbols": {
            "column": chosen_symbol,
            "samples": sorted(symbols),
            "sample_truncated": symbol_overflow,
        },
        "limitations": [
            "The manifest proves identity and structural properties of the supplied local bytes only.",
            "It does not prove dxFeed or DeepCharts authenticity, completeness, entitlement coverage, or executable fills.",
            "Timestamp ordering diagnostics do not establish exchange sequence ordering when the export contains multiple event types.",
        ],
    }


def verify_csv_export(path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != 1:
        raise ExportProfileError("unsupported export manifest schema")
    csv_meta = manifest.get("csv")
    file_meta = manifest.get("file")
    if not isinstance(csv_meta, dict) or not isinstance(file_meta, dict):
        raise ExportProfileError("manifest is missing file or csv metadata")
    delimiter = csv_meta.get("delimiter", ",")
    timestamp_column = manifest.get("timestamps", {}).get("column")
    symbol_column = manifest.get("symbols", {}).get("column")
    current = profile_csv_export(
        path,
        delimiter=delimiter,
        timestamp_column=timestamp_column,
        symbol_column=symbol_column,
    )
    checks = {
        "sha256": current["file"]["sha256"] == file_meta.get("sha256"),
        "size_bytes": current["file"]["size_bytes"] == file_meta.get("size_bytes"),
        "schema_sha256": current["csv"]["schema_sha256"] == csv_meta.get("schema_sha256"),
        "row_count": current["csv"]["row_count"] == csv_meta.get("row_count"),
        "row_chain": current["csv"]["normalized_row_chain_sha256"] == csv_meta.get("normalized_row_chain_sha256"),
    }
    return {"matches": all(checks.values()), "checks": checks, "current": current}

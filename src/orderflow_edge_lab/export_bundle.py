from __future__ import annotations

from dataclasses import dataclass, asdict
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .data import parse_timestamp_ns


_TS_KEYS = ("timestamp", "time", "datetime", "ts", "event_time", "eventtime")
_SYMBOL_KEYS = ("symbol", "instrument", "ticker", "event_symbol", "eventsymbol")
_SEQUENCE_KEYS = ("sequence", "seq", "event_sequence", "eventsequence")


def _lowered(row: Mapping[str, object]) -> dict[str, object]:
    return {str(k).strip().lower(): v for k, v in row.items()}


def _first(row: Mapping[str, object], keys: Sequence[str]) -> object | None:
    lowered = _lowered(row)
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def _canonical_row(row: Mapping[str, object]) -> str:
    normalized = {str(k).strip(): "" if v is None else str(v).strip() for k, v in row.items()}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sequence(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("sequence must be an integer")
    result = int(value)
    if result < 0:
        raise ValueError("sequence must be nonnegative")
    return result


@dataclass(frozen=True)
class BundleSource:
    path: str
    sha256: str
    rows: int


@dataclass(frozen=True)
class BundleStats:
    input_files: int
    input_rows: int
    output_rows: int
    exact_duplicates_removed: int
    sequence_conflicts: int
    first_ts_ns: int
    last_ts_ns: int


@dataclass(frozen=True)
class BundleResult:
    sources: tuple[BundleSource, ...]
    stats: BundleStats
    output_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "sources": [asdict(source) for source in self.sources],
            "stats": asdict(self.stats),
            "output_sha256": self.output_sha256,
            "research_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        }


def build_export_bundle(
    inputs: Iterable[str | Path],
    output_path: str | Path,
    *,
    default_symbol: str | None = None,
) -> BundleResult:
    """Merge overlapping DeepCharts/dxFeed CSV exports deterministically.

    Exact duplicate rows are collapsed. When a timestamp, symbol and sequence
    identity is present in two rows, different row contents are rejected instead
    of silently choosing one. Rows without sequence values are not collapsed by
    timestamp because multiple valid updates may share a timestamp.
    """
    paths = tuple(Path(p) for p in inputs)
    if not paths:
        raise ValueError("at least one input CSV is required")
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError("duplicate input paths are not allowed")

    sources: list[BundleSource] = []
    records: list[tuple[int, int | None, int, int, dict[str, str], str, str]] = []
    fieldnames: list[str] = []
    exact_seen: set[str] = set()
    identity_seen: dict[tuple[str, int, int], str] = {}
    duplicates = conflicts = input_rows = 0

    for file_index, path in enumerate(paths):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        for name in reader.fieldnames:
            if name not in fieldnames:
                fieldnames.append(name)
        rows_in_file = 0
        for row_index, row in enumerate(reader, start=2):
            rows_in_file += 1
            input_rows += 1
            canonical = _canonical_row(row)
            if canonical in exact_seen:
                duplicates += 1
                continue
            ts_ns = parse_timestamp_ns(_first(row, _TS_KEYS))
            symbol_value = _first(row, _SYMBOL_KEYS)
            symbol = str(symbol_value or default_symbol or "").strip()
            if not symbol:
                raise ValueError(f"missing symbol in {path} row {row_index}")
            seq = _sequence(_first(row, _SEQUENCE_KEYS))
            if seq is not None:
                identity = (symbol, ts_ns, seq)
                prior = identity_seen.get(identity)
                if prior is not None and prior != canonical:
                    conflicts += 1
                    raise ValueError(
                        f"conflicting rows for symbol={symbol} ts_ns={ts_ns} sequence={seq}"
                    )
                identity_seen[identity] = canonical
            exact_seen.add(canonical)
            normalized = {str(k): "" if v is None else str(v) for k, v in row.items()}
            records.append((ts_ns, seq, file_index, row_index, normalized, symbol, canonical))
        sources.append(BundleSource(path=str(path), sha256=digest, rows=rows_in_file))

    if not records:
        raise ValueError("input CSVs contain no data rows")
    records.sort(key=lambda item: (item[0], -1 if item[1] is None else item[1], item[2], item[3]))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for _ts, _seq, _fi, _ri, row, _symbol, _canonical in records:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    encoded = buffer.getvalue().encode("utf-8")
    output.write_bytes(encoded)

    result = BundleResult(
        sources=tuple(sources),
        stats=BundleStats(
            input_files=len(paths),
            input_rows=input_rows,
            output_rows=len(records),
            exact_duplicates_removed=duplicates,
            sequence_conflicts=conflicts,
            first_ts_ns=records[0][0],
            last_ts_ns=records[-1][0],
        ),
        output_sha256=hashlib.sha256(encoded).hexdigest(),
    )
    manifest = output.with_name(output.name + ".manifest.json")
    with manifest.open("x", encoding="utf-8", newline="\n") as fh:
        json.dump(result.as_dict(), fh, sort_keys=True, separators=(",", ":"), allow_nan=False)
        fh.write("\n")
    return result

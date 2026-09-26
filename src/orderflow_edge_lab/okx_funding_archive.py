from __future__ import annotations

from hashlib import sha256
from io import BytesIO, TextIOWrapper
import csv
import math
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping
import zipfile

import pandas as pd

from orderflow_edge_lab.okx_funding_archive_schema import (
    ArchiveLimits,
    OkxFundingArchiveSchemaError,
    _download,
)


class OkxFundingArchiveError(ValueError):
    pass


EXPECTED_HEADER = ["instrument_name", "funding_rate", "funding_time"]


def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        name
        and not path.is_absolute()
        and ".." not in path.parts
        and not name.endswith("/")
    )


def parse_okx_funding_archive_bytes(
    payload: bytes,
    *,
    expected_archive_filename: str,
    target_instruments: Iterable[str],
    start: str,
    end: str,
    limits: ArchiveLimits | None = None,
) -> dict[str, Any]:
    limits = limits or ArchiveLimits()
    if not payload:
        raise OkxFundingArchiveError("archive payload is empty")
    if len(payload) > int(limits.max_download_bytes):
        raise OkxFundingArchiveError("archive exceeds frozen download limit")

    start_ts = _utc(start)
    end_ts = _utc(end)
    if end_ts <= start_ts:
        raise OkxFundingArchiveError("end must be after start")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    targets = {str(value) for value in target_instruments}
    if not targets:
        raise OkxFundingArchiveError("target instrument set is empty")

    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise OkxFundingArchiveError("download is not a valid ZIP") from exc

    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos:
        raise OkxFundingArchiveError("ZIP contains no files")
    if len(infos) > int(limits.max_members):
        raise OkxFundingArchiveError(
            f"ZIP member count exceeds limit: {len(infos)}"
        )
    total_uncompressed = sum(int(info.file_size) for info in infos)
    if total_uncompressed > int(limits.max_uncompressed_bytes):
        raise OkxFundingArchiveError(
            f"ZIP uncompressed size exceeds limit: {total_uncompressed}"
        )

    records: dict[tuple[str, int], float] = {}
    total_data_rows = 0
    csv_members = 0
    for info in infos:
        if not _safe_member(info.filename):
            raise OkxFundingArchiveError(
                f"unsafe ZIP member path: {info.filename}"
            )
        if info.flag_bits & 0x1:
            raise OkxFundingArchiveError(
                f"encrypted archive member is not permitted: {info.filename}"
            )
        if not info.filename.lower().endswith(".csv"):
            continue
        csv_members += 1
        with archive.open(info, "r") as raw:
            with TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
                reader = csv.reader(text)
                try:
                    header = next(reader)
                except StopIteration as exc:
                    raise OkxFundingArchiveError(
                        f"empty CSV member: {info.filename}"
                    ) from exc
                if header != EXPECTED_HEADER:
                    raise OkxFundingArchiveError(
                        f"unexpected funding CSV header in {info.filename}: {header}"
                    )
                for line_number, row in enumerate(reader, start=2):
                    total_data_rows += 1
                    if len(row) != 3:
                        raise OkxFundingArchiveError(
                            f"{info.filename}:{line_number}: expected 3 columns"
                        )
                    instrument, raw_rate, raw_time = row
                    instrument = instrument.strip()
                    if not instrument:
                        raise OkxFundingArchiveError(
                            f"{info.filename}:{line_number}: empty instrument"
                        )
                    try:
                        rate = float(raw_rate)
                        funding_time = int(raw_time)
                    except (TypeError, ValueError) as exc:
                        raise OkxFundingArchiveError(
                            f"{info.filename}:{line_number}: invalid rate/time"
                        ) from exc
                    if not math.isfinite(rate):
                        raise OkxFundingArchiveError(
                            f"{info.filename}:{line_number}: non-finite funding rate"
                        )
                    if funding_time <= 0:
                        raise OkxFundingArchiveError(
                            f"{info.filename}:{line_number}: invalid funding time"
                        )
                    if instrument not in targets:
                        continue
                    if not (start_ms <= funding_time < end_ms):
                        continue
                    key = (instrument, funding_time)
                    previous = records.get(key)
                    if previous is not None and previous != rate:
                        raise OkxFundingArchiveError(
                            f"conflicting funding duplicate for {instrument} at {funding_time}"
                        )
                    records[key] = rate

    if csv_members == 0:
        raise OkxFundingArchiveError("ZIP contains no CSV members")

    parsed = [
        {
            "instrument_name": instrument,
            "funding_time": funding_time,
            "funding_rate": records[(instrument, funding_time)],
        }
        for instrument, funding_time in sorted(records)
    ]
    return {
        "schema_version": 1,
        "analysis": "okx_funding_archive_parse_v1",
        "expected_archive_filename": expected_archive_filename,
        "archive_sha256": sha256(payload).hexdigest(),
        "download_bytes": len(payload),
        "zip_member_count": len(infos),
        "csv_member_count": csv_members,
        "total_uncompressed_bytes": total_uncompressed,
        "total_data_rows": total_data_rows,
        "target_record_count": len(parsed),
        "records": parsed,
    }


def fetch_and_parse_okx_funding_archive(
    *,
    url: str,
    expected_archive_filename: str,
    target_instruments: Iterable[str],
    start: str,
    end: str,
    limits: ArchiveLimits | None = None,
) -> dict[str, Any]:
    limits = limits or ArchiveLimits()
    try:
        payload = _download(
            url,
            max_bytes=int(limits.max_download_bytes),
        )
    except OkxFundingArchiveSchemaError as exc:
        raise OkxFundingArchiveError(str(exc)) from exc
    result = parse_okx_funding_archive_bytes(
        payload,
        expected_archive_filename=expected_archive_filename,
        target_instruments=target_instruments,
        start=start,
        end=end,
        limits=limits,
    )
    result["source_url"] = url
    return result


def merge_okx_funding_archive_records(
    archive_reports: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int], float] = {}
    for report in archive_reports:
        for row in report.get("records") or []:
            instrument = str(row["instrument_name"])
            funding_time = int(row["funding_time"])
            rate = float(row["funding_rate"])
            key = (instrument, funding_time)
            previous = merged.get(key)
            if previous is not None and previous != rate:
                raise OkxFundingArchiveError(
                    f"conflicting cross-archive duplicate for {instrument} at {funding_time}"
                )
            merged[key] = rate
    return [
        {
            "instrument_name": instrument,
            "funding_time": funding_time,
            "funding_rate": merged[(instrument, funding_time)],
        }
        for instrument, funding_time in sorted(merged)
    ]


def records_to_funding_frames(
    records: Iterable[Mapping[str, Any]],
    symbol_to_instrument: Mapping[str, str],
) -> dict[str, pd.DataFrame]:
    instrument_to_symbol = {
        str(instrument): str(symbol)
        for symbol, instrument in symbol_to_instrument.items()
    }
    if len(instrument_to_symbol) != len(symbol_to_instrument):
        raise OkxFundingArchiveError("instrument mapping must be one-to-one")

    rows: dict[str, list[dict[str, Any]]] = {
        str(symbol): [] for symbol in symbol_to_instrument
    }
    for row in records:
        instrument = str(row["instrument_name"])
        symbol = instrument_to_symbol.get(instrument)
        if symbol is None:
            continue
        rows[symbol].append(
            {
                "timestamp": pd.to_datetime(
                    int(row["funding_time"]),
                    unit="ms",
                    utc=True,
                ),
                "funding_rate": float(row["funding_rate"]),
            }
        )

    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbol_to_instrument:
        data = rows[str(symbol)]
        if data:
            frame = pd.DataFrame(data).set_index("timestamp").sort_index()
            if frame.index.has_duplicates:
                raise OkxFundingArchiveError(
                    f"{symbol}: duplicate funding timestamps after merge"
                )
            frames[str(symbol)] = frame
        else:
            frames[str(symbol)] = pd.DataFrame(
                columns=["funding_rate"],
                index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
            )
    return frames

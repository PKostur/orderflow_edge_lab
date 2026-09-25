from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
import csv
import json
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.request import Request, urlopen
import zipfile


class OkxFundingArchiveSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveLimits:
    max_download_bytes: int = 50_000_000
    max_uncompressed_bytes: int = 100_000_000
    max_members: int = 20
    max_sample_rows: int = 3


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        name
        and not path.is_absolute()
        and ".." not in path.parts
        and not name.endswith("/")
    )


def _download(url: str, *, max_bytes: int, timeout: float = 30.0) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/zip,application/octet-stream,*/*",
            "User-Agent": "orderflow-edge-lab/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise OkxFundingArchiveSchemaError(
                f"archive download returned HTTP {response.status}"
            )
        raw_length = response.headers.get("Content-Length")
        if raw_length not in (None, ""):
            try:
                content_length = int(raw_length)
            except ValueError as exc:
                raise OkxFundingArchiveSchemaError(
                    "invalid archive Content-Length"
                ) from exc
            if content_length > max_bytes:
                raise OkxFundingArchiveSchemaError(
                    f"archive exceeds download limit: {content_length}"
                )
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise OkxFundingArchiveSchemaError(
            f"archive exceeds download limit: >{max_bytes}"
        )
    if not payload:
        raise OkxFundingArchiveSchemaError("archive download was empty")
    return payload


def _inspect_csv_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_sample_rows: int,
) -> dict[str, Any]:
    if info.flag_bits & 0x1:
        raise OkxFundingArchiveSchemaError(
            f"encrypted archive member is not permitted: {info.filename}"
        )
    with archive.open(info, "r") as raw:
        with TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            reader = csv.reader(text)
            try:
                header = next(reader)
            except StopIteration:
                header = []
            rows = 0
            sample_rows: list[list[str]] = []
            column_counts: set[int] = set()
            for row in reader:
                rows += 1
                column_counts.add(len(row))
                if len(sample_rows) < max_sample_rows:
                    sample_rows.append(list(row))
    return {
        "member": info.filename,
        "compressed_bytes": int(info.compress_size),
        "uncompressed_bytes": int(info.file_size),
        "header": header,
        "header_column_count": len(header),
        "data_row_count": rows,
        "observed_data_column_counts": sorted(column_counts),
        "sample_rows": sample_rows,
    }


def inspect_okx_funding_archive(
    url: str,
    *,
    expected_filename: str,
    limits: ArchiveLimits | None = None,
) -> dict[str, Any]:
    limits = limits or ArchiveLimits()
    payload = _download(
        url,
        max_bytes=int(limits.max_download_bytes),
    )
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise OkxFundingArchiveSchemaError("download is not a valid ZIP") from exc

    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos:
        raise OkxFundingArchiveSchemaError("ZIP contains no files")
    if len(infos) > int(limits.max_members):
        raise OkxFundingArchiveSchemaError(
            f"ZIP member count exceeds limit: {len(infos)}"
        )
    total_uncompressed = sum(int(info.file_size) for info in infos)
    if total_uncompressed > int(limits.max_uncompressed_bytes):
        raise OkxFundingArchiveSchemaError(
            f"ZIP uncompressed size exceeds limit: {total_uncompressed}"
        )
    for info in infos:
        if not _safe_member(info.filename):
            raise OkxFundingArchiveSchemaError(
                f"unsafe ZIP member path: {info.filename}"
            )

    csv_infos = [
        info for info in infos if info.filename.lower().endswith(".csv")
    ]
    if not csv_infos:
        raise OkxFundingArchiveSchemaError("ZIP contains no CSV members")

    csv_reports = [
        _inspect_csv_member(
            archive,
            info,
            max_sample_rows=int(limits.max_sample_rows),
        )
        for info in csv_infos
    ]
    return {
        "schema_version": 1,
        "analysis": "okx_funding_archive_schema_file_v1",
        "expected_archive_filename": expected_filename,
        "source_url": url,
        "download_bytes": len(payload),
        "zip_member_count": len(infos),
        "csv_member_count": len(csv_infos),
        "total_uncompressed_bytes": total_uncompressed,
        "members": [info.filename for info in infos],
        "csv_reports": csv_reports,
    }


def build_okx_funding_archive_schema_probe(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    samples = config.get("samples")
    if not isinstance(samples, list) or not samples:
        raise OkxFundingArchiveSchemaError("schema probe requires samples")
    limits_raw = config.get("limits") or {}
    limits = ArchiveLimits(
        max_download_bytes=int(
            limits_raw.get("max_download_bytes", ArchiveLimits.max_download_bytes)
        ),
        max_uncompressed_bytes=int(
            limits_raw.get(
                "max_uncompressed_bytes",
                ArchiveLimits.max_uncompressed_bytes,
            )
        ),
        max_members=int(limits_raw.get("max_members", ArchiveLimits.max_members)),
        max_sample_rows=int(
            limits_raw.get("max_sample_rows", ArchiveLimits.max_sample_rows)
        ),
    )

    reports: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise OkxFundingArchiveSchemaError("sample entries must be objects")
        expected = str(sample["filename"])
        url = str(sample["url"])
        report = inspect_okx_funding_archive(
            url,
            expected_filename=expected,
            limits=limits,
        )
        report["sample_id"] = str(sample["sample_id"])
        report["archive_kind"] = str(sample["archive_kind"])
        reports.append(report)

    headers = sorted(
        {
            tuple(csv_report["header"])
            for report in reports
            for csv_report in report["csv_reports"]
        }
    )
    return {
        "schema_version": 1,
        "analysis": "okx_funding_archive_schema_probe_v1",
        "probe_id": str(config["probe_id"]),
        "evidence_use": "engineering_schema_discovery_only",
        "sample_count": len(reports),
        "samples": reports,
        "distinct_csv_headers": [list(header) for header in headers],
        "claims": {
            "candidate_pnl_computed": False,
            "candidate_retested": False,
            "historical_result_repaired": False,
            "strategy_definition_changed": False,
            "candidate_promoted": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }

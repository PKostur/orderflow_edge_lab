"""MEXC capture health: descriptive inventory of recorded order-flow captures.

This is a **reporting layer only**. It inventories raw/feature capture files and
their manifests under a data directory, reports coverage ages, and flags gaps
(missing manifests, interrupted ``.partial`` files, stale captures). It never
reinterprets research results, never counts prospective evidence batches, and
never certifies data quality beyond what the files themselves show.

Counting of prospective evidence batches remains the exclusive responsibility of
the frozen discovery-aggregation pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path("data/mexc_orderflow")

_FILENAME_RE = re.compile(
    r"^(?P<ts>\d{8}T\d{6}Z)_mexc_(?P<kind>raw|features)\.jsonl(?:\.(?P<suffix>manifest\.json|partial))?$"
)

MANIFEST_SUFFIX = ".manifest.json"
PARTIAL_SUFFIX = ".partial"


class CaptureHealthError(ValueError):
    """Raised when the capture inventory cannot be built."""


def _parse_file_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise CaptureHealthError(f"invalid capture timestamp {value!r}") from exc


def peek_symbols(path: Path, max_lines: int = 5) -> list[str]:
    """Best-effort distinct-symbol peek from the first JSONL records of a file."""

    symbols: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for count, line in enumerate(handle):
                if count >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                symbol = record.get("symbol") if isinstance(record, dict) else None
                if isinstance(symbol, str) and symbol and symbol not in symbols:
                    symbols.append(symbol)
    except OSError:
        return []
    return symbols


def scan_capture_directory(data_dir: Path | str = DEFAULT_DATA_DIR) -> dict[str, Any]:
    """Inventory capture files. Missing directories are reported, not fatal."""

    directory = Path(data_dir)
    if not directory.is_dir():
        return {
            "data_dir": str(directory),
            "exists": False,
            "captures": [],
            "orphans": [],
        }
    content_files: list[dict[str, Any]] = []
    manifests_seen: set[tuple[str, str]] = set()
    orphans: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        match = _FILENAME_RE.match(path.name)
        if match is None:
            orphans.append(path.name)
            continue
        kind = match.group("kind")
        suffix = match.group("suffix")
        group_key = match.group("ts")  # one capture session per start timestamp
        if suffix == "manifest.json":
            manifests_seen.add((group_key, kind))
            continue
        content_files.append(
            {
                "group_key": group_key,
                "kind": kind,
                "is_partial": suffix == "partial",
                "file_name": path.name,
                "started_utc": match.group("ts"),
                "size_bytes": path.stat().st_size,
            }
        )
    # Group by capture base name so raw/features states line up.
    grouped: dict[str, dict[str, Any]] = {}
    for item in content_files:
        entry = grouped.setdefault(
            item["group_key"],
            {
                "group_key": item["group_key"],
                "started_utc": item["started_utc"],
                "raw": None,
                "features": None,
                "raw.partial": None,
                "features.partial": None,
            },
        )
        slot = f"{item['kind']}.partial" if item["is_partial"] else item["kind"]
        entry[slot] = {
            "file_name": item["file_name"],
            "size_bytes": item["size_bytes"],
        }
    for entry in grouped.values():
        for kind in ("raw", "features"):
            present = entry.get(kind)
            if not present:
                continue
            entry[f"{kind}_manifest_present"] = (entry["group_key"], kind) in manifests_seen
        raw_present = entry.get("raw")
        if raw_present:
            entry["symbols_observed"] = peek_symbols(directory / raw_present["file_name"])
    return {
        "data_dir": str(directory),
        "exists": True,
        "captures": [grouped[key] for key in sorted(grouped)],
        "orphans": orphans,
    }


def build_health_summary(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    now: datetime | None = None,
    stale_after_hours: float = 26.0,
) -> dict[str, Any]:
    """Build a descriptive, deterministic health report (no verdicts)."""

    inventory = scan_capture_directory(data_dir)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    findings: list[dict[str, Any]] = []

    for name in inventory["orphans"]:
        findings.append({"severity": "info", "code": "unrecognized_file", "detail": name})

    newest_start: datetime | None = None
    complete_captures = 0
    interrupted = 0
    missing_manifests = 0
    symbols: set[str] = set()

    for entry in inventory["captures"]:
        try:
            started = _parse_file_timestamp(entry["started_utc"])
        except CaptureHealthError:
            findings.append(
                {
                    "severity": "error",
                    "code": "unparsable_capture_timestamp",
                    "detail": entry["group_key"],
                }
            )
            continue
        newest_start = started if newest_start is None else max(newest_start, started)
        raw = entry.get("raw")
        features = entry.get("features")
        is_partial = bool(entry.get("raw.partial") or entry.get("features.partial"))
        if is_partial:
            interrupted += 1
            findings.append(
                {
                    "severity": "warning",
                    "code": "interrupted_capture",
                    "detail": entry["group_key"],
                }
            )
        elif raw and features:
            complete_captures += 1
        for slot in ("raw", "features"):
            present = entry.get(slot)
            if present and not entry.get(f"{slot}_manifest_present", False):
                missing_manifests += 1
                findings.append(
                    {
                        "severity": "warning",
                        "code": f"{slot}_manifest_missing",
                        "detail": entry["group_key"],
                    }
                )
        symbols.update(entry.get("symbols_observed", []))

    stale = False
    newest_iso = None
    hours_since_newest = None
    if newest_start is not None:
        hours_since_newest = round((moment - newest_start).total_seconds() / 3600.0, 3)
        newest_iso = newest_start.isoformat().replace("+00:00", "Z")
        stale = hours_since_newest > float(stale_after_hours)
        if stale:
            findings.append(
                {
                    "severity": "warning",
                    "code": "no_recent_capture",
                    "detail": f"newest capture is {hours_since_newest}h old (threshold {stale_after_hours}h)",
                }
            )
    elif inventory["exists"]:
        findings.append(
            {"severity": "warning", "code": "no_captures_found", "detail": inventory["data_dir"]}
        )

    # Stoppage assessment: the one signal that must not stay quiet during a
    # prospective window. A silent capture stop delays every open watch while
    # looking healthy in aggregate, so it is reported as its own block and as a
    # dedicated finding with a severity that escalates past 2x the threshold.
    stoppage: dict[str, Any] = {"capture_stopped": False, "severity": None, "reason": None}
    if not inventory["exists"]:
        stoppage = {
            "capture_stopped": True,
            "severity": "warning",
            "reason": f"no capture directory at {inventory['data_dir']}",
        }
    elif not inventory["captures"]:
        stoppage = {
            "capture_stopped": True,
            "severity": "error",
            "reason": "capture directory exists but holds no recognised captures",
        }
    elif stale and hours_since_newest is not None:
        severity = "error" if hours_since_newest > 2.0 * float(stale_after_hours) else "warning"
        stoppage = {
            "capture_stopped": True,
            "severity": severity,
            "reason": f"newest capture is {hours_since_newest}h old (threshold {stale_after_hours}h)",
        }
    if stoppage["capture_stopped"]:
        findings.append(
            {"severity": stoppage["severity"], "code": "capture_stopped", "detail": stoppage["reason"]}
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": "mexc-capture-health",
        "status": "reporting_only",
        "generated_at_utc": moment.isoformat().replace("+00:00", "Z"),
        "data_dir": inventory["data_dir"],
        "data_dir_exists": inventory["exists"],
        "stale_after_hours": stale_after_hours,
        "capture_counts": {
            "complete": complete_captures,
            "interrupted": interrupted,
            "missing_manifests": missing_manifests,
            "total_groups": len(inventory["captures"]),
        },
        "symbols_observed": sorted(symbols),
        "newest_capture_started_utc": newest_iso,
        "hours_since_newest_capture": hours_since_newest,
        "stale": stale,
        "stoppage": stoppage,
        "findings": findings,
        "claims": {
            "counts_prospective_batches": False,
            "reinterprets_research_results": False,
            "certifies_data_quality": False,
            "live_order_transmission_supported": False,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload

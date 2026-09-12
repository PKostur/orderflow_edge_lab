from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .candidate_freeze import reverify_candidate_freeze, verify_candidate_freeze

UTC = timezone.utc


class HoldoutAuditError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HoldoutAuditError(f"{field} must be a timezone-aware timestamp")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HoldoutAuditError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HoldoutAuditError(f"{field} must include timezone")
    return parsed.astimezone(UTC)


def _load_object(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise HoldoutAuditError(f"cannot read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise HoldoutAuditError(f"JSON must be an object: {path}")
    return raw, payload


def _candidate_entry(manifest: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    rows = manifest.get("candidates")
    if not isinstance(rows, list):
        raise HoldoutAuditError("candidate freeze has no candidate list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("candidate_id") == candidate_id]
    if len(matches) != 1:
        raise HoldoutAuditError("candidate_id must identify exactly one frozen candidate")
    return matches[0]


def build_holdout_audit(
    observations_path: str | Path,
    candidate_freeze_path: str | Path,
    candidate_id: str,
    *,
    source_files: Iterable[str | Path] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    observations_path = Path(observations_path)
    candidate_freeze_path = Path(candidate_freeze_path)
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise HoldoutAuditError("candidate_id must be a nonempty string")
    candidate_id = candidate_id.strip()

    _, freeze = _load_object(candidate_freeze_path)
    if not verify_candidate_freeze(freeze):
        raise HoldoutAuditError("candidate freeze manifest is invalid")
    ok, reasons = reverify_candidate_freeze(freeze)
    if not ok:
        raise HoldoutAuditError("candidate freeze cannot be reverified: " + ",".join(reasons))
    frozen = _candidate_entry(freeze, candidate_id)

    research = freeze.get("research_freeze")
    if not isinstance(research, dict):
        raise HoldoutAuditError("candidate freeze lacks research freeze metadata")
    holdout_start = _parse_utc(research.get("holdout_start_exclusive"), "holdout_start_exclusive")
    holdout_end = _parse_utc(research.get("holdout_end"), "holdout_end")
    if holdout_end <= holdout_start:
        raise HoldoutAuditError("holdout boundaries are invalid")

    try:
        observation_bytes = observations_path.read_bytes()
        lines = observation_bytes.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise HoldoutAuditError("cannot read observations JSONL") from exc

    total_rows = 0
    candidate_rows = 0
    earliest_event: datetime | None = None
    latest_event: datetime | None = None
    latest_outcome: datetime | None = None
    dataset_hashes: set[str] = set()
    seen_ids: set[str] = set()

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        total_rows += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HoldoutAuditError(f"invalid observations JSONL at line {line_number}") from exc
        if not isinstance(row, dict):
            raise HoldoutAuditError(f"observation at line {line_number} is not an object")
        if row.get("candidate_id") != candidate_id:
            continue
        candidate_rows += 1
        observation_id = row.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise HoldoutAuditError("holdout observation is missing observation_id")
        if observation_id in seen_ids:
            raise HoldoutAuditError("duplicate holdout observation_id")
        seen_ids.add(observation_id)

        event_time = _parse_utc(row.get("event_time"), "event_time")
        outcome_time = _parse_utc(row.get("outcome_time"), "outcome_time")
        if not holdout_start < event_time <= holdout_end:
            raise HoldoutAuditError("holdout event lies outside frozen holdout interval")
        if outcome_time <= event_time:
            raise HoldoutAuditError("holdout outcome must occur after event")
        if outcome_time > holdout_end:
            raise HoldoutAuditError("holdout outcome matures after frozen holdout end")

        provenance = row.get("source_provenance")
        digest = provenance.get("dataset_sha256") if isinstance(provenance, dict) else None
        if not _valid_sha256(digest):
            raise HoldoutAuditError("holdout observation lacks valid dataset_sha256")
        dataset_hashes.add(str(digest).lower())
        earliest_event = event_time if earliest_event is None else min(earliest_event, event_time)
        latest_event = event_time if latest_event is None else max(latest_event, event_time)
        latest_outcome = outcome_time if latest_outcome is None else max(latest_outcome, outcome_time)

    if candidate_rows == 0:
        raise HoldoutAuditError("no observations found for frozen candidate")

    source_evidence: list[dict[str, str]] = []
    supplied_hashes: set[str] | None = None
    if source_files is not None:
        supplied_hashes = set()
        seen_paths: set[Path] = set()
        for raw_path in source_files:
            path = Path(raw_path).expanduser().resolve()
            if path in seen_paths:
                raise HoldoutAuditError("duplicate source file path")
            seen_paths.add(path)
            if not path.is_file():
                raise HoldoutAuditError(f"source file is not readable: {path}")
            digest = _sha256_file(path)
            supplied_hashes.add(digest)
            source_evidence.append({"path": str(path), "sha256": digest})
        if not supplied_hashes:
            raise HoldoutAuditError("source_files cannot be empty")
        missing = sorted(dataset_hashes - supplied_hashes)
        if missing:
            raise HoldoutAuditError("observation dataset hashes do not match supplied source files")

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise HoldoutAuditError("audit timestamp must include timezone")
    timestamp = timestamp.astimezone(UTC)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": timestamp.isoformat(),
        "candidate_id": candidate_id,
        "candidate_spec_sha256": frozen.get("spec_sha256"),
        "candidate_freeze": {
            "path": str(candidate_freeze_path),
            "manifest_sha256": freeze.get("manifest_sha256"),
            "registry_sha256": freeze.get("registry", {}).get("sha256") if isinstance(freeze.get("registry"), dict) else None,
        },
        "partition": {
            "holdout_start_exclusive": holdout_start.isoformat(),
            "holdout_end": holdout_end.isoformat(),
        },
        "observations": {
            "path": str(observations_path),
            "sha256": hashlib.sha256(observation_bytes).hexdigest(),
            "total_rows": total_rows,
            "candidate_rows": candidate_rows,
            "earliest_event": earliest_event.isoformat() if earliest_event else None,
            "latest_event": latest_event.isoformat() if latest_event else None,
            "latest_outcome": latest_outcome.isoformat() if latest_outcome else None,
            "dataset_sha256": sorted(dataset_hashes),
        },
        "source_reverification": {
            "performed": supplied_hashes is not None,
            "files": source_evidence,
        },
        "claims": {
            "candidate_specification_frozen": True,
            "holdout_partition_respected": True,
            "source_bytes_reverified": supplied_hashes is not None,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def verify_holdout_audit(manifest: dict[str, Any]) -> bool:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return False
    expected = manifest.get("manifest_sha256")
    if not _valid_sha256(expected):
        return False
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if _canonical_sha256(unsigned) != expected:
        return False
    if not _valid_sha256(manifest.get("candidate_spec_sha256")):
        return False
    candidate_freeze = manifest.get("candidate_freeze")
    observations = manifest.get("observations")
    claims = manifest.get("claims")
    if not isinstance(candidate_freeze, dict) or not _valid_sha256(candidate_freeze.get("manifest_sha256")) or not _valid_sha256(candidate_freeze.get("registry_sha256")):
        return False
    if not isinstance(observations, dict) or not _valid_sha256(observations.get("sha256")):
        return False
    if not isinstance(claims, dict):
        return False
    required_true = ("candidate_specification_frozen", "holdout_partition_respected")
    if any(claims.get(key) is not True for key in required_true):
        return False
    required_false = ("verified_out_of_sample_evidence", "profitable_edge_established", "live_order_transmission_supported")
    if any(claims.get(key) is not False for key in required_false):
        return False
    return True

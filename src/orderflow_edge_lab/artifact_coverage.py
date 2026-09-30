"""Artifact retention and coverage audit for prospective evidence windows.

This is a **reporting layer only**. It compares a frozen list of retention
requirements (what must still be retrievable through which date) against an
observed inventory of CI artifacts and, optionally, local canonical files.

It never publishes, edits, extends, or deletes an artifact, never counts
prospective evidence, and never computes a strategy verdict. The question it
answers is operational: *if the frozen counting pipeline ran today, would every
input it needs still exist?*

Counting of prospective evidence batches remains the exclusive responsibility of
the frozen discovery-aggregation pipeline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_REQUIREMENTS = Path("config/evidence_retention_requirements_v1.json")

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


class ArtifactCoverageError(ValueError):
    """Raised when the requirements config or inventory cannot be read."""


def parse_utc(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ArtifactCoverageError(f"{context}: expected an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactCoverageError(f"{context}: invalid UTC timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ArtifactCoverageError(f"{context}: timestamp must carry a UTC offset")
    return parsed.astimezone(timezone.utc)


def load_requirements(path: Path | str = DEFAULT_REQUIREMENTS) -> dict[str, Any]:
    """Load and structurally validate the frozen retention requirements."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactCoverageError(f"requirements config is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactCoverageError("requirements config must be a JSON object")
    requirements = payload.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ArtifactCoverageError("requirements config: 'requirements' must be a non-empty list")
    seen_ids: set[str] = set()
    for index, entry in enumerate(requirements):
        context = f"requirements[{index}]"
        if not isinstance(entry, dict):
            raise ArtifactCoverageError(f"{context}: must be an object")
        for key in ("requirement_id", "artifact_name", "must_remain_retrievable_through_utc"):
            if not entry.get(key):
                raise ArtifactCoverageError(f"{context}: missing key {key!r}")
        requirement_id = str(entry["requirement_id"])
        if requirement_id in seen_ids:
            raise ArtifactCoverageError(f"{context}: duplicate requirement_id {requirement_id!r}")
        seen_ids.add(requirement_id)
        parse_utc(
            entry["must_remain_retrievable_through_utc"],
            f"{context}.must_remain_retrievable_through_utc",
        )
    return payload


def load_inventory(source: Path | str) -> list[dict[str, Any]]:
    """Load an artifact inventory.

    Accepts either a raw ``gh api .../actions/artifacts`` payload (an object with
    an ``artifacts`` list), a bare JSON list, or JSON-lines of artifact objects.
    """

    path = Path(source)
    if not path.is_file():
        raise ArtifactCoverageError(f"inventory file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        entries: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ArtifactCoverageError(
                    f"inventory line {line_number} is not valid JSON: {exc}"
                ) from exc
            if not isinstance(item, dict):
                raise ArtifactCoverageError(f"inventory line {line_number} must be an object")
            entries.append(item)
        return entries
    if isinstance(payload, dict):
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise ArtifactCoverageError("inventory object must contain an 'artifacts' list")
        entries = [item for item in artifacts if isinstance(item, dict)]
    elif isinstance(payload, list):
        entries = [item for item in payload if isinstance(item, dict)]
    else:
        raise ArtifactCoverageError("inventory must be an object, a list, or JSON-lines")
    return entries


def _finding(severity: str, code: str, detail: str, requirement_id: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "requirement_id": requirement_id,
        "detail": detail,
    }


def _local_file_hashes(paths: Iterable[str], repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    present: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for relative in paths:
        absolute = repo_root / relative
        if absolute.is_file():
            present.append(
                {
                    "path": relative,
                    "size_bytes": absolute.stat().st_size,
                    "sha256": hashlib.sha256(absolute.read_bytes()).hexdigest(),
                }
            )
        else:
            missing.append({"path": relative})
    return present, missing


def audit_coverage(
    requirements: Mapping[str, Any],
    inventory: list[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    repo_root: Path | str = ".",
    inventory_source: str | None = None,
) -> dict[str, Any]:
    """Compare retention requirements against an observed artifact inventory."""

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = Path(repo_root)
    findings: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []

    if not inventory:
        findings.append(
            _finding(
                "warning",
                "empty_inventory",
                "no artifacts were supplied; coverage cannot be confirmed",
                "<global>",
            )
        )

    for requirement in requirements.get("requirements", []):
        requirement_id = str(requirement["requirement_id"])
        artifact_name = str(requirement["artifact_name"])
        required_through = parse_utc(
            requirement["must_remain_retrievable_through_utc"],
            f"{requirement_id}.must_remain_retrievable_through_utc",
        )
        max_age_hours = requirement.get("max_age_hours")

        matching: list[dict[str, Any]] = []
        for item in inventory:
            if str(item.get("name")) != artifact_name:
                continue
            if item.get("expired") is True:
                continue
            matching.append(dict(item))

        entry: dict[str, Any] = {
            "requirement_id": requirement_id,
            "lane": requirement.get("lane"),
            "artifact_name": artifact_name,
            "producer": requirement.get("artifact_producer"),
            "must_remain_retrievable_through_utc": required_through.isoformat().replace("+00:00", "Z"),
            "max_age_hours": max_age_hours,
            "matching_artifacts": len(matching),
            "newest_created_at_utc": None,
            "newest_expires_at_utc": None,
            "newest_age_hours": None,
            "retention_covers_required_through": None,
            "satisfied": False,
            "notes": requirement.get("notes"),
        }

        # Local canonical files are checked even when the CI artifact is missing,
        # so a missing artifact never hides a present-or-absent local file.
        local_paths = requirement.get("local_paths") or []
        present, missing = _local_file_hashes([str(p) for p in local_paths], root)
        entry["local_paths_present"] = present
        entry["local_paths_missing"] = [item["path"] for item in missing]
        if missing:
            findings.append(
                _finding(
                    "warning",
                    "local_artifact_missing",
                    "required local canonical files are absent: " + ", ".join(item["path"] for item in missing),
                    requirement_id,
                )
            )

        if not matching:
            findings.append(
                _finding(
                    "error",
                    "artifact_missing",
                    f"no unexpired artifact named {artifact_name!r} was found in the inventory",
                    requirement_id,
                )
            )
            entries.append(entry)
            continue

        def _created(item: dict[str, Any]) -> datetime:
            return parse_utc(item.get("created_at"), f"{requirement_id}.created_at")

        newest = max(matching, key=_created)
        created_at = _created(newest)
        entry["newest_created_at_utc"] = created_at.isoformat().replace("+00:00", "Z")
        entry["newest_age_hours"] = round((moment - created_at).total_seconds() / 3600.0, 3)
        entry["newest_artifact_id"] = newest.get("id")

        expires_raw = newest.get("expires_at")
        if expires_raw:
            expires_at = parse_utc(expires_raw, f"{requirement_id}.expires_at")
            entry["newest_expires_at_utc"] = expires_at.isoformat().replace("+00:00", "Z")
            entry["retention_covers_required_through"] = expires_at >= required_through
            if expires_at < required_through:
                findings.append(
                    _finding(
                        "error",
                        "artifact_expires_before_required_through",
                        (
                            f"newest {artifact_name!r} expires {entry['newest_expires_at_utc']} "
                            f"before the required-through date "
                            f"{entry['must_remain_retrievable_through_utc']}"
                        ),
                        requirement_id,
                    )
                )

        if isinstance(max_age_hours, (int, float)) and entry["newest_age_hours"] > float(max_age_hours):
            findings.append(
                _finding(
                    "warning",
                    "artifact_stale",
                    (
                        f"newest {artifact_name!r} is {entry['newest_age_hours']}h old "
                        f"(declared maximum {max_age_hours}h)"
                    ),
                    requirement_id,
                )
            )

        anchor_raw = requirement.get("recomputable_anchor_utc")
        horizon_days = requirement.get("rederivation_horizon_days")
        if anchor_raw and isinstance(horizon_days, (int, float)) and horizon_days > 0:
            from datetime import timedelta

            anchor = parse_utc(anchor_raw, f"{requirement_id}.recomputable_anchor_utc")
            horizon_end = anchor + timedelta(days=float(horizon_days))
            entry["derivation_horizon_end_utc"] = horizon_end.isoformat().replace("+00:00", "Z")
            entry["required_through_inside_derivation_horizon"] = required_through <= horizon_end
            if required_through > horizon_end:
                findings.append(
                    _finding(
                        "warning",
                        "rederivation_horizon_exceeded",
                        (
                            "the declared upstream source is expected to serve data only until "
                            f"{entry['derivation_horizon_end_utc']}, before the required-through "
                            f"date {entry['must_remain_retrievable_through_utc']}; the retained "
                            "artifact becomes the only copy of those inputs"
                        ),
                        requirement_id,
                    )
                )

        entry["satisfied"] = not any(
            finding["requirement_id"] == requirement_id and finding["severity"] == "error"
            for finding in findings
        )
        entries.append(entry)

    satisfied = sum(1 for entry in entries if entry["satisfied"])
    highest = max((finding["severity"] for finding in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol_name": requirements.get("protocol_name", "evidence-retention-coverage-v1"),
        "status": "reporting_only",
        "generated_at_utc": moment.isoformat().replace("+00:00", "Z"),
        "requirements_source": requirements.get("_source"),
        "inventory_source": inventory_source,
        "inventory_size": len(inventory),
        "requirements_total": len(entries),
        "requirements_satisfied": satisfied,
        "requirements_open": len(entries) - satisfied,
        "coverage_ok": highest != "error",
        "highest_severity": highest,
        "requirements": entries,
        "findings": findings,
        "claims": {
            "counts_prospective_batches": False,
            "computes_strategy_verdicts": False,
            "certifies_data_quality": False,
            "extends_or_deletes_artifacts": False,
            "live_order_transmission_supported": False,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def audit_from_paths(
    requirements_path: Path | str = DEFAULT_REQUIREMENTS,
    inventory_path: Path | str | None = None,
    *,
    now: datetime | None = None,
    repo_root: Path | str = ".",
) -> dict[str, Any]:
    """Convenience wrapper: load requirements and inventory, then audit."""

    requirements = load_requirements(requirements_path)
    requirements["_source"] = str(requirements_path)
    inventory = load_inventory(inventory_path) if inventory_path else []
    return audit_coverage(
        requirements,
        inventory,
        now=now,
        repo_root=repo_root,
        inventory_source=str(inventory_path) if inventory_path else None,
    )


def coverage_markdown(report: Mapping[str, Any]) -> str:
    """Render a human-readable summary of a coverage audit (no verdicts)."""

    lines = [
        "# Evidence retention coverage",
        "",
        "- Status: reporting only (this report deletes, extends, and promotes nothing)",
        f"- Generated: {report['generated_at_utc']}",
        f"- Inventory entries observed: {report['inventory_size']}",
        f"- Requirements satisfied: {report['requirements_satisfied']}/{report['requirements_total']}",
        f"- Coverage OK: {report['coverage_ok']} (highest finding severity: {report['highest_severity']})",
        "",
        "| Requirement | Artifact | Must remain through | Newest age (h) | Retention covers | Satisfied |",
        "|---|---|---|---|---|---|",
    ]
    for entry in report["requirements"]:
        lines.append(
            "| {req} | {name} | {through} | {age} | {covers} | {ok} |".format(
                req=entry["requirement_id"],
                name=entry["artifact_name"],
                through=entry["must_remain_retrievable_through_utc"],
                age=entry["newest_age_hours"],
                covers=entry["retention_covers_required_through"],
                ok=entry["satisfied"],
            )
        )
    lines.append("")
    if report["findings"]:
        lines.append("## Findings")
        lines.append("")
        for finding in report["findings"]:
            lines.append(
                f"- [{finding['severity']}] `{finding['code']}` ({finding['requirement_id']}): {finding['detail']}"
            )
    else:
        lines.append("No findings.")
    lines.append("")
    return "\n".join(lines)

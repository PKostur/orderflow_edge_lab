"""Append-only registry of hypothesis inspections.

The repository's rule is that previously inspected data is spent for independent
validation. That rule was enforced by discipline and by narrative status files.
This module makes it mechanical: every lane that was looked at gets one entry
recording what was asked, over which window, against which dependence clusters,
and in what state it ended -- so a later review can show what it is *not*
allowed to re-use as fresh evidence.

Two properties matter more than the schema:

* **Terminal identifiers are terminal.** A ``FALSIFIED`` or ``CLOSED`` entry sets
  ``id_reusable`` false: the identifier may not be reopened, re-sided or
  re-phased, because a second attempt under the same name silently converts an
  inspected dataset into apparent confirmation.
* **``data_spent`` follows the state.** Once a lane has been evaluated, falsified
  or closed, its window is spent; only a still-``REGISTERED`` prospective watch
  can leave it false.

This is a navigation and accounting layer. It adjudicates nothing; the canonical
records it points at remain the authority, and it reproduces no numbers from
them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_REGISTRY = Path("config/hypothesis_inspection_registry_v1.json")

STATUSES = ("REGISTERED", "EVALUATED", "FALSIFIED", "CLOSED")
TERMINAL_STATUSES = ("FALSIFIED", "CLOSED")
EVIDENCE_KINDS = ("development", "prospective", "transfer", "observational")

REQUIRED_FIELDS = (
    "hypothesis_id",
    "family",
    "statement",
    "evidence_kind",
    "registered_at_utc",
    "status",
    "data_spent",
    "id_reusable",
    "canonical_record",
)

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


class InspectionRegistryError(ValueError):
    """Raised when the registry cannot be read or written as required."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def entries_digest(entries: list[Mapping[str, Any]]) -> str:
    """Digest over the entry list alone, so a hand edit is detectable."""

    return _canonical_sha256(list(entries))


def load_registry(path: Path | str = DEFAULT_REGISTRY) -> dict[str, Any]:
    """Load and structurally validate the registry file."""

    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InspectionRegistryError(f"cannot read registry: {target}") from exc
    except json.JSONDecodeError as exc:
        raise InspectionRegistryError(f"registry is not valid JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise InspectionRegistryError("registry must be a JSON object")
    if payload.get("schema_version") != 1:
        raise InspectionRegistryError("registry schema_version must be 1")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise InspectionRegistryError("registry must carry a non-empty entries list")
    return payload


def validate_registry(registry: Mapping[str, Any], *, repo_root: Path | str = Path(".")) -> dict[str, Any]:
    """Validate every entry and the registry-level digest."""

    root = Path(repo_root)
    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, entry in enumerate(registry.get("entries", []), start=1):
        if not isinstance(entry, Mapping):
            findings.append(
                {
                    "severity": "error",
                    "code": "entry_invalid",
                    "hypothesis_id": None,
                    "detail": f"entry {index} is not an object",
                }
            )
            continue
        hypothesis_id = str(entry.get("hypothesis_id", ""))
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            findings.append(
                {
                    "severity": "error",
                    "code": "entry_invalid",
                    "hypothesis_id": hypothesis_id or f"<entry {index}>",
                    "detail": f"missing required fields: {', '.join(missing)}",
                }
            )
        if hypothesis_id in seen:
            findings.append(
                {
                    "severity": "error",
                    "code": "hypothesis_id_duplicate",
                    "hypothesis_id": hypothesis_id,
                    "detail": "the same hypothesis identifier appears twice",
                }
            )
        seen.add(hypothesis_id)

        status = entry.get("status")
        if status not in STATUSES:
            findings.append(
                {
                    "severity": "error",
                    "code": "status_invalid",
                    "hypothesis_id": hypothesis_id,
                    "detail": f"status must be one of {STATUSES}",
                }
            )
        kind = entry.get("evidence_kind")
        if kind not in EVIDENCE_KINDS:
            findings.append(
                {
                    "severity": "error",
                    "code": "evidence_kind_invalid",
                    "hypothesis_id": hypothesis_id,
                    "detail": f"evidence_kind must be one of {EVIDENCE_KINDS}",
                }
            )

        data_spent = bool(entry.get("data_spent"))
        if status in TERMINAL_STATUSES or status == "EVALUATED":
            if not data_spent:
                findings.append(
                    {
                        "severity": "error",
                        "code": "data_spent_inconsistent",
                        "hypothesis_id": hypothesis_id,
                        "detail": (
                            f"status {status} means the window was inspected; data_spent must be true"
                        ),
                    }
                )
        elif status == "REGISTERED" and data_spent:
            findings.append(
                {
                    "severity": "warning",
                    "code": "data_spent_before_outcome",
                    "hypothesis_id": hypothesis_id,
                    "detail": "a still-registered watch reports its window as spent",
                }
            )

        if status in TERMINAL_STATUSES and bool(entry.get("id_reusable")):
            findings.append(
                {
                    "severity": "error",
                    "code": "terminal_id_marked_reusable",
                    "hypothesis_id": hypothesis_id,
                    "detail": (
                        "a falsified or closed identifier may not be reused; reopening it would "
                        "convert already-inspected data into apparent confirmation"
                    ),
                }
            )

        canonical = entry.get("canonical_record")
        record = {
            "hypothesis_id": hypothesis_id,
            "family": entry.get("family"),
            "status": status,
            "evidence_kind": kind,
            "data_spent": data_spent,
            "id_reusable": bool(entry.get("id_reusable")),
            "canonical_record": canonical,
            "canonical_record_exists": (root / str(canonical)).is_file() if canonical else False,
            "dependence_clusters": entry.get("dependence_clusters"),
            "data_window": entry.get("data_window"),
        }
        records.append(record)

        if canonical:
            candidate = root / str(canonical)
            if not candidate.exists():
                findings.append(
                    {
                        "severity": "warning",
                        "code": "canonical_record_missing",
                        "hypothesis_id": hypothesis_id,
                        "detail": f"canonical record not found in this checkout: {canonical}",
                    }
                )
        else:
            findings.append(
                {
                    "severity": "error",
                    "code": "canonical_record_missing",
                    "hypothesis_id": hypothesis_id,
                    "detail": "no canonical record declared",
                }
            )

    recorded_digest = registry.get("registry_sha256")
    actual_digest = entries_digest(list(registry.get("entries", [])))
    digest_matches = recorded_digest == actual_digest
    if not digest_matches:
        findings.append(
            {
                "severity": "error",
                "code": "registry_sha256_mismatch",
                "hypothesis_id": None,
                "detail": (
                    "the registry digest does not match its entries; entries were edited without "
                    "updating registry_sha256 (or without using the append helper)"
                ),
            }
        )

    spent = [
        {
            "hypothesis_id": record["hypothesis_id"],
            "evidence_kind": record["evidence_kind"],
            "data_window": record["data_window"],
            "dependence_clusters": record["dependence_clusters"],
        }
        for record in records
        if record["data_spent"]
    ]
    highest = max((finding["severity"] for finding in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    report = {
        "schema_version": 1,
        "analysis": "hypothesis_inspection_registry_validation",
        "registry_version": registry.get("version"),
        "entries_total": len(registry.get("entries", [])),
        "terminal_count": sum(1 for record in records if record["status"] in TERMINAL_STATUSES),
        "registered_count": sum(1 for record in records if record["status"] == "REGISTERED"),
        "spent_windows": spent,
        "registry_sha256_matches": digest_matches,
        "registry_sha256_recorded": recorded_digest,
        "registry_sha256_actual": actual_digest,
        "entries": records,
        "findings": findings,
        "highest_severity": highest,
        "valid": not any(finding["severity"] == "error" for finding in findings),
        "claims": {
            "adjudicates_evidence": False,
            "recomputes_lane_results": False,
            "reopens_terminal_identifiers": False,
            "computes_strategy_verdicts": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def append_entry(registry: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    """Append one entry and refresh the registry digest.

    Appending is only for a *new* hypothesis recorded before its window is
    inspected, or for a state transition on an existing identifier. It refuses a
    duplicate identifier so that a falsified lane cannot be quietly re-registered.
    """

    existing = [dict(item) for item in registry.get("entries", [])]
    hypothesis_id = str(entry.get("hypothesis_id", "")).strip()
    if not hypothesis_id:
        raise InspectionRegistryError("entry needs a hypothesis_id")
    if any(str(item.get("hypothesis_id")) == hypothesis_id for item in existing):
        raise InspectionRegistryError(
            f"{hypothesis_id} is already registered; use a versioned identifier for a new hypothesis"
        )
    updated_entry = dict(entry)
    updated_entry["hypothesis_id"] = hypothesis_id
    merged = [*existing, updated_entry]
    updated = dict(registry)
    updated["entries"] = merged
    updated["registry_sha256"] = entries_digest(merged)
    return updated


def registry_markdown(report: Mapping[str, Any]) -> str:
    """Render the registry validation and the spent-window inventory."""

    lines = [
        "# Hypothesis inspection registry",
        "",
        f"- Registry version: `{report['registry_version']}`",
        f"- Entries: {report['entries_total']} ({report['registered_count']} still registered, "
        f"{report['terminal_count']} terminal)",
        f"- Digest matches: `{report['registry_sha256_matches']}`; valid: `{report['valid']}`; "
        f"highest severity `{report['highest_severity']}`",
        "",
        "## Lanes",
        "",
        "| Hypothesis | Kind | Status | Data spent | ID reusable | Canonical record |",
        "|---|---|---|---|---|---|",
    ]
    for record in report["entries"]:
        lines.append(
            f"| `{record['hypothesis_id']}` | {record['evidence_kind']} | {record['status']} | "
            f"`{record['data_spent']}` | `{record['id_reusable']}` | `{record['canonical_record']}` |"
        )
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("- None.")
    for finding in report["findings"]:
        lines.append(
            f"- `{finding['severity']}` `{finding['code']}` "
            f"({finding.get('hypothesis_id')}) — {finding['detail']}"
        )
    lines.append("")
    return "\n".join(lines)

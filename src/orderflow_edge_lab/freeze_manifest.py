"""Hash contract for frozen research definitions.

The repository already freezes thresholds, feature families and watch
definitions in JSON configs, and several of them carry a freeze commit. What it
did not have is a mechanism that *notices* when one of those files changes.

This module verifies a manifest of ``(path, sha256)`` pairs for the files whose
numeric content must never move silently -- ``discovery-v1`` thresholds, the
pre-registered ``regime-research`` feature families, the frozen strategy
conditioning blocks and the prospective watch definitions. A change to any of
them has to be deliberate: it must be a versioned successor with a fresh freeze
record, not an edit in place.

Verification only. There is deliberately no write mode: rewriting the recorded
hash is exactly the operation this module exists to make visible, so it stays a
hand edit plus a review, not a flag.

A note on scope. This manifest covers *research* definitions, not documentation.
``STATUS.md``, ``README.md``, ``docs/`` and the navigation layer are expected to
change and are not listed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_MANIFEST = Path("config/frozen_manifest_v1.json")

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}
_SHA_LENGTH = 64
_HEX = set("0123456789abcdef")


class FreezeManifestError(ValueError):
    """Raised when the manifest itself cannot be read or is malformed."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path | str) -> str:
    """Return the SHA-256 of a file's bytes."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA_LENGTH
        and all(char in _HEX for char in value.lower())
    )


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load and structurally validate the frozen manifest."""

    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FreezeManifestError(f"cannot read manifest: {target}") from exc
    except json.JSONDecodeError as exc:
        raise FreezeManifestError(f"manifest is not valid JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise FreezeManifestError("manifest must be a JSON object")
    if payload.get("schema_version") != 1:
        raise FreezeManifestError("manifest schema_version must be 1")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise FreezeManifestError("manifest must list at least one file")
    for entry in files:
        if not isinstance(entry, Mapping) or not entry.get("path"):
            raise FreezeManifestError("every manifest entry needs a path")
    return payload


def build_manifest(
    entries: Sequence[Mapping[str, Any]],
    *,
    repo_root: Path | str = Path("."),
    version: str,
    recorded_at_utc: str,
) -> dict[str, Any]:
    """Build a manifest from ``{path, frozen_for, freeze_reference, change_rule}`` specs."""

    root = Path(repo_root)
    files: list[dict[str, Any]] = []
    for entry in entries:
        relative = str(entry["path"])
        target = root / relative
        if not target.is_file():
            raise FreezeManifestError(f"cannot record a missing file: {relative}")
        files.append(
            {
                "path": relative,
                "sha256": file_sha256(target),
                "frozen_for": entry.get("frozen_for"),
                "freeze_reference": entry.get("freeze_reference"),
                "change_rule": entry.get("change_rule"),
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "version": version,
        "recorded_at_utc": recorded_at_utc,
        "purpose": (
            "Frozen research definitions whose numeric content must not move without a "
            "deliberate, reviewable version bump."
        ),
        "files": files,
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def verify_frozen_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Compare recorded hashes with the working tree."""

    root = Path(repo_root)
    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in manifest.get("files", []):
        relative = str(entry.get("path", ""))
        recorded = entry.get("sha256")
        if not relative or not _valid_sha256(recorded):
            findings.append(
                {
                    "severity": "error",
                    "code": "manifest_entry_invalid",
                    "path": relative or "<empty>",
                    "detail": "entry needs a path and a 64-character hex sha256",
                }
            )
            continue
        if relative in seen:
            findings.append(
                {
                    "severity": "error",
                    "code": "manifest_entry_duplicate",
                    "path": relative,
                    "detail": "the same file is recorded twice",
                }
            )
            continue
        seen.add(relative)

        target = root / relative
        record: dict[str, Any] = {
            "path": relative,
            "recorded_sha256": recorded,
            "frozen_for": entry.get("frozen_for"),
            "change_rule": entry.get("change_rule"),
        }
        if not target.is_file():
            record.update({"exists": False, "matches": False, "actual_sha256": None})
            findings.append(
                {
                    "severity": "error",
                    "code": "frozen_file_missing",
                    "path": relative,
                    "detail": "a frozen definition is missing from the tree",
                }
            )
            records.append(record)
            continue

        actual = file_sha256(target)
        matches = actual == str(recorded)
        record.update({"exists": True, "matches": matches, "actual_sha256": actual})
        records.append(record)
        if not matches:
            findings.append(
                {
                    "severity": "error",
                    "code": "frozen_file_changed",
                    "path": relative,
                    "detail": (
                        "recorded hash does not match the working tree; a frozen definition changed. "
                        "Either restore it or move to a versioned successor with a fresh freeze record, "
                        "then update this manifest in the same reviewed change."
                    ),
                }
            )
        if not entry.get("change_rule"):
            findings.append(
                {
                    "severity": "warning",
                    "code": "change_rule_absent",
                    "path": relative,
                    "detail": "no change_rule recorded for this frozen file",
                }
            )

    highest = max((f["severity"] for f in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    report = {
        "schema_version": 1,
        "analysis": "frozen_manifest_verification",
        "manifest_version": manifest.get("version"),
        "manifest_recorded_at_utc": manifest.get("recorded_at_utc"),
        "files_total": len(manifest.get("files", [])),
        "files_matching": sum(1 for record in records if record.get("matches")),
        "files_changed": sum(1 for record in records if record.get("exists") and not record.get("matches")),
        "files_missing": sum(1 for record in records if not record.get("exists")),
        "files": records,
        "findings": findings,
        "highest_severity": highest,
        "verified": not any(finding["severity"] == "error" for finding in findings),
        "claims": {
            "changes_frozen_definitions": False,
            "authorises_retuning": False,
            "computes_strategy_verdicts": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def freeze_manifest_markdown(report: Mapping[str, Any]) -> str:
    """Render the manifest verification for a step summary or review record."""

    lines = [
        "# Frozen definition hash check",
        "",
        f"- Manifest version: `{report['manifest_version']}` (recorded {report['manifest_recorded_at_utc']})",
        f"- Files: {report['files_total']} ({report['files_matching']} matching, "
        f"{report['files_changed']} changed, {report['files_missing']} missing)",
        f"- Verified: `{report['verified']}`; highest severity `{report['highest_severity']}`",
        "",
        "| File | Matches |",
        "|---|---|",
    ]
    for record in report["files"]:
        lines.append(f"| `{record['path']}` | `{record['matches']}` |")
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("- None.")
    for finding in report["findings"]:
        lines.append(f"- `{finding['severity']}` `{finding['code']}` — {finding['path']}: {finding['detail']}")
    lines.append("")
    return "\n".join(lines)

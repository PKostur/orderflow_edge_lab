"""Workflow-to-artifact contract.

``capture-health-watch-v1.yml`` spent its whole life reporting "directory
absent", because it scanned a path that CI never populated. Nothing failed,
because nothing checked that the artifact a workflow consumes is produced by
*any* workflow. That is the class of bug this module closes.

It scans ``.github/workflows/*.yml`` for two things:

* every ``actions/upload-artifact`` step's artifact name (a *producer*), and
* every ``actions/download-artifact`` step's ``name``/``pattern`` (a *consumer*),

then requires every consumer to have a producer, and requires every artifact a
retention requirement declares to have both a producer and the producer named in
the requirement itself.

The scanner is line-based on purpose: the workflows are hand-written YAML with
consistent indentation, and a line scanner keeps this module free of a YAML
dependency in a project whose runtime extras are deliberately small (numpy,
pandas, scikit-learn). The tests assert it reads the real tree without false
positives, which is the property that matters.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_REQUIREMENTS = Path("config/evidence_retention_requirements_v1.json")
DEFAULT_WORKFLOW_DIR = Path(".github/workflows")

_UPLOAD = "actions/upload-artifact"
_DOWNLOAD = "actions/download-artifact"

# ``uses:`` may sit on its own line or inline after the step dash
# (``- uses: actions/download-artifact@v4``); both forms are common here.
_USES_RE = re.compile(r"^(?P<prefix>\s*(?:-\s+)?)uses:\s*(?P<value>\S+)")
_STEP_RE = re.compile(r"^\s*-\s")
_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>name|pattern):\s*(?P<value>.+?)\s*$")
_TOP_NAME_RE = re.compile(r"^name:\s*(?P<value>.+?)\s*$")
_CRON_RE = re.compile(r"^\s*-\s*cron:\s*['\"]?(?P<value>[^'\"]+)['\"]?\s*$")
_EXPRESSION_RE = re.compile(r"\$\{\{[^}]*\}\}")

# Artifacts are also consumed through the REST API inside shell steps
# (``gh api .../artifacts?... startswith("orderflow-discovery-replay-")``),
# which is precisely how the capture-health consumer reads its input. A scanner
# that only understood actions/download-artifact would repeat the original blind
# spot, so the shell path is scanned too.
_SHELL_STARTSWITH_RE = re.compile(r"startswith\(\s*['\"](?P<value>[^'\"]+)['\"]\s*\)")
_SHELL_GH_RUN_DOWNLOAD_RE = re.compile(r"gh run download[^\n]*?(?:-n|--name)\s+(?P<value>[^\s'\"]+)")
_SHELL_ARTIFACT_API_RE = re.compile(r"gh api[^\n]*artifacts")

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


class WorkflowContractError(ValueError):
    """Raised when a workflow file or requirement cannot be read."""


def _clean_value(value: str) -> str:
    text = value.strip()
    if text.startswith(("'", '"')) and text.endswith(("'", '"')) and len(text) >= 2:
        text = text[1:-1]
    if " #" in text:
        text = text.split(" #", 1)[0].strip()
    return text


def normalize_artifact_name(value: str) -> str:
    """Reduce an artifact identifier to its static, comparable core.

    Template expressions (``${{ github.run_id }}``) and trailing separators are
    removed, and repeated separators collapsed, so
    ``orderflow-discovery-replay-${{ github.run_id }}``,
    ``orderflow-discovery-replay-`` and ``orderflow-discovery-replay`` all
    normalize to ``orderflow-discovery-replay``.
    """

    static = _EXPRESSION_RE.sub("", str(value))
    static = static.strip().strip("'\"")
    static = re.sub(r"[-_\s]+", "-", static)
    return static.strip("-")


def _is_pattern(value: str) -> bool:
    return "*" in str(value) or "?" in str(value)


def _pattern_core(value: str) -> str:
    return normalize_artifact_name(str(value).replace("*", "").replace("?", ""))


def matches(producer_value: str, consumer_value: str) -> bool:
    """True when a producer identifier can satisfy a consumer identifier."""

    producer = normalize_artifact_name(producer_value)
    if not producer:
        return False
    if _is_pattern(consumer_value):
        core = _pattern_core(consumer_value)
        return bool(core) and (producer == core or producer.startswith(core))
    consumer = normalize_artifact_name(consumer_value)
    return bool(consumer) and producer == consumer


def scan_workflow(path: Path) -> dict[str, Any]:
    """Extract artifact producers/consumers and schedule from one workflow file."""

    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise WorkflowContractError(f"cannot read workflow: {path}") from exc

    uploads: list[str] = []
    downloads: list[dict[str, str]] = []
    schedules: list[str] = []
    workflow_name: str | None = None

    mode: str | None = None
    uses_indent = -1

    for line in lines:
        if workflow_name is None:
            top = _TOP_NAME_RE.match(line)
            if top:
                workflow_name = _clean_value(top.group("value"))

        cron = _CRON_RE.match(line)
        if cron:
            schedules.append(_clean_value(cron.group("value")))

        if _STEP_RE.match(line):
            mode = None
            uses_indent = -1

        uses = _USES_RE.match(line)
        if uses:
            uses_indent = len(uses.group("prefix"))
            target = uses.group("value")
            if target.startswith(_UPLOAD):
                mode = "upload"
            elif target.startswith(_DOWNLOAD):
                mode = "download"
            else:
                mode = None
            continue

        if mode is None:
            continue

        key = _KEY_RE.match(line)
        if not key:
            continue
        if len(key.group("indent")) <= uses_indent:
            continue
        value = _clean_value(key.group("value"))
        if not value:
            continue
        if mode == "upload" and key.group("key") == "name":
            uploads.append(value)
        elif mode == "download":
            downloads.append({"kind": key.group("key"), "value": value})

    text = "\n".join(lines)
    for match in _SHELL_STARTSWITH_RE.finditer(text):
        downloads.append({"kind": "shell_pattern", "value": f"{match.group('value')}*"})
    for match in _SHELL_GH_RUN_DOWNLOAD_RE.finditer(text):
        downloads.append({"kind": "shell_name", "value": match.group("value")})

    return {
        # Forward slashes always: retention requirements declare producer paths in
        # POSIX form, so recording a platform-native path would make every
        # declaration fail to match on Windows.
        "path": Path(path).as_posix(),
        "name": workflow_name,
        "uploads": uploads,
        "downloads": downloads,
        "schedules": schedules,
        "uses_artifact_rest_api": bool(_SHELL_ARTIFACT_API_RE.search(text)),
    }


def scan_workflows(root: Path | str = Path("."), *, workflow_dir: Path | str = DEFAULT_WORKFLOW_DIR) -> dict[str, dict[str, Any]]:
    """Scan every workflow file under ``root``."""

    directory = Path(root) / workflow_dir
    if not directory.is_dir():
        raise WorkflowContractError(f"workflow directory not found: {directory}")
    scans: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml")):
        scans[path.relative_to(root).as_posix()] = scan_workflow(path)
    if not scans:
        raise WorkflowContractError(f"no workflow files under {directory}")
    return scans


def load_requirements(path: Path | str = DEFAULT_REQUIREMENTS) -> dict[str, Any]:
    """Load the artifact retention requirements."""

    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowContractError(f"cannot read requirements: {target}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowContractError(f"requirements are not valid JSON: {target}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("requirements"), list):
        raise WorkflowContractError("requirements file must carry a 'requirements' list")
    return payload


def _producer_index(scans: Mapping[str, Mapping[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Artifact name -> [(workflow path, raw artifact name)].

    Tuples rather than ``"path:name"`` strings: a Windows path can contain a
    colon, and splitting on it would silently mangle the producer.
    """

    index: dict[str, list[tuple[str, str]]] = {}
    for relative, scan in scans.items():
        for name in scan.get("uploads", []):
            index.setdefault(normalize_artifact_name(name), []).append((relative, name))
    return index


def audit_workflow_contract(
    *,
    repo_root: Path | str = Path("."),
    workflow_dir: Path | str = DEFAULT_WORKFLOW_DIR,
    requirements_path: Path | str = DEFAULT_REQUIREMENTS,
) -> dict[str, Any]:
    """Verify the workflow-to-artifact graph."""

    root = Path(repo_root)
    scans = scan_workflows(root, workflow_dir=workflow_dir)
    requirements = load_requirements(root / requirements_path if not Path(requirements_path).is_absolute() else requirements_path)
    producers = _producer_index(scans)

    findings: list[dict[str, Any]] = []
    consumers: list[dict[str, Any]] = []

    for relative, scan in sorted(scans.items()):
        if not scan.get("name"):
            findings.append(
                {
                    "severity": "warning",
                    "code": "workflow_name_absent",
                    "workflow": relative,
                    "detail": "workflow declares no top-level name",
                }
            )
        if not scan.get("schedules"):
            findings.append(
                {
                    "severity": "info",
                    "code": "workflow_has_no_schedule",
                    "workflow": relative,
                    "detail": "workflow is event-driven only (no cron); it produces no periodic evidence",
                }
            )
        if scan.get("uses_artifact_rest_api") and not any(
            download["kind"] in ("shell_pattern", "shell_name") for download in scan.get("downloads", [])
        ):
            findings.append(
                {
                    "severity": "warning",
                    "code": "artifact_rest_fetch_without_named_filter",
                    "workflow": relative,
                    "detail": (
                        "reads the artifact REST API but names no artifact filter, so no workflow can be "
                        "checked as its producer"
                    ),
                }
            )

        for download in scan.get("downloads", []):
            value = str(download["value"])
            satisfied_by = sorted(
                {entry[0] for name, entries in producers.items() if matches(name, value) for entry in entries}
            )
            consumers.append(
                {
                    "workflow": relative,
                    "kind": download["kind"],
                    "value": value,
                    "producers": satisfied_by,
                    "satisfied": bool(satisfied_by),
                }
            )
            if not satisfied_by:
                findings.append(
                    {
                        "severity": "error",
                        "code": "artifact_downloaded_without_producer",
                        "workflow": relative,
                        "detail": (
                            f"downloads artifact {value!r} ({download['kind']}) but no workflow uploads "
                            "a matching artifact name; this step can never receive anything"
                        ),
                    }
                )

    requirement_records: list[dict[str, Any]] = []
    for requirement in requirements["requirements"]:
        artifact = str(requirement.get("artifact_name", ""))
        declared_raw = str(requirement.get("artifact_producer", ""))
        declared_producer = Path(declared_raw).as_posix() if declared_raw else ""
        produced = sorted(
            {entry[0] for name, entries in producers.items() if matches(name, artifact) for entry in entries}
        )
        record = {
            "requirement_id": requirement.get("requirement_id"),
            "artifact_name": artifact,
            "declared_producer": declared_raw,
            "producing_workflows": produced,
            "declared_producer_uploads_it": False,
        }
        if not produced:
            findings.append(
                {
                    "severity": "error",
                    "code": "required_artifact_without_producer",
                    "workflow": declared_producer,
                    "detail": f"retention requirement {artifact!r} has no producing workflow anywhere",
                }
            )
        elif declared_producer and declared_producer not in produced:
            findings.append(
                {
                    "severity": "error",
                    "code": "declared_producer_does_not_upload_artifact",
                    "workflow": declared_producer,
                    "detail": (
                        f"retention requirement declares {declared_producer} as the producer of "
                        f"{artifact!r}, but that workflow does not upload it; uploads found in {produced}"
                    ),
                }
            )
        else:
            record["declared_producer_uploads_it"] = True
        requirement_records.append(record)

    highest = max((finding["severity"] for finding in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    report = {
        "schema_version": 1,
        "analysis": "workflow_artifact_contract",
        "workflows_scanned": len(scans),
        "artifact_producers": {
            name: sorted(f"{path}:{artifact}" for path, artifact in entries)
            for name, entries in sorted(producers.items())
        },
        "consumers": consumers,
        "requirements": requirement_records,
        "findings": findings,
        "highest_severity": highest,
        "contract_ok": not any(finding["severity"] == "error" for finding in findings),
        "claims": {
            "runs_workflows": False,
            "fetches_external_data": False,
            "computes_strategy_verdicts": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return report


def workflow_contract_markdown(report: Mapping[str, Any]) -> str:
    """Render the contract audit."""

    lines = [
        "# Workflow to artifact contract",
        "",
        f"- Workflows scanned: {report['workflows_scanned']}",
        f"- Contract ok: `{report['contract_ok']}`; highest severity `{report['highest_severity']}`",
        f"- Findings: {len(report['findings'])}",
        "",
        "## Retention requirements",
        "",
        "| Requirement | Artifact | Declared producer uploads it |",
        "|---|---|---|",
    ]
    for record in report["requirements"]:
        lines.append(
            f"| `{record['requirement_id']}` | `{record['artifact_name']}` | "
            f"`{record['declared_producer_uploads_it']}` |"
        )
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("- None.")
    for finding in report["findings"]:
        lines.append(
            f"- `{finding['severity']}` `{finding['code']}` ({finding.get('workflow')}) — {finding['detail']}"
        )
    lines.append("")
    return "\n".join(lines)


def producer_names(scans: Iterable[Mapping[str, Any]]) -> list[str]:
    """Convenience: every artifact name produced across the supplied scans."""

    names: list[str] = []
    for scan in scans:
        names.extend(str(name) for name in scan.get("uploads", []))
    return names

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from orderflow_edge_lab.freeze_manifest import (
    DEFAULT_MANIFEST,
    FreezeManifestError,
    freeze_manifest_markdown,
    load_manifest,
    verify_frozen_manifest,
)
from orderflow_edge_lab.inspection_registry import (
    DEFAULT_REGISTRY as DEFAULT_INSPECTION_REGISTRY,
)
from orderflow_edge_lab.inspection_registry import (
    InspectionRegistryError,
    load_registry,
    registry_markdown,
    validate_registry,
)
from orderflow_edge_lab.preregistration import (
    DEFAULT_REGISTRY as DEFAULT_PREREGISTRATION_REGISTRY,
)
from orderflow_edge_lab.preregistration import (
    PreregistrationError,
    audit_preregistration,
    load_registry as load_preregistration_registry,
    preregistration_markdown,
)
from orderflow_edge_lab.workflow_contract import (
    DEFAULT_REQUIREMENTS,
    DEFAULT_WORKFLOW_DIR,
    WorkflowContractError,
    audit_workflow_contract,
    workflow_contract_markdown,
)

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One research-hygiene report over four mechanical contracts: whether every prospective watch "
            "fixed a decision rule and trial family, whether frozen definitions still match their recorded "
            "hashes, whether every artifact a workflow consumes has a producer, and whether the "
            "hypothesis-inspection registry is intact. Reporting and gating only; it changes no definition."
        )
    )
    parser.add_argument("--repo-root", default=".", help="Repository root (default: current directory).")
    parser.add_argument("--preregistration-registry", default=str(DEFAULT_PREREGISTRATION_REGISTRY))
    parser.add_argument("--frozen-manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--inspection-registry", default=str(DEFAULT_INSPECTION_REGISTRY))
    parser.add_argument("--workflow-dir", default=str(DEFAULT_WORKFLOW_DIR))
    parser.add_argument("--retention-requirements", default=str(DEFAULT_REQUIREMENTS))
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON report.")
    parser.add_argument("--markdown", help="Optional path for a human-readable report.")
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default="error",
        help="Exit 2 when findings at or above this severity exist (default: error).",
    )
    return parser


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def build_report(args: argparse.Namespace) -> dict:
    root = Path(args.repo_root)
    preregistration = audit_preregistration(
        load_preregistration_registry(root / args.preregistration_registry)
        if not Path(args.preregistration_registry).is_absolute()
        else load_preregistration_registry(args.preregistration_registry),
        repo_root=root,
    )
    frozen = verify_frozen_manifest(
        load_manifest(root / args.frozen_manifest)
        if not Path(args.frozen_manifest).is_absolute()
        else load_manifest(args.frozen_manifest),
        repo_root=root,
    )
    workflows = audit_workflow_contract(
        repo_root=root,
        workflow_dir=args.workflow_dir,
        requirements_path=args.retention_requirements,
    )
    inspection = validate_registry(
        load_registry(root / args.inspection_registry)
        if not Path(args.inspection_registry).is_absolute()
        else load_registry(args.inspection_registry),
        repo_root=root,
    )

    findings: list[dict] = []
    for component, payload in (
        ("preregistration", preregistration),
        ("frozen_manifest", frozen),
        ("workflow_contract", workflows),
        ("inspection_registry", inspection),
    ):
        for finding in payload.get("findings", []):
            findings.append({**finding, "component": component})

    highest = max((finding["severity"] for finding in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    report = {
        "schema_version": 1,
        "analysis": "research_hygiene_report",
        "repo_root": str(root),
        "components": {
            "preregistration": preregistration,
            "frozen_manifest": frozen,
            "workflow_contract": workflows,
            "inspection_registry": inspection,
        },
        "component_ok": {
            "preregistration": preregistration["audit_ok"],
            "frozen_manifest": frozen["verified"],
            "workflow_contract": workflows["contract_ok"],
            "inspection_registry": inspection["valid"],
        },
        "finding_counts": {
            severity: sum(1 for finding in findings if finding["severity"] == severity)
            for severity in ("info", "warning", "error")
        },
        "findings": findings,
        "highest_severity": highest,
        "hygiene_ok": not any(finding["severity"] == "error" for finding in findings),
        "claims": {
            "changes_frozen_definitions": False,
            "computes_strategy_verdicts": False,
            "promotes_strategy": False,
            "counts_prospective_batches": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return report


def hygiene_markdown(report: dict) -> str:
    lines = [
        "# Research hygiene report",
        "",
        f"- Components ok: {json.dumps(report['component_ok'], sort_keys=True)}",
        f"- Findings: {json.dumps(report['finding_counts'], sort_keys=True)}",
        f"- Hygiene ok: `{report['hygiene_ok']}`; highest severity `{report['highest_severity']}`",
        f"- Report hash: `{report['report_sha256']}`",
        "",
        preregistration_markdown(report["components"]["preregistration"]),
        freeze_manifest_markdown(report["components"]["frozen_manifest"]),
        workflow_contract_markdown(report["components"]["workflow_contract"]),
        registry_markdown(report["components"]["inspection_registry"]),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_report(args)
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), hygiene_markdown(report))
        print(json.dumps(report, sort_keys=True, indent=2))
        threshold = 2 if args.fail_on == "error" else 1 if args.fail_on == "warning" else 99
        if args.fail_on != "never" and _SEVERITY_ORDER[report["highest_severity"]] >= threshold:
            return 2
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        PreregistrationError,
        FreezeManifestError,
        WorkflowContractError,
        InspectionRegistryError,
    ) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_id: str
    focus: str
    status: str
    findings: list[Finding]
    checks_run: list[str]


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    focus: str
    required_paths: tuple[str, ...]
    forbidden_claims: tuple[str, ...]


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def _run_command(root: Path, command: list[str], timeout: int = 240) -> Finding:
    completed = subprocess.run(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout[-8000:]
    if completed.returncode == 0:
        return Finding(
            "info",
            "command_passed",
            f"Command passed: {' '.join(command)}",
            {"returncode": completed.returncode, "output_tail": output},
        )
    return Finding(
        "error",
        "command_failed",
        f"Command failed: {' '.join(command)}",
        {"returncode": completed.returncode, "output_tail": output},
    )


def _load_specs(config_path: Path) -> tuple[list[AgentSpec], dict[str, Any]]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported multi-agent configuration schema")
    specs = []
    for item in data.get("agents", []):
        specs.append(
            AgentSpec(
                agent_id=str(item["id"]),
                focus=str(item["focus"]),
                required_paths=tuple(str(value) for value in item.get("required_paths", [])),
                forbidden_claims=tuple(str(value).lower() for value in item.get("forbidden_claims", [])),
            )
        )
    if not specs:
        raise ValueError("multi-agent configuration contains no agents")
    return specs, dict(data.get("release_manager", {}))


def _required_path_findings(root: Path, spec: AgentSpec) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    checks: list[str] = []
    for rel in spec.required_paths:
        checks.append(f"required_path:{rel}")
        if not (root / rel).exists():
            findings.append(Finding("error", "missing_required_path", f"Required path is missing: {rel}", {"path": rel}))
    return findings, checks


def _claim_findings(root: Path, spec: AgentSpec) -> tuple[list[Finding], list[str]]:
    if not spec.forbidden_claims:
        return [], []
    findings: list[Finding] = []
    checks = ["unsupported_claim_scan"]
    targets = [root / "README.md", root / "docs", root / "src" / "orderflow_edge_lab"]
    for target in targets:
        paths = [target] if target.is_file() else sorted(target.rglob("*.py")) + sorted(target.rglob("*.md")) if target.exists() else []
        for path in paths:
            text = _read_text(path).lower()
            for phrase in spec.forbidden_claims:
                if phrase in text:
                    findings.append(
                        Finding(
                            "warning",
                            "unsupported_claim_phrase",
                            f"Potentially unsupported claim phrase found: {phrase}",
                            {"path": str(path.relative_to(root)), "phrase": phrase},
                        )
                    )
    return findings, checks


def _domain_findings(root: Path, spec: AgentSpec, run_commands: bool) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    checks: list[str] = []

    if spec.agent_id == "data_integrity":
        checks.extend(["zero_cost_dxfeed_path", "mexc_replay_path"])
        if not (root / "docs" / "ZERO_COST_DATA_PATH.md").exists():
            findings.append(Finding("warning", "zero_cost_path_undocumented", "Zero-additional-cost data path documentation is missing."))
        if not (root / "src" / "orderflow_edge_lab" / "mexc_orderflow.py").exists():
            findings.append(Finding("error", "mexc_adapter_missing", "MEXC order-flow adapter is missing."))

    elif spec.agent_id == "research_validity":
        checks.extend(["trial_ledger_promotion_binding", "holdout_binding"])
        promotion = _read_text(root / "src" / "orderflow_edge_lab" / "promotion.py").lower()
        promote_cli = _read_text(root / "src" / "orderflow_edge_lab" / "cli" / "promote.py").lower()
        combined = promotion + "\n" + promote_cli
        if "trial_ledger" not in combined and "trial-ledger" not in combined:
            findings.append(
                Finding(
                    "warning",
                    "trial_ledger_not_bound_to_promotion",
                    "Trial accounting exists but is not visibly mandatory at the promotion boundary.",
                )
            )
        if "holdout" not in combined:
            findings.append(Finding("error", "holdout_not_bound_to_promotion", "Promotion boundary does not visibly reference holdout evidence."))

    elif spec.agent_id == "strategy_validation":
        checks.extend(["cost_model_presence", "oos_language_presence"])
        validation = _read_text(root / "src" / "orderflow_edge_lab" / "validation.py").lower()
        economics = _read_text(root / "src" / "orderflow_edge_lab" / "economics.py").lower()
        if not any(token in economics for token in ("fee", "slippage", "spread", "cost")):
            findings.append(Finding("error", "economics_model_incomplete", "Economics module does not visibly model trading costs."))
        if not any(token in validation for token in ("holdout", "out_of_sample", "out-of-sample")):
            findings.append(Finding("warning", "oos_guard_not_visible", "Validation module does not visibly reference out-of-sample or holdout evidence."))

    elif spec.agent_id == "execution_safety":
        checks.extend(["live_dependency_scan", "approval_boundary_presence"])
        pyproject = _read_text(root / "pyproject.toml").lower()
        broker_deps = [name for name in ("ccxt", "metatrader5", "ib_insync", "alpaca-py") if name in pyproject]
        if broker_deps:
            findings.append(Finding("error", "live_broker_dependency_present", "Live broker/exchange dependency detected.", {"dependencies": broker_deps}))
        execution = _read_text(root / "src" / "orderflow_edge_lab" / "execution.py").lower()
        if "approval" not in execution:
            findings.append(Finding("error", "approval_boundary_missing", "Execution module does not visibly preserve an approval boundary."))

    elif spec.agent_id == "reliability_ci":
        checks.append("ci_workflow_presence")
        if run_commands:
            checks.extend(["compileall", "unittest", "deployment_check"])
            findings.append(_run_command(root, [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"]))
            findings.append(_run_command(root, [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]))
            findings.append(_run_command(root, [sys.executable, "scripts/deployment_check.py"]))
        else:
            findings.append(Finding("info", "heavy_checks_skipped", "Reliability commands were skipped for this run."))

    elif spec.agent_id == "observability_deployment":
        checks.extend(["runtime_identity", "deployment_docs", "hash_evidence"])
        runtime_identity = _read_text(root / "src" / "orderflow_edge_lab" / "runtime_identity.py").lower()
        if "sha256" not in runtime_identity:
            findings.append(Finding("warning", "runtime_identity_not_hashed", "Runtime identity does not visibly contain SHA-256 evidence."))

    elif spec.agent_id == "adversarial_reviewer":
        checks.extend(["safety_boundary", "dependency_challenge", "fail_closed_language"])
        readme = _read_text(root / "README.md").lower()
        if "does not contain live broker or exchange order transmission" not in readme:
            findings.append(Finding("error", "live_boundary_not_explicit", "README no longer explicitly excludes live order transmission."))
        if "out-of-sample" not in readme:
            findings.append(Finding("warning", "oos_boundary_not_explicit", "README does not explicitly require out-of-sample evidence."))

    return findings, checks


def _status(findings: list[Finding]) -> str:
    severities = {finding.severity for finding in findings}
    if "critical" in severities or "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def run_agent(root: Path, spec: AgentSpec, run_commands: bool = True) -> AgentResult:
    findings, checks = _required_path_findings(root, spec)
    extra, extra_checks = _claim_findings(root, spec)
    findings.extend(extra)
    checks.extend(extra_checks)
    extra, extra_checks = _domain_findings(root, spec, run_commands)
    findings.extend(extra)
    checks.extend(extra_checks)
    return AgentResult(spec.agent_id, spec.focus, _status(findings), findings, checks)


def run_multi_agent(
    root: str | Path = ".",
    config: str | Path = "config/multi_agents.json",
    *,
    run_commands: bool = True,
    max_workers: int = 7,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    config_path = Path(config)
    if not config_path.is_absolute():
        config_path = root_path / config_path
    specs, release_policy = _load_specs(config_path)

    results: list[AgentResult] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(specs)))) as pool:
        futures = {pool.submit(run_agent, root_path, spec, run_commands): spec.agent_id for spec in specs}
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item.agent_id)

    required = set(str(value) for value in release_policy.get("require_agents", []))
    seen = {result.agent_id for result in results}
    missing_agents = sorted(required - seen)
    blocking_status = any(result.status == "failed" for result in results) or bool(missing_agents)
    warning_count = sum(1 for result in results for finding in result.findings if finding.severity == "warning")
    error_count = sum(1 for result in results for finding in result.findings if finding.severity in {"critical", "error"})

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "agents": [
            {
                "agent_id": result.agent_id,
                "focus": result.focus,
                "status": result.status,
                "checks_run": result.checks_run,
                "findings": [asdict(finding) for finding in result.findings],
            }
            for result in results
        ],
        "release_manager": {
            "status": "blocked" if blocking_status else "reviewable",
            "missing_agents": missing_agents,
            "error_count": error_count,
            "warning_count": warning_count,
            "next_actions": [
                asdict(finding)
                for result in results
                for finding in result.findings
                if finding.severity in {"critical", "error", "warning"}
            ],
            "live_order_transmission_supported": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
        },
    }
    report["manifest_sha256"] = _canonical_sha256(report)
    return report


def verify_report(report: dict[str, Any]) -> bool:
    stored = report.get("manifest_sha256")
    if not isinstance(stored, str):
        return False
    payload = dict(report)
    payload.pop("manifest_sha256", None)
    return stored == _canonical_sha256(payload)

"""Opt-in v2 engineering governance contracts.

This module is deliberately local and read-only.  It validates prospective
engineering configuration and repository evidence; it does not collect market
data, start watches, use credentials, assert durable storage, or authorize
promotion or order transmission.  Legacy v1 multi-agent and control-plane
surfaces remain untouched.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
import json
import re

from orderflow_edge_lab.contracts_v2 import (
    ContractValidationError,
    canonical_json_sha256,
    non_authority_claims,
    validate_non_authority_claims,
)
from orderflow_edge_lab.research_control_plane import (
    ResearchControlPlaneError,
    build_control_plane_status,
)

CONFIG_SCHEMA = "orderflow_edge_lab.multi_agent_policy.v2"
PROFILE_SCHEMA = "orderflow_edge_lab.release_profile.v2"
CONTROL_CONTRACT_SCHEMA = "orderflow_edge_lab.research_control_plane_contract.v2"
CONTROL_STATUS_SCHEMA = "orderflow_edge_lab.research_control_plane_status.v2"
MAP_SCHEMA = "orderflow_edge_lab.governance_map.v2"
SEVERITIES = frozenset({"info", "warning", "error", "critical"})
PROFILES = frozenset({"advisory", "release"})
CHECK_KINDS = frozenset({"path_exists", "path_contains", "json_false_claims", "dependency_absent", "text_absent"})
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_\-]*$")


class GovernanceV2Error(ValueError):
    """A deterministic, stable-code error for prospective governance inputs."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


def _fail(code: str, message: str) -> None:
    raise GovernanceV2Error(code, message)


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _fail("invalid_object", f"{field} must be an object with string keys")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_string", f"{field} must be a nonempty string")
    return value.strip()


def _identifier(value: object, field: str) -> str:
    result = _string(value, field)
    if not _IDENTIFIER.fullmatch(result):
        _fail("invalid_identifier", f"{field} must be lowercase identifier text")
    return result


def _relative_path(value: object, field: str) -> str:
    result = _string(value, field)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts or result.startswith("~"):
        _fail("unsafe_relative_path", f"{field} must be a repository-relative path without traversal")
    return result


def _string_list(value: object, field: str, *, unique: bool = False) -> list[str]:
    if not isinstance(value, list):
        _fail("invalid_list", f"{field} must be a list")
    result = [_string(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if unique and len(result) != len(set(result)):
        _fail("duplicate_value", f"{field} values must be unique")
    return result


def _canonical_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))


def _validate_check(raw: object, field: str) -> dict[str, Any]:
    item = _object(raw, field)
    allowed = {"id", "kind", "severity", "release_only", "paths", "tokens", "claims", "dependencies"}
    unknown = sorted(set(item) - allowed)
    if unknown:
        _fail("unknown_check_field", f"{field} has unknown fields: {','.join(unknown)}")
    check_id = _identifier(item.get("id"), f"{field}.id")
    kind = _string(item.get("kind"), f"{field}.kind")
    if kind not in CHECK_KINDS:
        _fail("unknown_check_kind", f"{field}.kind is unsupported: {kind}")
    severity = _string(item.get("severity", "error"), f"{field}.severity")
    if severity not in SEVERITIES - {"info"}:
        _fail("unknown_severity", f"{field}.severity is unsupported: {severity}")
    release_only = item.get("release_only", False)
    if type(release_only) is not bool:
        _fail("invalid_boolean", f"{field}.release_only must be boolean")
    normalized: dict[str, Any] = {"id": check_id, "kind": kind, "severity": severity, "release_only": release_only}
    if kind in {"path_exists", "path_contains", "json_false_claims", "text_absent"}:
        paths = item.get("paths")
        if not isinstance(paths, list) or not paths:
            _fail("missing_check_paths", f"{field}.paths must be a nonempty list")
        normalized["paths"] = [_relative_path(path, f"{field}.paths[{index}]") for index, path in enumerate(paths)]
        if len(normalized["paths"]) != len(set(normalized["paths"])):
            _fail("duplicate_value", f"{field}.paths values must be unique")
    if kind in {"path_contains", "text_absent"}:
        tokens = _string_list(item.get("tokens"), f"{field}.tokens", unique=True)
        if not tokens:
            _fail("missing_check_tokens", f"{field}.tokens must be nonempty")
        normalized["tokens"] = tokens
    if kind == "json_false_claims":
        claims = _string_list(item.get("claims"), f"{field}.claims", unique=True)
        if not claims:
            _fail("missing_check_claims", f"{field}.claims must be nonempty")
        normalized["claims"] = claims
    if kind == "dependency_absent":
        dependencies = _string_list(item.get("dependencies"), f"{field}.dependencies", unique=True)
        if not dependencies:
            _fail("missing_check_dependencies", f"{field}.dependencies must be nonempty")
        normalized["dependencies"] = [item.lower() for item in dependencies]
    return normalized


def validate_policy_config(config: Mapping[str, Any], *, allow_legacy: bool = False) -> dict[str, Any]:
    """Strictly validate and normalize a prospective v2 multi-agent policy.

    ``allow_legacy`` only describes a v1 object as read-only historical input; it
    never makes it eligible for a v2 release profile.
    """
    raw = _object(config, "config")
    if raw.get("schema_version") == 1:
        if not allow_legacy:
            _fail("legacy_config_requires_explicit_mode", "v1 configuration is readable only with allow_legacy=True")
        return {"compatibility_mode": "legacy_read_only", "schema_version": 1, "config_sha256": canonical_json_sha256(raw)}
    expected = {"schema_version", "analysis", "config_id", "agents", "release_manager"}
    supplied_hash = raw.get("config_sha256")
    allowed = expected | {"config_sha256"}
    if set(raw) != expected and set(raw) != allowed:
        _fail("invalid_config_shape", f"config fields must be exactly: {','.join(sorted(expected))}")
    if raw.get("schema_version") != 2 or raw.get("analysis") != CONFIG_SCHEMA:
        _fail("unsupported_config_schema", "config must be multi-agent policy schema version 2")
    config_id = _identifier(raw.get("config_id"), "config.config_id")
    agents_raw = raw.get("agents")
    if not isinstance(agents_raw, list) or not agents_raw:
        _fail("invalid_agents", "config.agents must be a nonempty list")
    agents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(agents_raw):
        field = f"config.agents[{index}]"
        item = _object(entry, field)
        expected_agent = {"id", "focus", "logical_role", "required_paths", "forbidden_claims", "checks"}
        if set(item) != expected_agent:
            _fail("invalid_agent_shape", f"{field} must contain exactly the v2 agent fields")
        agent_id = _identifier(item.get("id"), f"{field}.id")
        if agent_id in seen_ids:
            _fail("duplicate_agent_id", f"agent id is duplicated: {agent_id}")
        seen_ids.add(agent_id)
        focus = _string(item.get("focus"), f"{field}.focus")
        logical_role = _string(item.get("logical_role"), f"{field}.logical_role")
        required_paths_raw = item.get("required_paths")
        if not isinstance(required_paths_raw, list) or not required_paths_raw:
            _fail("invalid_required_paths", f"{field}.required_paths must be a nonempty list")
        required_paths = [_relative_path(path, f"{field}.required_paths[{n}]") for n, path in enumerate(required_paths_raw)]
        if len(required_paths) != len(set(required_paths)):
            _fail("duplicate_value", f"{field}.required_paths values must be unique")
        forbidden_claims = _string_list(item.get("forbidden_claims"), f"{field}.forbidden_claims", unique=True)
        checks_raw = item.get("checks")
        if not isinstance(checks_raw, list) or not checks_raw:
            _fail("invalid_checks", f"{field}.checks must be a nonempty list")
        checks = [_validate_check(value, f"{field}.checks[{n}]") for n, value in enumerate(checks_raw)]
        check_ids = [check["id"] for check in checks]
        if len(check_ids) != len(set(check_ids)):
            _fail("duplicate_check_id", f"{field}.checks ids must be unique")
        if not any(check["kind"] == "path_exists" for check in checks):
            _fail("missing_path_invariant", f"{field} must declare a path_exists check")
        agents.append({"id": agent_id, "focus": focus, "logical_role": logical_role, "required_paths": required_paths,
                       "forbidden_claims": forbidden_claims, "checks": checks})
    manager = _object(raw.get("release_manager"), "config.release_manager")
    if set(manager) != {"block_on", "require_agents"}:
        _fail("invalid_release_manager", "release_manager must contain block_on and require_agents only")
    block_on = _string_list(manager.get("block_on"), "config.release_manager.block_on", unique=True)
    if not block_on or any(value not in SEVERITIES - {"info"} for value in block_on):
        _fail("unknown_severity", "release_manager.block_on must contain known blocking severities")
    require_agents = [_identifier(item, f"config.release_manager.require_agents[{i}]") for i, item in enumerate(
        _string_list(manager.get("require_agents"), "config.release_manager.require_agents", unique=True))]
    unknown_required = sorted(set(require_agents) - seen_ids)
    if unknown_required:
        _fail("unknown_required_agent", f"release_manager requires unknown agents: {','.join(unknown_required)}")
    if set(require_agents) != seen_ids:
        _fail("incomplete_required_agents", "release_manager.require_agents must name every configured v2 agent")
    normalized = {"schema_version": 2, "analysis": CONFIG_SCHEMA, "config_id": config_id, "agents": agents,
                  "release_manager": {"block_on": block_on, "require_agents": require_agents}}
    normalized["config_sha256"] = canonical_json_sha256(normalized)
    if supplied_hash is not None and supplied_hash != normalized["config_sha256"]:
        _fail("config_hash_mismatch", "supplied normalized config_sha256 does not match configuration")
    return normalized


def load_policy_config(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceV2Error("config_read_error", f"cannot read policy config: {path}") from exc
    return validate_policy_config(_object(value, "config"))


def evaluate_release_policy(findings: Sequence[Mapping[str, Any]], block_on: Sequence[str]) -> dict[str, Any]:
    """Evaluate declared severity policy without a duplicated hard-coded gate."""
    policy = set(block_on)
    if not policy or not policy <= SEVERITIES - {"info"}:
        _fail("unknown_severity", "block_on must contain known non-info severities")
    normalized: list[dict[str, Any]] = []
    for index, finding in enumerate(findings):
        item = _object(finding, f"findings[{index}]")
        severity = _string(item.get("severity"), f"findings[{index}].severity")
        if severity not in SEVERITIES:
            _fail("unknown_severity", f"findings[{index}].severity is unsupported")
        normalized.append(_canonical_copy(item))
    blocked = [item for item in normalized if item["severity"] in policy]
    return {"block_on": sorted(policy), "blocking_findings": blocked, "blocked": bool(blocked)}


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return ""


def _check(root: Path, check: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    kind = check["kind"]
    paths = [root / item for item in check.get("paths", [])]
    if kind == "path_exists":
        observed = {str(path.relative_to(root)): path.exists() for path in paths}
        return all(observed.values()), {"paths": observed}
    if kind == "path_contains":
        tokens = check["tokens"]
        observed = {str(path.relative_to(root)): {token: token.lower() in _safe_text(path) for token in tokens} for path in paths}
        return all(all(row.values()) for row in observed.values()), {"tokens": observed}
    if kind == "text_absent":
        tokens = check["tokens"]
        observed = {str(path.relative_to(root)): {token: token.lower() not in _safe_text(path) for token in tokens} for path in paths}
        return all(all(row.values()) for row in observed.values()), {"tokens_absent": observed}
    if kind == "json_false_claims":
        observed: dict[str, Any] = {}
        passed = True
        for path in paths:
            name = str(path.relative_to(root))
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                claims = value.get("claims", {}) if isinstance(value, Mapping) else {}
                row = {claim: claims.get(claim) is False for claim in check["claims"]}
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                row = {claim: False for claim in check["claims"]}
            observed[name] = row
            passed = passed and all(row.values())
        return passed, {"claims_false": observed}
    if kind == "dependency_absent":
        pyproject = _safe_text(root / "pyproject.toml")
        observed = {name: name in pyproject for name in check["dependencies"]}
        return not any(observed.values()), {"forbidden_dependencies_present": observed}
    raise AssertionError(f"validated check kind missing runner: {kind}")


def build_release_profile_v2(
    root: str | Path,
    config: Mapping[str, Any],
    *,
    profile: str = "release",
) -> dict[str, Any]:
    """Run a deterministic, repository-local governance profile.

    Advisory output is hash-verifiable but deliberately cannot be release
    reviewable.  A release profile executes every named v2 check exactly once.
    """
    if profile not in PROFILES:
        _fail("unknown_profile", "profile must be advisory or release")
    normalized = validate_policy_config(config)
    root_path = Path(root).resolve()
    executions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    required_checks: list[str] = []
    for agent in normalized["agents"]:
        for check in agent["checks"]:
            full_id = f"{agent['id']}:{check['id']}"
            required_checks.append(full_id)
            if profile == "advisory" and check["release_only"]:
                executions.append({"check_id": full_id, "agent_id": agent["id"], "status": "SKIPPED",
                                   "reason": "advisory_profile", "evidence": None, "evidence_sha256": None})
                continue
            passed, evidence = _check(root_path, check)
            evidence_sha256 = canonical_json_sha256(evidence)
            executions.append({"check_id": full_id, "agent_id": agent["id"], "status": "PASSED" if passed else "FAILED",
                               "reason": None, "evidence": evidence, "evidence_sha256": evidence_sha256})
            if not passed:
                findings.append({"severity": check["severity"], "code": "governance_check_failed", "agent_id": agent["id"],
                                 "check_id": full_id, "message": f"required deterministic check failed: {full_id}",
                                 "evidence_sha256": evidence_sha256})
        if agent["forbidden_claims"]:
            scan = {phrase: [] for phrase in agent["forbidden_claims"]}
            for location in (root_path / "README.md", root_path / "docs", root_path / "src" / "orderflow_edge_lab"):
                candidates = [location] if location.is_file() else list(location.rglob("*.py")) + list(location.rglob("*.md")) if location.exists() else []
                for candidate in candidates:
                    text = _safe_text(candidate)
                    for phrase in scan:
                        if phrase.lower() in text:
                            scan[phrase].append(str(candidate.relative_to(root_path)))
            scan = {key: sorted(value) for key, value in scan.items()}
            evidence_sha256 = canonical_json_sha256(scan)
            full_id = f"{agent['id']}:forbidden_claim_scan"
            required_checks.append(full_id)
            passed = not any(scan.values())
            executions.append({"check_id": full_id, "agent_id": agent["id"], "status": "PASSED" if passed else "FAILED",
                               "reason": None, "evidence": {"matches": scan}, "evidence_sha256": evidence_sha256})
            if not passed:
                findings.append({"severity": "warning", "code": "forbidden_claim_phrase", "agent_id": agent["id"],
                                 "check_id": full_id, "message": "configured unsupported claim phrase found", "evidence_sha256": evidence_sha256})
    executed = [item["check_id"] for item in executions if item["status"] != "SKIPPED"]
    skipped = [item["check_id"] for item in executions if item["status"] == "SKIPPED"]
    if len(required_checks) != len(set(required_checks)) or len(executed) != len(set(executed)):
        _fail("duplicate_runtime_check", "configured checks must be globally unique")
    policy = evaluate_release_policy(findings, normalized["release_manager"]["block_on"])
    failed = [item["check_id"] for item in executions if item["status"] == "FAILED"]
    release_eligible = profile == "release" and not skipped and not failed and not policy["blocked"]
    agents = [{"agent_id": agent["id"], "focus": agent["focus"], "logical_role": agent["logical_role"],
               "status": "failed" if any(item["agent_id"] == agent["id"] and item["status"] == "FAILED" for item in executions) else "passed"}
              for agent in normalized["agents"]]
    unsigned = {
        "schema": PROFILE_SCHEMA, "analysis": "multi_agent_release_profile_v2", "execution_profile": profile,
        "config_id": normalized["config_id"], "config_schema_version": 2, "config_sha256": normalized["config_sha256"],
        "required_checks": required_checks, "checks_executed": executed, "checks_skipped": skipped,
        "checks_skipped_required": len(skipped), "checks": executions, "agents": agents, "findings": findings,
        "release_manager": {"status": "reviewable" if release_eligible else ("not_release_eligible" if profile == "advisory" else "blocked"),
                            "block_on": policy["block_on"], "blocking_findings": policy["blocking_findings"],
                            "failed_required_checks": failed, "missing_required_checks": sorted(set(required_checks) - set(executed) - set(skipped)),
                            "release_eligible": release_eligible},
        "non_authority_claims": non_authority_claims(),
        "activation_blockers": ["Durable external storage is not verified by local governance checks.",
                                "Independent engine calibration is not verified by local governance checks.",
                                "Risk and scientific policy parameters require caller-declared frozen successor policies."],
    }
    return {**unsigned, "report_sha256": canonical_json_sha256(unsigned)}


def verify_release_profile_v2(report: Mapping[str, Any]) -> bool:
    try:
        raw = _object(report, "release_profile")
        stored = raw.get("report_sha256")
        if not isinstance(stored, str):
            return False
        unsigned = dict(raw)
        unsigned.pop("report_sha256", None)
        if raw.get("schema") != PROFILE_SCHEMA or raw.get("analysis") != "multi_agent_release_profile_v2":
            return False
        validate_non_authority_claims(raw.get("non_authority_claims"))
        return stored == canonical_json_sha256(unsigned)
    except (GovernanceV2Error, ContractValidationError, TypeError, ValueError):
        return False


def validate_control_plane_contract_v2(contract: Mapping[str, Any]) -> dict[str, Any]:
    raw = _object(contract, "control_plane_contract")
    required = {"schema_version", "analysis", "contract_id", "input_analysis", "stage_order", "required_authority_false", "required_operational_claims"}
    supplied_hash = raw.get("contract_sha256")
    if set(raw) != required and set(raw) != required | {"contract_sha256"}:
        _fail("invalid_control_contract_shape", "control-plane v2 contract has missing or extra fields")
    if raw.get("schema_version") != 2 or raw.get("analysis") != CONTROL_CONTRACT_SCHEMA:
        _fail("unsupported_control_contract", "control-plane contract must be v2")
    input_analysis = _object(raw.get("input_analysis"), "control_plane_contract.input_analysis")
    expected_inputs = {"shadow", "decision", "action", "operational"}
    if set(input_analysis) != expected_inputs:
        _fail("invalid_control_inputs", "contract must declare exactly four named inputs")
    normalized_inputs = {name: _string(input_analysis[name], f"input_analysis.{name}") for name in sorted(expected_inputs)}
    stage_order = _string_list(raw.get("stage_order"), "control_plane_contract.stage_order", unique=True)
    expected_stages = {"PRE_START", "WAITING_FOR_FIRST_POST_START_CHANGE", "WAITING_FOR_COMPLETIONS", "ACCUMULATING_COMPLETED_EVIDENCE", "READY_FOR_REVIEW", "HALTED_PROTOCOL_BREACH"}
    if set(stage_order) != expected_stages:
        _fail("invalid_control_stages", "contract stage_order must include every computed v1 stage exactly once")
    authority = _string_list(raw.get("required_authority_false"), "control_plane_contract.required_authority_false", unique=True)
    if not authority:
        _fail("invalid_control_authority", "contract requires nonempty all-false authority claims")
    operational_claims = _string_list(raw.get("required_operational_claims"), "control_plane_contract.required_operational_claims", unique=True)
    if not operational_claims:
        _fail("invalid_operational_claims", "contract requires nonempty operational claim list")
    normalized = {"schema_version": 2, "analysis": CONTROL_CONTRACT_SCHEMA,
                  "contract_id": _identifier(raw.get("contract_id"), "control_plane_contract.contract_id"),
                  "input_analysis": normalized_inputs, "stage_order": stage_order,
                  "required_authority_false": authority, "required_operational_claims": operational_claims}
    normalized["contract_sha256"] = canonical_json_sha256(normalized)
    if supplied_hash is not None and supplied_hash != normalized["contract_sha256"]:
        _fail("contract_hash_mismatch", "supplied normalized contract_sha256 does not match contract")
    return normalized


def load_control_plane_contract_v2(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceV2Error("contract_read_error", f"cannot read control-plane contract: {path}") from exc
    return validate_control_plane_contract_v2(_object(value, "control_plane_contract"))


def build_control_plane_status_v2(
    shadow: Mapping[str, Any], decision: Mapping[str, Any], action: Mapping[str, Any], operational: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Compose a v2 provenance-bound read-only control-plane status.

    The stage calculation deliberately delegates to the preserved v1 pure logic
    after the separately declared v2 contract has validated its boundary.
    """
    normalized = validate_control_plane_contract_v2(contract)
    supplied = {"shadow": shadow, "decision": decision, "action": action, "operational": operational}
    for name, report in supplied.items():
        if _object(report, name).get("analysis") != normalized["input_analysis"][name]:
            _fail("input_analysis_mismatch", f"{name} analysis does not match contract")
    authority = _object(action.get("authority_boundary"), "action.authority_boundary")
    for claim in normalized["required_authority_false"]:
        if authority.get(claim) is not False:
            _fail("authority_boundary_violated", f"action authority claim must be false: {claim}")
    op_claims = _object(operational.get("claims"), "operational.claims")
    for claim in normalized["required_operational_claims"]:
        if op_claims.get(claim) is not True:
            _fail("operational_claim_missing", f"operational claim must be true: {claim}")
    try:
        legacy_status = build_control_plane_status(shadow, decision, action, operational)
    except ResearchControlPlaneError as exc:
        raise GovernanceV2Error("legacy_semantic_validation_failed", str(exc)) from exc
    if legacy_status["stage"] not in normalized["stage_order"]:
        _fail("computed_stage_not_declared", "computed stage is not declared in the v2 contract")
    unsigned = {
        "schema": CONTROL_STATUS_SCHEMA, "analysis": "research_control_plane_status_v2", "contract_id": normalized["contract_id"],
        "contract_schema_version": 2, "contract_sha256": normalized["contract_sha256"],
        "input_sha256": {name: canonical_json_sha256(supplied[name]) for name in sorted(supplied)},
        "status": legacy_status,
        "non_authority_claims": non_authority_claims(),
        "verification_scope": "local_canonical_json_and_declared_contract_only",
        "activation_blockers": ["No external durable-storage verification is performed.", "No provider completeness or independent-engine calibration is established.", "This read-only status does not authorize promotion, leverage, or live execution."],
    }
    return {**unsigned, "report_sha256": canonical_json_sha256(unsigned)}


def verify_control_plane_status_v2(report: Mapping[str, Any]) -> bool:
    try:
        raw = _object(report, "control_plane_status")
        if raw.get("schema") != CONTROL_STATUS_SCHEMA or not isinstance(raw.get("report_sha256"), str):
            return False
        validate_non_authority_claims(raw.get("non_authority_claims"))
        unsigned = dict(raw)
        stored = unsigned.pop("report_sha256")
        return stored == canonical_json_sha256(unsigned)
    except (GovernanceV2Error, ContractValidationError, TypeError, ValueError):
        return False


def build_governance_map_v2(config: Mapping[str, Any]) -> dict[str, Any]:
    """Generate the single governance-map payload from the validated v2 registry."""
    normalized = validate_policy_config(config)
    deterministic = [{"agent_id": agent["id"], "focus": agent["focus"], "logical_role": agent["logical_role"],
                      "deterministic_repository_evidence": True} for agent in normalized["agents"]]
    unsigned = {"schema": MAP_SCHEMA, "analysis": "governance_map_v2", "config_id": normalized["config_id"],
                "config_sha256": normalized["config_sha256"], "deterministic_agent_count": len(deterministic),
                "deterministic_agents": deterministic,
                "optional_coordination": {"deerflow": "Logical role grouping only; it is not deterministic repository evidence.",
                                          "ruflo": "Optional coordination only; it is not deterministic repository evidence."},
                "lead_release_manager": "Adversarial synthesis and release manager; repository evidence, not coordination voting, governs release."}
    return {**unsigned, "map_sha256": canonical_json_sha256(unsigned)}


def render_governance_map_markdown(governance_map: Mapping[str, Any]) -> str:
    raw = _object(governance_map, "governance_map")
    lines = ["# Governance Map v2", "", "This generated prospective map is sourced from `config/multi_agents_v2.json`. It does not alter historical v1 reports or research evidence.", "",
             f"- **Deterministic checker count:** {raw['deterministic_agent_count']}", f"- **Registry SHA-256:** `{raw['config_sha256']}`", f"- **Map SHA-256:** `{raw['map_sha256']}`", "",
             "| Deterministic agent ID | Logical compatibility role | Repository evidence |", "| --- | --- | --- |"]
    for agent in raw["deterministic_agents"]:
        lines.append(f"| `{agent['agent_id']}` | {agent['logical_role']} | deterministic local check evidence |")
    lines += ["", "## Coordination boundary", "", "DeerFlow and Ruflo labels are logical orchestration groupings only. They do not equal the deterministic checker count, do not bootstrap services, and do not substitute for repository test or governance evidence.", "", "## Lead / release manager", "", str(raw["lead_release_manager"]), ""]
    return "\n".join(lines)

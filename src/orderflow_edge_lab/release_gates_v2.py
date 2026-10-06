"""Non-optional offline engineering gates; no market-data or trading side effects.

A passed gate is local code-review evidence only. It does not supply durable
external append concurrency, vendor rights, independent calibration or policy.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from orderflow_edge_lab.contracts_v2 import build_file_identity

BASE_COMMIT = "cc2582f5f9385b2bad4c7b5450b6e7257889ee6e"
PROTECTED_INVENTORY_SHA256 = "5ade0a1e729c4079612dbffd36552a918a8ffe594df6335ced2fe45da32aa8e6"
MANDATORY_RELEASE_GATES = (
    "protected_inventory_parity", "generated_map_parity", "complete_v2_suite", "isolated_install_console_smoke",
)


def protected_inventory_parity(root: Path) -> tuple[bool, dict[str, Any]]:
    root = root.resolve()
    inventory_path = root / "config/protected_inventory_v2.json"
    try:
        if not inventory_path.resolve().is_relative_to(root):
            return False, {"error": "inventory_path_escape"}
        inventory_bytes = inventory_path.read_bytes()
        digest = hashlib.sha256(inventory_bytes).hexdigest()
        if digest != PROTECTED_INVENTORY_SHA256:
            return False, {"error": "protected_inventory_identity_mismatch", "observed_sha256": digest,
                           "required_sha256": PROTECTED_INVENTORY_SHA256}
        inventory = json.loads(inventory_bytes)
        if inventory["base_commit"] != BASE_COMMIT:
            return False, {"error": "protected_base_mismatch"}
        rows = [row for key in ("config_files", "research_files", "preexisting_package_module_files") for row in inventory[key]]
        if len(rows) != 535 or len({row["path"] for row in rows}) != len(rows):
            return False, {"error": "protected_inventory_count_or_duplicate"}
        mismatches = []
        for row in rows:
            path = root / row["path"]
            if not path.resolve().is_relative_to(root) or not path.is_file():
                mismatches.append({"path": row["path"], "error": "missing_or_unsafe_protected_file"})
                continue
            raw = path.read_bytes()
            observed = hashlib.sha256(raw).hexdigest()
            if observed != row["sha256_raw_bytes"] or len(raw) != row["size_bytes"]:
                mismatches.append({"path": row["path"], "observed_sha256": observed, "observed_size_bytes": len(raw),
                                   "expected_sha256": row["sha256_raw_bytes"], "expected_size_bytes": row["size_bytes"]})
        return not mismatches, {"base_commit": BASE_COMMIT, "inventory_sha256": digest,
                                "files_checked": len(rows), "files_matching": len(rows)-len(mismatches), "mismatches": mismatches}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, {"error": "protected_inventory_unreadable", "error_type": type(exc).__name__}


def generated_map_parity(root: Path, config: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    from orderflow_edge_lab.governance_v2 import (
        build_governance_map_v2, load_policy_config, render_governance_map_markdown, validate_policy_config,
    )
    paths = [root / name for name in ("config/multi_agents_v2.json", "docs/governance_map_v2.json", "docs/GOVERNANCE_MAP_V2.md")]
    try:
        if any(not path.resolve().is_relative_to(root) for path in paths):
            return False, {"error": "generated_map_path_escape"}
        actual_config = load_policy_config(paths[0])
        expected = build_governance_map_v2(actual_config)
        matches = {"requested_config_matches_checkout": validate_policy_config(config) == actual_config,
                   "json_map_matches": json.loads(paths[1].read_text(encoding="utf-8")) == expected,
                   "markdown_map_matches": paths[2].read_text(encoding="utf-8") == render_governance_map_markdown(expected)}
        return all(matches.values()), {"parity": matches, "config_sha256": actual_config["config_sha256"],
                                      "map_sha256": expected["map_sha256"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, {"error": "generated_map_unreadable", "error_type": type(exc).__name__}


def _command(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[bool, dict[str, Any]]:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        text = result.stdout + result.stderr
        passed = result.returncode == 0
        # unittest execution time and random temporary paths are not identities.
        normalized = re.sub(r"Ran (\d+) tests? in [0-9.]+s", r"Ran \1 tests", text)
        normalized = re.sub(r"/tmp/(?:tmp|orderflow-v2-install-|orderflow-smoke-|pip-ephem-wheel-cache-)[A-Za-z0-9_\-/\.]+", "{TEMP}", normalized)
        return passed, {"exit_code": result.returncode, "output_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
                        "output_tail": normalized[-6000:], "tests_run": int(re.search(r"Ran (\d+) tests?", text).group(1)) if re.search(r"Ran (\d+) tests?", text) else 0}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": type(exc).__name__, "tests_run": 0}


def complete_v2_suite(root: Path) -> tuple[bool, dict[str, Any]]:
    """Discover every authored v2 test AND the mandatory foundational contract."""
    paths = sorted((root / "tests").glob("test_v2_*.py"))
    foundation = root / "tests/test_contracts_v2.py"
    foundation_present = foundation.is_file()
    if foundation_present:
        paths = sorted([*paths, foundation])
    if not paths or any(not path.resolve().is_relative_to(root) for path in paths):
        return False, {"error": "v2_tests_missing_or_unsafe", "tests_run": 0}
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)])}
    # The baseline uses a namespace tests directory, not an __init__.py package.
    # Enumerate ALL glob results rather than relying on -t package discovery or
    # caller-selected classes, which could omit authored regression modules.
    command = [sys.executable, "-m", "unittest", "-v", *["tests."+path.stem for path in paths]]
    passed, evidence = _command(command, cwd=root, env=env, timeout=300)
    return passed and evidence["tests_run"] > 0 and foundation_present, {**evidence,
                                                "discovery_pattern": "test_v2_*.py + test_contracts_v2.py",
                                                "foundational_contract_tests_present": foundation_present,
                                                "test_identities": [build_file_identity(path, logical_name=path.relative_to(root).as_posix()) for path in paths]}


def isolated_install_console_smoke(root: Path) -> tuple[bool, dict[str, Any]]:
    """Build/install without indexes and probe actual installed console scripts."""
    required = [root / name for name in ("pyproject.toml", "src/orderflow_edge_lab", "scripts/package_smoke.py")]
    if any(not path.exists() or not path.resolve().is_relative_to(root) for path in required):
        return False, {"error": "packaging_inputs_missing_or_unsafe"}
    # Refuse escaped symlinks before copy; do not copy research/data/holdouts.
    if any(path.is_symlink() for path in required[1].rglob("*")):
        return False, {"error": "package_source_symlink"}
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "", "PIP_NO_INDEX": "1",
           "PIP_DISABLE_PIP_VERSION_CHECK": "1", "SOURCE_DATE_EPOCH": "1791276329"}
    with tempfile.TemporaryDirectory(prefix="orderflow-v2-install-") as temp:
        stage = Path(temp) / "build"
        stage.mkdir()
        shutil.copy2(required[0], stage / "pyproject.toml")
        shutil.copytree(required[1], stage / "src/orderflow_edge_lab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wheels = Path(temp) / "wheels"
        passed, build = _command([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps", "--no-build-isolation",
                                  "--wheel-dir", str(wheels), str(stage)], cwd=Path(temp), env=env, timeout=120)
        candidates = list(wheels.glob("*.whl"))
        if not passed or len(candidates) != 1:
            return False, {"error": "isolated_wheel_build_failed", "build": build}
        passed, smoke = _command([sys.executable, str(required[2]), str(candidates[0])], cwd=Path(temp), env=env, timeout=300)
        return passed, {"verification_scope": "fresh_installed_package_and_actual_console_help_only_shared_dependency_runtime",
                        "wheel_identity": build_file_identity(candidates[0], logical_name=candidates[0].name),
                        "build": build, "smoke": smoke}


def run_mandatory_release_gate(root: Path, gate: str, config: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    if gate == "protected_inventory_parity":
        return protected_inventory_parity(root)
    if gate == "generated_map_parity":
        return generated_map_parity(root, config)
    if gate == "complete_v2_suite":
        return complete_v2_suite(root)
    if gate == "isolated_install_console_smoke":
        return isolated_install_console_smoke(root)
    raise ValueError(f"unknown mandatory release gate: {gate}")

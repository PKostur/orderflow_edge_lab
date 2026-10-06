"""Fast offline contracts; heavy native installs belong to CI/manual verifier."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from orderflow_edge_lab.release_gates_v2 import complete_v2_suite, protected_inventory_parity

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / "requirements/locks"
SPEC = importlib.util.spec_from_file_location("packaging_verifier", ROOT / "scripts/verify_packaging.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class PackagingProofContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((LOCKS / "artifacts.json").read_text(encoding="utf-8"))

    def test_exact_supported_matrix_and_fail_closed_target_selection(self):
        expected = {"py310-manylinux-x86_64", "py311-manylinux-x86_64", "py312-manylinux-x86_64", "py312-win-amd64"}
        self.assertEqual(set(self.manifest["targets"]), expected)
        for name, target in self.manifest["targets"].items():
            identity = {key: target[key] for key in ("python", "sys_platform", "machine", "implementation")}
            self.assertEqual(VERIFIER.select_target(self.manifest, identity)[0], name)
            for key, invalid in [("python", "3.13"), ("machine", "aarch64"), ("implementation", "PyPy"), ("sys_platform", "darwin")]:
                wrong = {**identity, key: invalid}
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    VERIFIER.select_target(self.manifest, wrong)

    def test_exact_hashes_markers_and_authentic_artifact_identity_contract(self):
        for name, target in self.manifest["targets"].items():
            for kind, filename in target["locks"].items():
                lines = [line for line in (LOCKS / filename).read_text().splitlines() if line and not line.startswith("#")]
                rows = [row for row in target["artifacts"] if row["kind"] == kind]
                self.assertEqual(len(lines), len(rows), name)
                for line, row in zip(lines, rows):
                    text, digest = line.split(" --hash=sha256:")
                    requirement = Requirement(text)
                    self.assertEqual(canonicalize_name(requirement.name), canonicalize_name(row["name"]))
                    self.assertEqual(str(requirement.specifier), "==" + row["version"])
                    self.assertRegex(digest, r"^[a-f0-9]{64}$")
                    self.assertEqual(digest, row["sha256"])
                    self.assertGreater(row["size_bytes"], 0)
                    self.assertTrue(row["url"].startswith("https://files.pythonhosted.org/"))
                    self.assertEqual(row["url"].split("/")[-1], row["filename"])
                    marker = str(requirement.marker)
                    self.assertIn(f'python_version == "{target["python"]}"', marker)
                    self.assertIn(f'sys_platform == "{target["sys_platform"]}"', marker)
                    self.assertIn(f'platform_machine == "{target["machine"]}"', marker)
                    self.assertIn('platform_python_implementation == "CPython"', marker)

    def test_complete_reviewed_dependency_metadata_closure_and_baseline_pins(self):
        for name, target in self.manifest["targets"].items():
            environment = {"python_version": target["python"], "python_full_version": target["python"] + ".10",
                           "sys_platform": target["sys_platform"], "platform_machine": target["machine"],
                           "os_name": "nt" if target["sys_platform"] == "win32" else "posix",
                           "platform_python_implementation": "CPython", "extra": ""}
            versions = {canonicalize_name(row["name"]): row["version"] for row in target["artifacts"]}
            for row in target["artifacts"]:
                for text in row.get("requires_dist", []):
                    requirement = Requirement(text)
                    if requirement.marker and not requirement.marker.evaluate(environment):
                        continue
                    dependency = canonicalize_name(requirement.name)
                    self.assertIn(dependency, versions, (name, row["name"], text))
                    self.assertIn(versions[dependency], requirement.specifier, (name, row["name"], text))
            for line in (ROOT / "requirements/constraints.txt").read_text().splitlines():
                if not line or line.startswith("#"):
                    continue
                requirement = Requirement(line)
                if canonicalize_name(requirement.name) == "ruff":
                    continue  # dev-only lint, not research artifact runtime
                if not requirement.marker or requirement.marker.evaluate(environment):
                    self.assertIn(versions[canonicalize_name(requirement.name)], requirement.specifier)
            self.assertEqual(versions["setuptools"], "80.9.0")
            self.assertEqual(versions["wheel"], "0.45.1")
            self.assertEqual(versions["cloudpickle"], "3.1.2")
            if target["python"] != "3.10":
                self.assertEqual(versions["narwhals"], "2.26.0")

    def test_ci_gate_has_clean_wheel_and_sdist_and_explicit_build_tools(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn('python-version: "3.12"', ci)
        self.assertIn("windows-latest", ci)
        self.assertIn("scripts/verify_packaging.py", ci)
        self.assertIn("requirements/locks/build-ci.txt", ci)
        self.assertIn("requirements/locks/research-ci.txt", ci)
        hardening = (ROOT / ".github/workflows/multi-agent-hardening.yml").read_text()
        self.assertIn("py312-manylinux-x86_64-build.txt", hardening)
        self.assertIn("--require-hashes", hardening)
        self.assertNotIn("schedule:", hardening)
        verifier = (ROOT / "scripts/verify_packaging.py").read_text()
        self.assertIn('system_site_packages=False', verifier)
        self.assertIn('"--no-build-isolation"', verifier)
        self.assertIn('"--require-hashes"', verifier)
        self.assertNotIn('"--no-deps"', verifier)
        self.assertIn('("sdist", sources[0])', verifier)

    def test_probe_environment_removes_checkout_fallbacks(self):
        with patch.dict("os.environ", {"PYTHONPATH": "unsafe-source", "PYTHONHOME": "unsafe-host", "VIRTUAL_ENV": "shared"}):
            environment = VERIFIER.isolated_env()
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("VIRTUAL_ENV", environment)
        self.assertEqual(environment["PIP_NO_INDEX"], "1")

    def test_foundational_contract_failure_really_blocks_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tests").mkdir()
            (root / "tests/__init__.py").write_text("")
            (root / "tests/test_v2_fixture.py").write_text("import unittest\nclass V(unittest.TestCase):\n def test_ok(self): pass\n")
            (root / "tests/test_contracts_v2.py").write_text("import unittest\nclass F(unittest.TestCase):\n def test_foundation(self): self.fail('foundation must block')\n")
            passed, evidence = complete_v2_suite(root)
            self.assertFalse(passed)
            self.assertEqual(evidence["tests_run"], 2)
            self.assertTrue(evidence["foundational_contract_tests_present"])
            self.assertIn("foundation must block", evidence["output_tail"])
            self.assertIn("test_contracts_v2.py", " ".join(item["logical_name"] for item in evidence["test_identities"]))

    def test_deleted_foundation_cannot_pass_even_if_all_v2_tests_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tests").mkdir()
            (root / "tests/__init__.py").write_text("")
            (root / "tests/test_v2_fixture.py").write_text("import unittest\nclass V(unittest.TestCase):\n def test_ok(self): pass\n")
            passed, evidence = complete_v2_suite(root)
            self.assertFalse(passed)
            self.assertEqual(evidence["tests_run"], 1)
            self.assertFalse(evidence["foundational_contract_tests_present"])

    def test_all_535_protected_baseline_identities_still_match(self):
        passed, evidence = protected_inventory_parity(ROOT)
        self.assertTrue(passed, evidence)
        self.assertEqual(evidence["files_matching"], 535)


if __name__ == "__main__":
    unittest.main()

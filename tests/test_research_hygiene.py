import json
import shutil
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.cli.research_hygiene import build_parser, hygiene_markdown, main

REPO_ROOT = Path(__file__).resolve().parents[1]


def _arguments(root: Path) -> list[str]:
    return [
        "--repo-root",
        str(root),
        "--preregistration-registry",
        "config/preregistration_registry_v1.json",
        "--frozen-manifest",
        "config/frozen_manifest_v1.json",
        "--inspection-registry",
        "config/hypothesis_inspection_registry_v1.json",
        "--workflow-dir",
        ".github/workflows",
        "--retention-requirements",
        "config/evidence_retention_requirements_v1.json",
    ]


class ParserTests(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.repo_root, ".")
        self.assertEqual(args.fail_on, "error")


class RealRepositoryTests(unittest.TestCase):
    def test_hygiene_report_is_clean_on_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "hygiene.json"
            markdown = root / "hygiene.md"
            code = main([*_arguments(REPO_ROOT), "--output", str(output), "--markdown", str(markdown)])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["analysis"], "research_hygiene_report")
            self.assertTrue(report["hygiene_ok"], msg=json.dumps(report["findings"], indent=2))
            self.assertEqual(report["finding_counts"]["error"], 0)
            self.assertTrue(all(report["component_ok"].values()))
            self.assertGreater(report["finding_counts"]["warning"], 0)
            self.assertFalse(any(report["claims"].values()))
            text = markdown.read_text(encoding="utf-8")
            for heading in (
                "Pre-registration audit",
                "Frozen definition hash check",
                "Workflow to artifact contract",
                "Hypothesis inspection registry",
            ):
                self.assertIn(heading, text)

    def test_hygiene_markdown_contains_every_component(self):
        report = json.loads(
            json.dumps(
                {
                    "component_ok": {},
                    "finding_counts": {"info": 0, "warning": 0, "error": 0},
                    "hygiene_ok": True,
                    "highest_severity": "info",
                    "report_sha256": "0" * 64,
                    "components": {
                        "preregistration": {"watches": [], "findings": [], "registry_version": "v", "watches_total": 0, "compliant_count": 0, "acknowledged_gap_count": 0, "highest_severity": "info", "audit_ok": True},
                        "frozen_manifest": {"files": [], "findings": [], "manifest_version": "v", "manifest_recorded_at_utc": "t", "files_total": 0, "files_matching": 0, "files_changed": 0, "files_missing": 0, "verified": True, "highest_severity": "info"},
                        "workflow_contract": {"consumers": [], "requirements": [], "findings": [], "workflows_scanned": 0, "contract_ok": True, "highest_severity": "info"},
                        "inspection_registry": {"entries": [], "findings": [], "registry_version": "v", "entries_total": 0, "registered_count": 0, "terminal_count": 0, "registry_sha256_matches": True, "valid": True, "highest_severity": "info"},
                    },
                }
            )
        )
        text = hygiene_markdown(report)
        self.assertIn("Research hygiene report", text)


class BrokenRepositoryTests(unittest.TestCase):
    def _copy(self, root: Path) -> Path:
        for relative in (
            "config",
            ".github/workflows",
            "research",
            "STATUS.md",
        ):
            source = REPO_ROOT / relative
            if source.is_dir():
                shutil.copytree(source, root / relative)
            else:
                shutil.copy2(source, root / relative)
        return root

    def test_tampered_frozen_definition_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy(Path(directory))
            target = root / "config" / "orderflow_discovery_v1.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["silent_retune"] = True
            target.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual(main(_arguments(root)), 2)
            self.assertEqual(main([*_arguments(root), "--fail-on", "never"]), 0)

    def test_broken_inspection_registry_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy(Path(directory))
            registry = root / "config" / "hypothesis_inspection_registry_v1.json"
            payload = json.loads(registry.read_text(encoding="utf-8"))
            payload["registry_sha256"] = "0" * 64
            registry.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(main(_arguments(root)), 2)

    def test_warning_only_findings_do_not_fail_the_default_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._copy(Path(directory))
            # The repository's frozen-watch gaps are warnings by design.
            self.assertEqual(main(_arguments(root)), 0)
            self.assertEqual(main([*_arguments(root), "--fail-on", "warning"]), 2)


if __name__ == "__main__":
    unittest.main()

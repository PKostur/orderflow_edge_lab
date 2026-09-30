import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.workflow_contract import (
    audit_workflow_contract,
    matches,
    normalize_artifact_name,
    scan_workflow,
    workflow_contract_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

WORKFLOW = """\
name: Sample
on:
  schedule:
    - cron: '17 3 * * *'
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Produce
        uses: actions/upload-artifact@v4
        with:
          name: sample-report-${{ github.run_id }}
          path: artifacts/report.json
      - name: Consume
        uses: actions/download-artifact@v4
        with:
          pattern: sample-*
          path: artifacts/in
      - name: Fetch by name
        run: |
          gh run download 12345 -n sample-report
          gh api "repos/x/y/actions/artifacts?per_page=100" --jq '.artifacts | map(select(.name | startswith("sample-price-")))'
"""

NO_RUN_INLINE = """\
name: Inline
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/upload-artifact@v6
        with:
          name: inline-report
"""


class ScanTests(unittest.TestCase):
    def _write(self, root: Path, name: str, body: str) -> Path:
        path = root / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_scan_extracts_producers_consumers_and_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(Path(directory), "sample.yml", WORKFLOW)
            scan = scan_workflow(path)
            self.assertEqual(scan["name"], "Sample")
            self.assertEqual(scan["schedules"], ["17 3 * * *"])
            self.assertEqual(scan["uploads"], ["sample-report-${{ github.run_id }}"])
            kinds = {(entry["kind"], entry["value"]) for entry in scan["downloads"]}
            self.assertIn(("pattern", "sample-*"), kinds)
            self.assertIn(("shell_name", "sample-report"), kinds)
            self.assertIn(("shell_pattern", "sample-price-*"), kinds)
            self.assertTrue(scan["uses_artifact_rest_api"])

    def test_scan_handles_uses_inline_with_the_step_dash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(Path(directory), "inline.yml", NO_RUN_INLINE)
            scan = scan_workflow(path)
            self.assertEqual(scan["uploads"], ["inline-report"])
            self.assertEqual(scan["downloads"], [])
            self.assertFalse(scan["uses_artifact_rest_api"])

    def test_normalization_and_matching(self):
        self.assertEqual(
            normalize_artifact_name("orderflow-discovery-replay-${{ github.run_id }}"),
            "orderflow-discovery-replay",
        )
        self.assertEqual(normalize_artifact_name("orderflow-discovery-replay-"), "orderflow-discovery-replay")
        self.assertTrue(matches("orderflow-discovery-replay-${{ github.run_id }}", "orderflow-discovery-replay-*"))
        self.assertTrue(matches("evidence-v2-price-${{ matrix.family }}-${{ matrix.interval }}", "evidence-v2-price-*"))
        self.assertTrue(matches("evidence-v2-data-${{ matrix.interval }}", "evidence-v2-data-${{ matrix.interval }}"))
        self.assertFalse(matches("other-artifact", "evidence-v2-price-*"))


class AuditTests(unittest.TestCase):
    def _repo(self, root: Path, workflows: dict, requirements: list | None = None) -> Path:
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "config").mkdir(exist_ok=True)
        for name, body in workflows.items():
            (root / ".github" / "workflows" / name).write_text(body, encoding="utf-8")
        payload = {
            "schema_version": 1,
            "requirements": requirements
            or [
                {
                    "requirement_id": "r1",
                    "artifact_name": "inline-report",
                    "artifact_producer": ".github/workflows/inline.yml",
                }
            ],
        }
        (root / "config" / "requirements.json").write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_consumer_without_producer_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orphan = """\
name: Orphan
on: workflow_dispatch
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: never-produced
"""
            self._repo(root, {"orphan.yml": orphan})
            report = audit_workflow_contract(
                repo_root=root,
                requirements_path=Path("config/requirements.json"),
            )
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("artifact_downloaded_without_producer", codes)
            self.assertFalse(report["contract_ok"])

    def test_declared_producer_must_actually_upload_the_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(
                root,
                {"inline.yml": NO_RUN_INLINE},
                requirements=[
                    {
                        "requirement_id": "r1",
                        "artifact_name": "some-other-name",
                        "artifact_producer": ".github/workflows/inline.yml",
                    }
                ],
            )
            report = audit_workflow_contract(
                repo_root=root,
                requirements_path=Path("config/requirements.json"),
            )
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("required_artifact_without_producer", codes)
            self.assertFalse(report["contract_ok"])

    def test_satisfied_tree_reports_ok(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root, {"inline.yml": NO_RUN_INLINE})
            report = audit_workflow_contract(
                repo_root=root,
                requirements_path=Path("config/requirements.json"),
            )
            self.assertTrue(report["contract_ok"])
            self.assertEqual(report["requirements"][0]["declared_producer_uploads_it"], True)

    def test_markdown_renders_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root, {"inline.yml": NO_RUN_INLINE})
            report = audit_workflow_contract(
                repo_root=root,
                requirements_path=Path("config/requirements.json"),
            )
            text = workflow_contract_markdown(report)
            self.assertIn("Workflow to artifact contract", text)
            self.assertIn("inline-report", text)


class RealTreeTests(unittest.TestCase):
    """The regression test for the bug this module exists to prevent."""

    def setUp(self):
        self.report = audit_workflow_contract(repo_root=REPO_ROOT)
        self.by_value = {consumer["value"]: consumer for consumer in self.report["consumers"]}

    def test_contract_holds_on_the_repository(self):
        self.assertTrue(self.report["contract_ok"], msg=json.dumps(self.report["findings"], indent=2))
        self.assertGreater(self.report["workflows_scanned"], 40)
        self.assertEqual([f for f in self.report["findings"] if f["severity"] == "error"], [])

    def test_capture_health_consumer_has_a_real_producer(self):
        consumer = self.by_value["orderflow-discovery-replay-*"]
        self.assertTrue(consumer["satisfied"])
        self.assertIn(".github/workflows/orderflow-continuous-discovery.yml", consumer["producers"])

    def test_the_digest_consumer_has_a_real_producer(self):
        values = {consumer["value"] for consumer in self.report["consumers"]}
        self.assertIn("orderflow-discovery-replay-*", values)
        self.assertTrue(
            all(
                consumer["satisfied"]
                for consumer in self.report["consumers"]
                if consumer["value"] == "orderflow-discovery-replay-*"
            )
        )

    def test_every_retention_requirement_has_its_declared_producer(self):
        for record in self.report["requirements"]:
            self.assertTrue(
                record["declared_producer_uploads_it"],
                msg=f"{record['requirement_id']} is not produced by {record['declared_producer']}",
            )


if __name__ == "__main__":
    unittest.main()

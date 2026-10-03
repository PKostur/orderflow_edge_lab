import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab import freeze_manifest as freeze_manifest_module
from orderflow_edge_lab.freeze_manifest import (
    FreezeManifestError,
    build_manifest,
    file_sha256,
    freeze_manifest_markdown,
    load_manifest,
    verify_frozen_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(path: str, *, sha: str = "0" * 64, change_rule: str = "Versioned successor only."):
    return {"path": path, "sha256": sha, "frozen_for": "test", "change_rule": change_rule}


class ManifestLoadingTests(unittest.TestCase):
    def test_missing_or_invalid_manifest_is_rejected(self):
        with self.assertRaises(FreezeManifestError):
            load_manifest(Path("does/not/exist.json"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            target.write_text(json.dumps({"schema_version": 2, "files": []}), encoding="utf-8")
            with self.assertRaises(FreezeManifestError):
                load_manifest(target)
            target.write_text(json.dumps({"schema_version": 1, "files": []}), encoding="utf-8")
            with self.assertRaises(FreezeManifestError):
                load_manifest(target)

    def test_build_manifest_records_real_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "config" / "frozen.json"
            target.parent.mkdir(parents=True)
            target.write_text("{\"threshold\": 1}\n", encoding="utf-8")
            manifest = build_manifest(
                [{"path": "config/frozen.json", "frozen_for": "test", "change_rule": "successor only"}],
                repo_root=root,
                version="test-v1",
                recorded_at_utc="2026-09-30T00:00:00Z",
            )
            self.assertEqual(manifest["files"][0]["sha256"], file_sha256(target))
            self.assertIn("manifest_sha256", manifest)
            with self.assertRaises(FreezeManifestError):
                build_manifest([{"path": "config/absent.json"}], repo_root=root, version="x", recorded_at_utc="y")


class VerificationTests(unittest.TestCase):
    def _manifest(self, entries):
        return {"schema_version": 1, "version": "test", "files": entries}

    def test_matching_file_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "frozen.json"
            target.write_text("x", encoding="utf-8")
            manifest = self._manifest([_entry("frozen.json", sha=file_sha256(target))])
            report = verify_frozen_manifest(manifest, repo_root=root)
            self.assertTrue(report["verified"])
            self.assertEqual(report["files_matching"], 1)
            self.assertEqual(report["findings"], [])

    def test_changed_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "frozen.json"
            target.write_text("x", encoding="utf-8")
            manifest = self._manifest([_entry("frozen.json", sha="0" * 64)])
            report = verify_frozen_manifest(manifest, repo_root=root)
            self.assertFalse(report["verified"])
            self.assertEqual(report["files_changed"], 1)
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("frozen_file_changed", codes)

    def test_missing_file_is_an_error(self):
        manifest = self._manifest([_entry("gone.json", sha="a" * 64)])
        with tempfile.TemporaryDirectory() as directory:
            report = verify_frozen_manifest(manifest, repo_root=Path(directory))
            self.assertEqual(report["files_missing"], 1)
            self.assertIn("frozen_file_missing", {finding["code"] for finding in report["findings"]})

    def test_duplicate_and_invalid_entries_are_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "frozen.json"
            target.write_text("x", encoding="utf-8")
            manifest = self._manifest(
                [
                    _entry("frozen.json", sha=file_sha256(target)),
                    _entry("frozen.json", sha=file_sha256(target)),
                    _entry("other.json", sha="not-a-hash"),
                ]
            )
            report = verify_frozen_manifest(manifest, repo_root=root)
            codes = {finding["code"] for finding in report["findings"]}
            self.assertIn("manifest_entry_duplicate", codes)
            self.assertIn("manifest_entry_invalid", codes)
            self.assertFalse(report["verified"])

    def test_hashing_is_independent_of_line_endings(self):
        # A Windows checkout with CRLF conversion must not register as a change to
        # a frozen definition; the contract is about content, not about platform.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unix = root / "unix.json"
            windows = root / "windows.json"
            unix.write_bytes(b'{\n  "threshold": 1\n}\n')
            windows.write_bytes(b'{\r\n  "threshold": 1\r\n}\r\n')
            self.assertEqual(file_sha256(unix), file_sha256(windows))

            plain = root / "plain.json"
            plain.write_bytes(b'{\n  "threshold": 1\n}\n')
            converted = root / "converted.json"
            converted.write_bytes(b'{\r\n  "threshold": 1\r\n}\r\n')
            manifest = self._manifest([_entry("plain.json", sha=file_sha256(converted))])
            report = verify_frozen_manifest(manifest, repo_root=root)
            self.assertTrue(report["verified"], msg=json.dumps(report["findings"], indent=2))

    def test_binary_content_is_hashed_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "blob.bin"
            binary.write_bytes(b"\x00\xff\r\n\x80")
            self.assertEqual(file_sha256(binary), hashlib.sha256(b"\x00\xff\r\n\x80").hexdigest())

    def test_missing_change_rule_is_a_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "frozen.json"
            target.write_text("x", encoding="utf-8")
            manifest = self._manifest(
                [{"path": "frozen.json", "sha256": file_sha256(target), "frozen_for": "test"}]
            )
            report = verify_frozen_manifest(manifest, repo_root=root)
            self.assertTrue(report["verified"])
            self.assertEqual(report["highest_severity"], "warning")
            self.assertIn("change_rule_absent", {finding["code"] for finding in report["findings"]})

    def test_claims_and_determinism(self):
        manifest = self._manifest([_entry("gone.json", sha="a" * 64)])
        first = verify_frozen_manifest(manifest)
        second = verify_frozen_manifest(manifest)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertFalse(any(first["claims"].values()))

    def test_there_is_no_write_mode(self):
        # Rewriting a recorded hash is exactly the operation this module makes
        # visible, so it must stay a reviewed hand edit.
        self.assertFalse(hasattr(freeze_manifest_module, "write_manifest"))
        self.assertFalse(hasattr(freeze_manifest_module, "update_manifest"))

    def test_markdown_lists_every_file(self):
        manifest = self._manifest([_entry("gone.json", sha="a" * 64)])
        text = freeze_manifest_markdown(verify_frozen_manifest(manifest))
        self.assertIn("gone.json", text)
        self.assertIn("frozen_file_missing", text)


class RealManifestTests(unittest.TestCase):
    """Contract test: the committed manifest must match the committed configs."""

    def test_repository_frozen_definitions_match(self):
        manifest = load_manifest(REPO_ROOT / "config" / "frozen_manifest_v1.json")
        report = verify_frozen_manifest(manifest, repo_root=REPO_ROOT)
        self.assertTrue(report["verified"], msg=json.dumps(report["findings"], indent=2))
        self.assertEqual(report["files_total"], 14)  # 12 + the two LSK freeze files
        self.assertEqual(report["files_changed"], 0)
        self.assertEqual(report["files_missing"], 0)

    def test_the_don8_and_session_watch_definitions_are_covered(self):
        manifest = load_manifest(REPO_ROOT / "config" / "frozen_manifest_v1.json")
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertIn("config/evidence_v2_session_forward_watch_v1.json", paths)
        self.assertIn("config/session_development_watch_v1.json", paths)
        self.assertIn("config/orderflow_discovery_v1.json", paths)
        self.assertIn("config/regime_research_v1.json", paths)
        references = {entry["freeze_reference"] for entry in manifest["files"]}
        self.assertTrue(any(reference and "37ec950f" in reference for reference in references))

    def test_manifest_verifies_against_a_crlf_checkout(self):
        # Reproduction of the Windows CI failure: rewriting every frozen definition
        # with CRLF must not change a single hash.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(REPO_ROOT / "config", root / "config")
            for path in (root / "config").glob("*.json"):
                path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            manifest = load_manifest(REPO_ROOT / "config" / "frozen_manifest_v1.json")
            report = verify_frozen_manifest(manifest, repo_root=root)
            self.assertTrue(report["verified"], msg=json.dumps(report["findings"], indent=2))
            self.assertEqual(report["files_changed"], 0)

    def test_config_definitions_are_covered_by_the_attribute_rule(self):
        # .gitattributes pins config/*.json so a Windows checkout keeps their bytes.
        rules = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("config/*.json -text", rules)

    def test_tampering_with_a_copy_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(REPO_ROOT / "config", root / "config")
            manifest = load_manifest(REPO_ROOT / "config" / "frozen_manifest_v1.json")
            target = root / "config" / "orderflow_discovery_v1.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["tampered"] = True
            target.write_text(json.dumps(payload), encoding="utf-8")
            report = verify_frozen_manifest(manifest, repo_root=root)
            self.assertFalse(report["verified"])
            self.assertEqual(report["files_changed"], 1)
            self.assertEqual(report["findings"][0]["path"], "config/orderflow_discovery_v1.json")


if __name__ == "__main__":
    unittest.main()

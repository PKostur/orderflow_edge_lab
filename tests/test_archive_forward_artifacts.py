import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("archive_forward_artifacts", ROOT / "scripts" / "archive_forward_artifacts.py")
arch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(arch)


def art(i, name, created, expired=False):
    return {"id": i, "name": name, "created_at": created, "expired": expired, "workflow_run": {"id": 100 + i}}


class SelectTests(unittest.TestCase):
    def test_reports_kept_every_run_ledgers_newest_per_day(self):
        arts = [art(1, "multi-premia-blend-v1", "2026-10-16T01:00:00Z"),
                art(2, "multi-premia-blend-v1", "2026-10-16T20:00:00Z"),
                art(3, "liquidation-flow-ledger-v1", "2026-10-16T01:00:00Z"),
                art(4, "liquidation-flow-ledger-v1", "2026-10-16T09:00:00Z"),
                art(5, "liquidation-flow-ledger-v1", "2026-10-17T01:00:00Z"),
                art(6, "capture-health-watch", "2026-10-16T01:00:00Z"),
                art(7, "fade24-forward-v1", "2026-10-16T01:00:00Z", expired=True)]
        self.assertEqual([a["id"] for a in arch.select(arts, set())], [1, 4, 2, 5])

    def test_ledger_never_falls_back_to_an_older_same_day_artifact(self):
        arts = [art(3, "liquidation-flow-ledger-v1", "2026-10-16T01:00:00Z"),
                art(4, "liquidation-flow-ledger-v1", "2026-10-16T20:00:00Z")]
        self.assertEqual([a["id"] for a in arch.select(arts, set())], [4])
        self.assertEqual(arch.select(arts, {4}), [])

    def test_token_is_not_forwarded_on_redirect(self):
        import unittest.mock as mock
        seen = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(req, timeout):
            seen["redirected"] = dict(req.headers)
            seen["unredirected"] = dict(req.unredirected_hdrs)
            return Resp()

        with mock.patch.object(arch.urllib.request, "urlopen", fake_urlopen):
            arch._get("https://api.github.com/x", "tok")
        self.assertNotIn("Authorization", seen["redirected"])
        self.assertEqual(seen["unredirected"]["Authorization"], "Bearer tok")

    def test_already_archived_are_skipped(self):
        arts = [art(1, "fade24-forward-v1", "2026-10-16T01:00:00Z"), art(2, "fade24-forward-v1", "2026-10-16T02:00:00Z")]
        self.assertEqual([a["id"] for a in arch.select(arts, {1})], [2])


class ExtractTests(unittest.TestCase):
    def _zip(self, members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in members.items():
                z.writestr(name, data)
        return buf.getvalue()

    def test_extract_hashes_files_and_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            files = arch.extract(self._zip({"report.json": b"{}"}), Path(d) / "x")
            self.assertEqual(files["report.json"], "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a")
            m = Path(d) / "manifest.jsonl"
            m.write_text(json.dumps({"artifact_id": 9}) + "\n", encoding="utf-8")
            self.assertEqual(arch.archived_ids_from(m), {9})

    def test_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                arch.extract(self._zip({"../evil.json": b"{}"}), Path(d) / "x")


if __name__ == "__main__":
    unittest.main()

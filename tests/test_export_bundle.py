import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.export_bundle import build_export_bundle


HEADER = ["eventTime", "eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize", "sequence"]


def write_csv(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ExportBundleTests(unittest.TestCase):
    def test_merges_overlap_deterministically_and_hashes_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.csv"
            b = root / "b.csv"
            out = root / "bundle.csv"
            row1 = {"eventTime":"2026-09-12T00:00:00Z","eventSymbol":"NQ","bidPrice":"100","askPrice":"101","bidSize":"10","askSize":"11","sequence":"1"}
            row2 = {"eventTime":"2026-09-12T00:00:01Z","eventSymbol":"NQ","bidPrice":"101","askPrice":"102","bidSize":"12","askSize":"9","sequence":"2"}
            row3 = {"eventTime":"2026-09-12T00:00:02Z","eventSymbol":"NQ","bidPrice":"102","askPrice":"103","bidSize":"8","askSize":"7","sequence":"3"}
            write_csv(a, [row1, row2])
            write_csv(b, [row2, row3])
            result = build_export_bundle([a, b], out)
            self.assertEqual(result.stats.input_rows, 4)
            self.assertEqual(result.stats.output_rows, 3)
            self.assertEqual(result.stats.exact_duplicates_removed, 1)
            self.assertEqual(result.output_sha256, hashlib.sha256(out.read_bytes()).hexdigest())
            manifest = json.loads((root / "bundle.csv.manifest.json").read_text())
            self.assertFalse(manifest["profitable_edge_established"])
            rows = list(csv.DictReader(out.open(encoding="utf-8")))
            self.assertEqual([r["sequence"] for r in rows], ["1", "2", "3"])

    def test_rejects_conflicting_sequence_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.csv"
            b = root / "b.csv"
            common = {"eventTime":"2026-09-12T00:00:00Z","eventSymbol":"NQ","bidPrice":"100","askPrice":"101","bidSize":"10","askSize":"11","sequence":"7"}
            changed = dict(common, bidSize="99")
            write_csv(a, [common])
            write_csv(b, [changed])
            with self.assertRaisesRegex(ValueError, "conflicting rows"):
                build_export_bundle([a, b], root / "bundle.csv")

    def test_same_timestamp_without_sequence_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.csv"
            rows = [
                {"eventTime":"2026-09-12T00:00:00Z","eventSymbol":"NQ","bidPrice":"100","askPrice":"101","bidSize":"10","askSize":"11","sequence":""},
                {"eventTime":"2026-09-12T00:00:00Z","eventSymbol":"NQ","bidPrice":"100","askPrice":"101","bidSize":"12","askSize":"11","sequence":""},
            ]
            write_csv(a, rows)
            result = build_export_bundle([a], root / "bundle.csv")
            self.assertEqual(result.stats.output_rows, 2)


if __name__ == "__main__":
    unittest.main()

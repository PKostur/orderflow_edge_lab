from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.data_lineage import profile_csv_export
from orderflow_edge_lab.data_lineage_v2 import profile_csv_export_v2, verify_csv_export_v2


class DataLineageV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "lineage.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, value: str) -> None:
        self.path.write_text(value, encoding="utf-8")

    def test_adjacent_descending_nanoseconds_are_not_collapsed(self):
        self.write(
            "timestamp,symbol\n"
            "1700000000000000001,BTC\n"
            "1700000000000000000,BTC\n"
        )
        manifest = profile_csv_export_v2(self.path)
        timestamps = manifest["timestamps"]
        self.assertEqual(timestamps["regression_count"], 1)
        self.assertEqual(timestamps["first_ns"], 1700000000000000001)
        self.assertEqual(timestamps["last_ns"], 1700000000000000000)
        self.assertEqual(timestamps["minimum_ns"], 1700000000000000000)
        self.assertEqual(timestamps["maximum_ns"], 1700000000000000001)
        self.assertTrue(verify_csv_export_v2(self.path, manifest)["matches"])

    def test_seconds_milliseconds_microseconds_nanoseconds_and_timezone_rules(self):
        self.write(
            "timestamp,symbol\n"
            "1700000000,BTC\n"
            "1700000000000,BTC\n"
            "1700000000000000,BTC\n"
            "1700000000000000000,BTC\n"
            "2023-11-14T22:13:20+00:00,BTC\n"
            "2023-11-14T22:13:20.000000000Z,BTC\n"
            "2023-11-14T22:13:20,BTC\n"
            "1700000000.0000000001,BTC\n"
        )
        manifest = profile_csv_export_v2(self.path)
        self.assertEqual(manifest["timestamps"]["parsed_count"], 6)
        self.assertEqual(manifest["timestamps"]["parse_error_count"], 2)

    def test_v1_verifies_unchanged_and_v2_manifest_tampering_is_detected(self):
        self.write("timestamp,symbol\n1700000000000000001,BTC\n")
        v1 = profile_csv_export(self.path)
        self.assertTrue(verify_csv_export_v2(self.path, v1)["matches"])
        v2 = profile_csv_export_v2(self.path)
        tampered = dict(v2)
        tampered_timestamps = dict(v2["timestamps"])
        tampered_timestamps["first_ns"] = 1
        tampered["timestamps"] = tampered_timestamps
        result = verify_csv_export_v2(self.path, tampered)
        self.assertFalse(result["matches"])
        self.assertFalse(result["checks"]["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()

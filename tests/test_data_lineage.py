import hashlib
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.data_lineage import ExportProfileError, profile_csv_export, verify_csv_export


class DataLineageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "deepcharts.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_profiles_exact_bytes_schema_and_time_order(self):
        self.write(
            "timestamp,symbol,bid,ask\n"
            "2026-09-11T00:00:01Z,MNQ,20000,20000.25\n"
            "2026-09-11T00:00:00Z,MNQ,19999.75,20000\n"
        )
        report = profile_csv_export(self.path)
        self.assertEqual(report["file"]["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(report["csv"]["row_count"], 2)
        self.assertEqual(report["timestamps"]["parsed_count"], 2)
        self.assertEqual(report["timestamps"]["regression_count"], 1)
        self.assertEqual(report["symbols"]["samples"], ["MNQ"])

    def test_epoch_milliseconds_are_supported(self):
        self.write("time,instrument,price\n1789084800000,NQ,20000\n")
        report = profile_csv_export(self.path)
        self.assertEqual(report["timestamps"]["parse_error_count"], 0)
        self.assertEqual(report["timestamps"]["parsed_count"], 1)
        self.assertEqual(report["symbols"]["samples"], ["NQ"])

    def test_bad_timestamp_is_counted_not_silently_coerced(self):
        self.write("timestamp,symbol\nnot-a-time,MNQ\n")
        report = profile_csv_export(self.path)
        self.assertEqual(report["timestamps"]["parsed_count"], 0)
        self.assertEqual(report["timestamps"]["parse_error_count"], 1)

    def test_malformed_width_and_duplicate_headers_fail_closed(self):
        cases = (
            "timestamp,symbol\n2026-09-11T00:00:00Z,MNQ,extra\n",
            "timestamp,Timestamp\n2026-09-11T00:00:00Z,2026-09-11T00:00:00Z\n",
        )
        for text in cases:
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(ExportProfileError):
                    profile_csv_export(self.path)

    def test_verify_detects_tampering(self):
        self.write("timestamp,symbol\n2026-09-11T00:00:00Z,MNQ\n")
        manifest = profile_csv_export(self.path)
        self.assertTrue(verify_csv_export(self.path, manifest)["matches"])
        self.write("timestamp,symbol\n2026-09-11T00:00:00Z,NQ\n")
        result = verify_csv_export(self.path, manifest)
        self.assertFalse(result["matches"])
        self.assertFalse(result["checks"]["sha256"])
        self.assertFalse(result["checks"]["row_chain"])

    def test_explicit_missing_columns_fail(self):
        self.write("timestamp,symbol\n2026-09-11T00:00:00Z,MNQ\n")
        with self.assertRaisesRegex(ExportProfileError, "timestamp column not found"):
            profile_csv_export(self.path, timestamp_column="event_time")
        with self.assertRaisesRegex(ExportProfileError, "symbol column not found"):
            profile_csv_export(self.path, symbol_column="contract")


if __name__ == "__main__":
    unittest.main()

import csv
import io
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.cli.export_audit import audit_export
from orderflow_edge_lab.dxfeed_bbo import BboSample, compute_bbo_ofi, extract_bbo_samples


class DxFeedBboTests(unittest.TestCase):
    def test_extracts_common_dxfeed_camel_case_fields(self):
        rows = [
            {
                "eventTime": "2026-09-11T12:00:00.000000001Z",
                "eventSymbol": "NQ",
                "bidPrice": "100.00",
                "askPrice": "100.25",
                "bidSize": "10",
                "askSize": "12",
                "sequence": "1",
            },
            {
                "eventTime": "2026-09-11T12:00:00.000000002Z",
                "eventSymbol": "NQ",
                "bidPrice": "100.00",
                "askPrice": "100.25",
                "bidSize": "14",
                "askSize": "9",
                "sequence": "2",
            },
        ]
        result = extract_bbo_samples(rows, reject_timestamp_regressions=True)
        self.assertEqual(len(result.samples), 2)
        self.assertEqual(result.samples[0].bid_size, 10)
        self.assertEqual(result.samples[1].ask_size, 9)
        self.assertEqual(result.stats.incomplete_size_rows, 0)
        self.assertEqual(result.stats.size_coverage_fraction, 1.0)

    def test_same_timestamp_requires_increasing_sequence(self):
        rows = [
            {"time": "2026-09-11T12:00:00Z", "symbol": "NQ", "bid": 100, "ask": 101,
             "bid_size": 10, "ask_size": 10, "sequence": 2},
            {"time": "2026-09-11T12:00:00Z", "symbol": "NQ", "bid": 100, "ask": 101,
             "bid_size": 11, "ask_size": 9, "sequence": 2},
            {"time": "2026-09-11T12:00:00Z", "symbol": "NQ", "bid": 100, "ask": 101,
             "bid_size": 12, "ask_size": 8, "sequence": 3},
        ]
        result = extract_bbo_samples(rows)
        self.assertEqual(len(result.samples), 2)
        self.assertEqual(result.stats.same_timestamp_ambiguous_rows, 1)

    def test_ofi_identity_for_unchanged_best_prices(self):
        samples = [
            BboSample(1, "NQ", 100, 101, 10, 12, 1),
            BboSample(2, "NQ", 100, 101, 14, 9, 2),
        ]
        events, stats = compute_bbo_ofi(samples)
        self.assertEqual(stats.ofi_events, 1)
        self.assertEqual(events[0].bid_contribution, 4)
        self.assertEqual(events[0].ask_contribution, 3)
        self.assertEqual(events[0].ofi, 7)

    def test_ofi_identity_for_price_improvement(self):
        samples = [
            BboSample(1, "NQ", 100, 101, 10, 12, 1),
            BboSample(2, "NQ", 100.25, 100.75, 8, 7, 2),
        ]
        events, _ = compute_bbo_ofi(samples)
        self.assertEqual(events[0].bid_contribution, 8)
        self.assertEqual(events[0].ask_contribution, -7)
        self.assertEqual(events[0].ofi, 1)

    def test_export_audit_marks_ofi_eligible_only_with_sufficient_samples(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.csv"
            output = io.StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=["timestamp", "symbol", "kind", "price", "side", "bid", "ask", "bidSize", "askSize", "sequence"],
            )
            writer.writeheader()
            for i in range(1, 6):
                writer.writerow({
                    "timestamp": f"2026-09-11T12:00:0{i}Z",
                    "symbol": "NQ",
                    "kind": "TRADE",
                    "price": "100.25",
                    "side": "BUY",
                    "bid": "100.00",
                    "ask": "100.25",
                    "bidSize": str(10 + i),
                    "askSize": str(12 - i),
                    "sequence": str(i),
                })
            path.write_text(output.getvalue(), encoding="utf-8")
            report = audit_export(
                path,
                default_symbol=None,
                min_events=1,
                min_bbo_size_samples=3,
                allow_quote_only=False,
            )
            self.assertTrue(report["quality"]["passed"])
            self.assertTrue(report["research_eligibility"]["bbo_ofi"])
            self.assertEqual(report["ofi"]["ofi_events"], 4)

    def test_missing_sizes_are_reported_not_synthesized(self):
        rows = [
            {"timestamp": "2026-09-11T12:00:00Z", "symbol": "NQ", "bid": 100, "ask": 101},
        ]
        result = extract_bbo_samples(rows)
        self.assertEqual(result.stats.rows_with_bbo_prices, 1)
        self.assertEqual(result.stats.complete_size_samples, 0)
        self.assertEqual(result.stats.incomplete_size_rows, 1)


if __name__ == "__main__":
    unittest.main()

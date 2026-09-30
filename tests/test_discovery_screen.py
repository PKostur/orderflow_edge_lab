import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.cli.discovery_screen import main as discovery_screen_main
from orderflow_edge_lab.discovery_screen import (
    SCREEN_CLEARS,
    SCREEN_FAILS,
    SCREEN_INDETERMINATE,
    DiscoveryScreenError,
    build_discovery_screen,
    compare_declared_vs_measured,
    cost_screen,
    discovery_screen_markdown,
    load_observation_rows,
    measured_friction,
    spread_bps,
)


def _rows(mean_gross: float, cost: float = 5.0, count: int = 20):
    return [{"gross_bps": mean_gross, "cost_bps": cost} for _ in range(count)]


class LoaderTests(unittest.TestCase):
    def test_json_lines_and_array_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lines = root / "rows.jsonl"
            lines.write_text(
                "\n".join(json.dumps({"gross_bps": 10.0, "cost_bps": 2.0}) for _ in range(3)) + "\n",
                encoding="utf-8",
            )
            array = root / "rows.json"
            array.write_text(json.dumps([{"gross_bps": 10.0, "cost_bps": 2.0}]), encoding="utf-8")
            self.assertEqual(len(load_observation_rows(lines)), 3)
            self.assertEqual(len(load_observation_rows(array)), 1)

    def test_missing_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rows.jsonl"
            target.write_text(json.dumps({"gross_bps": 1.0}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(DiscoveryScreenError, "cost_bps"):
                load_observation_rows(target)

    def test_empty_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rows.jsonl"
            target.write_text("\n", encoding="utf-8")
            with self.assertRaises(DiscoveryScreenError):
                load_observation_rows(target)


class CostScreenTests(unittest.TestCase):
    def test_candidate_clearing_the_declared_screen(self):
        screen = cost_screen(_rows(20.0, cost=5.0), minimum_break_even_ratio=3.0)
        self.assertEqual(screen["screen_status"], SCREEN_CLEARS)
        self.assertAlmostEqual(screen["break_even_to_base_cost_ratio"], 4.0)
        self.assertTrue(screen["screen_threshold_supplied_by_caller"])

    def test_candidate_failing_the_declared_screen(self):
        screen = cost_screen(_rows(4.0, cost=5.0), minimum_break_even_ratio=1.5)
        self.assertEqual(screen["screen_status"], SCREEN_FAILS)
        self.assertLess(screen["mean_net_bps_at_base_cost"], 0.0)

    def test_zero_cost_is_indeterminate_not_a_pass(self):
        screen = cost_screen(_rows(10.0, cost=0.0), minimum_break_even_ratio=1.0)
        self.assertEqual(screen["screen_status"], SCREEN_INDETERMINATE)
        self.assertIsNone(screen["break_even_to_base_cost_ratio"])

    def test_threshold_must_come_from_the_caller(self):
        with self.assertRaises(DiscoveryScreenError):
            cost_screen(_rows(10.0), minimum_break_even_ratio=0.0)
        with self.assertRaises(DiscoveryScreenError):
            cost_screen(_rows(10.0), minimum_break_even_ratio=True)
        with self.assertRaises(DiscoveryScreenError):
            cost_screen([], minimum_break_even_ratio=1.0)


class FrictionTests(unittest.TestCase):
    def test_spread_from_field_or_quote_pair(self):
        self.assertEqual(spread_bps({"spread_bps": 3.5}), 3.5)
        self.assertAlmostEqual(spread_bps({"bid": 100.0, "ask": 100.1}), 10.0, places=2)
        self.assertIsNone(spread_bps({"bid": 100.1, "ask": 100.0}))
        self.assertIsNone(spread_bps({}))

    def test_measured_quantiles_and_fees(self):
        quotes = [{"spread_bps": value} for value in (1.0, 2.0, 3.0, 4.0, 100.0)]
        measured = measured_friction(quotes, fee_bps_per_side=2.0)
        self.assertEqual(measured["quotes"], 5)
        self.assertEqual(measured["median_spread_bps"], 3.0)
        self.assertEqual(measured["estimated_round_trip_cost_bps"], 7.0)
        self.assertEqual(measured["conservative_round_trip_cost_bps"], 104.0)

    def test_unusable_quotes_are_counted_not_silently_dropped(self):
        measured = measured_friction([{"bid": 1.0}, {"spread_bps": 2.0}], fee_bps_per_side=1.0)
        self.assertEqual(measured["quotes"], 1)
        self.assertEqual(measured["skipped_quotes"], 1)
        empty = measured_friction([{"bid": 1.0}], fee_bps_per_side=1.0)
        self.assertEqual(empty["status"], "no_usable_spreads")

    def test_declared_below_measured_is_an_error(self):
        measured = measured_friction([{"spread_bps": 12.0}], fee_bps_per_side=5.0)
        comparison = compare_declared_vs_measured(declared_round_trip_cost_bps=20.0, measured=measured)
        self.assertEqual(comparison["status"], "declared_cost_below_measured")
        self.assertEqual(comparison["findings"][0]["severity"], "error")

    def test_declared_above_measured_is_informational(self):
        measured = measured_friction([{"spread_bps": 2.0}], fee_bps_per_side=1.0)
        comparison = compare_declared_vs_measured(declared_round_trip_cost_bps=20.0, measured=measured)
        self.assertEqual(comparison["status"], "declared_cost_above_measured")
        self.assertEqual(comparison["findings"][0]["severity"], "info")

    def test_unavailable_measurement_is_not_compared(self):
        comparison = compare_declared_vs_measured(
            declared_round_trip_cost_bps=20.0, measured={"status": "no_usable_spreads"}
        )
        self.assertEqual(comparison["status"], "not_compared")
        self.assertEqual(comparison["findings"], [])


class BuildTests(unittest.TestCase):
    def test_full_report_with_quotes(self):
        report = build_discovery_screen(
            _rows(20.0, cost=5.0),
            declared_round_trip_cost_bps=20.0,
            minimum_break_even_ratio=3.0,
            friction_rows=[{"spread_bps": 8.0}, {"spread_bps": 12.0}],
            fee_bps_per_side=3.0,
        )
        self.assertEqual(report["screen"]["screen_status"], SCREEN_CLEARS)
        self.assertEqual(report["declared_vs_measured"]["status"], "declared_cost_above_measured")
        self.assertTrue(report["screen_ok"])
        self.assertFalse(any(report["claims"].values()))
        text = discovery_screen_markdown(report)
        self.assertIn("Discovery-time economics screen", text)
        self.assertIn("Measured friction", text)

    def test_failing_candidate_adds_a_warning(self):
        report = build_discovery_screen(
            _rows(4.0, cost=5.0), declared_round_trip_cost_bps=20.0, minimum_break_even_ratio=2.0
        )
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("candidate_fails_declared_economics_screen", codes)
        self.assertTrue(report["screen_ok"])  # a failing screen is not an assumption violation

    def test_weak_declared_cost_makes_the_report_not_ok(self):
        report = build_discovery_screen(
            _rows(20.0, cost=5.0),
            declared_round_trip_cost_bps=5.0,
            minimum_break_even_ratio=1.0,
            friction_rows=[{"spread_bps": 30.0}],
            fee_bps_per_side=3.0,
        )
        self.assertFalse(report["screen_ok"])
        self.assertEqual(report["highest_severity"], "error")

    def test_friction_quotes_without_a_fee_are_rejected(self):
        with self.assertRaises(DiscoveryScreenError):
            build_discovery_screen(
                _rows(20.0),
                declared_round_trip_cost_bps=20.0,
                minimum_break_even_ratio=1.0,
                friction_rows=[{"spread_bps": 5.0}],
            )

    def test_determinism(self):
        first = build_discovery_screen(_rows(20.0), declared_round_trip_cost_bps=20.0, minimum_break_even_ratio=3.0)
        second = build_discovery_screen(_rows(20.0), declared_round_trip_cost_bps=20.0, minimum_break_even_ratio=3.0)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class CliTests(unittest.TestCase):
    def test_cli_writes_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations = root / "rows.jsonl"
            observations.write_text(
                "\n".join(json.dumps(row) for row in _rows(20.0)) + "\n", encoding="utf-8"
            )
            output = root / "screen.json"
            code = discovery_screen_main(
                [
                    str(observations),
                    "--declared-round-trip-cost-bps",
                    "20",
                    "--minimum-break-even-ratio",
                    "3",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["analysis"], "discovery_time_economics_screen"
            )

    def test_cli_reports_failure_for_a_bad_input(self):
        self.assertEqual(
            discovery_screen_main(
                ["missing.jsonl", "--declared-round-trip-cost-bps", "20", "--minimum-break-even-ratio", "3"]
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()

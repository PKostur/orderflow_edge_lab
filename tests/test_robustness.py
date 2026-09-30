import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from orderflow_edge_lab.cli.robustness import main as robustness_main
from orderflow_edge_lab.robustness import (
    RobustnessError,
    build_robustness_report,
    cluster_bootstrap_mean,
    cluster_units,
    interval_observations,
    robustness_markdown,
)

BUCKETS = ("ASIA_00_08", "LONDON_PLUS_OVERLAP_08_16", "NY_POST_PLUS_LATE_16_24")


def _row(start, bucket, net_bps, *, gross_bps=None, cost_bps=0.0, symbols=None):
    gross = net_bps if gross_bps is None else gross_bps
    return {
        "start": start,
        "end": start,
        "session_bucket": bucket,
        "portfolio_net_return": net_bps / 10_000.0,
        "portfolio_turnover_cost_bps": cost_bps,
        "portfolio_long_gross_bps": gross if gross >= 0 else 0.0,
        "portfolio_short_gross_bps": gross if gross < 0 else 0.0,
        "active_symbol_count": len(symbols or {}),
        "symbol_net_contribution_bps": symbols or {},
    }


def _variant(audit_id, role, rows):
    return {
        "audit_id": audit_id,
        "role": role,
        "family": "test_family",
        "interval": "8h",
        "parameters": {},
        "all_intervals": {},
        "by_session_bucket": [],
        "interval_rows": rows,
    }


def _report(variants, *, hypothesis="test hypothesis statement"):
    return {
        "schema_version": 1,
        "analysis": "evidence_v2_cross_strategy_session_forward_v1",
        "watch_id": "test_watch",
        "status": "ACCUMULATING",
        "days_elapsed": 7,
        "as_of_utc": "2026-09-30T00:00:00+00:00",
        "reports": variants,
        "primary_hypothesis": {"statement": hypothesis},
    }


def _correlated_rows(cluster_count=8, per_cluster=3, cluster_bps=None, with_symbols=True):
    """One cluster per calendar day: rows inside a day share a common component.

    Each day carries a large common move plus a small bar-specific wobble, which
    is exactly the dependence a bar-level resample ignores and a day-level
    resample respects.
    """

    values = cluster_bps or [60.0, -55.0, 20.0, -25.0, 45.0, -35.0, 30.0, -15.0]
    wobble = (3.0, -2.0, 1.0, -1.0, 2.0)
    rows = []
    for index in range(cluster_count):
        value = values[index % len(values)]
        day = 20 + index
        for offset in range(per_cluster):
            row_value = value + wobble[offset % len(wobble)]
            symbols = {}
            if with_symbols:
                symbols = {"BTC_USDT": row_value / 2.0, "ENA_USDT": row_value / 2.0}
            rows.append(
                _row(
                    f"2026-09-{day:02d}T{offset * 8:02d}:00:00+00:00",
                    BUCKETS[offset % len(BUCKETS)],
                    row_value,
                    gross_bps=row_value,
                    symbols=symbols,
                )
            )
    return rows


class ClusterBootstrapTests(unittest.TestCase):
    def test_day_clustered_interval_is_wider_than_a_bar_level_interval(self):
        # A bar-level resample treats the three bars of one day as independent.
        # A day-level resample does not, and must therefore be wider.
        rows = _correlated_rows()
        variant = _variant("A", "PRIMARY_SESSION_HYPOTHESIS", rows)
        bar_level = cluster_bootstrap_mean(
            cluster_units(interval_observations(variant, cluster="bar")), resamples=4000, seed=7
        )
        day_level = cluster_bootstrap_mean(
            cluster_units(interval_observations(variant, cluster="day")), resamples=4000, seed=7
        )
        bar_width = bar_level["ci_upper_bps"] - bar_level["ci_lower_bps"]
        day_width = day_level["ci_upper_bps"] - day_level["ci_lower_bps"]

        self.assertGreater(day_width, bar_width * 1.3)
        self.assertEqual(bar_level["cluster_count"], 24)
        self.assertEqual(day_level["cluster_count"], 8)
        self.assertEqual(day_level["observation_count"], 24)

    def test_zero_edge_interval_straddles_zero_and_no_verdict(self):
        rows = []
        for index in range(6):
            rows.append(_row(f"2026-09-{20 + index:02d}T00:00:00+00:00", BUCKETS[0], 10.0, symbols={"BTC_USDT": 10.0}))
            rows.append(_row(f"2026-09-{20 + index:02d}T08:00:00+00:00", BUCKETS[1], -10.0, symbols={"BTC_USDT": -10.0}))
        report = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]),
            cluster="bar",
        )
        self.assertFalse(report["interval"]["interval_excludes_zero"])
        self.assertIsNone(report["verdict"])
        self.assertTrue(report["verdict_requires_human_review"])

    def test_determinism_and_self_hash(self):
        report = _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())])
        first = build_robustness_report(report, cluster="bar", design_clusters=90)
        second = build_robustness_report(report, cluster="bar", design_clusters=90)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        canonical = json.dumps(
            {key: value for key, value in first.items() if key != "report_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), first["report_sha256"])

    def test_claims_numeric_thresholds_and_labels(self):
        report = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())]),
            cluster="bar",
        )
        self.assertFalse(any(report["claims"].values()))
        self.assertTrue(report["numeric_thresholds_invented"] is False)
        self.assertEqual(report["analysis_label"], "post_hoc_descriptive")
        self.assertEqual(report["decision_rule_status"], "watch_config_not_supplied")
        text = robustness_markdown(report)
        self.assertIn("post_hoc_descriptive", text)
        self.assertIn("withheld", text)
        self.assertIn("Negative controls", text)

    def test_resample_guards(self):
        units = cluster_units(interval_observations(_variant("A", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())))
        with self.assertRaisesRegex(RobustnessError, "at least 100"):
            cluster_bootstrap_mean(units, resamples=10)
        with self.assertRaisesRegex(RobustnessError, "confidence"):
            cluster_bootstrap_mean(units, confidence=1.5)
        with self.assertRaises(RobustnessError):
            cluster_bootstrap_mean([])


class ReportingTests(unittest.TestCase):
    def test_minimum_detectable_effect_shrinks_with_the_design_size(self):
        rows = _correlated_rows()
        observations = interval_observations(_variant("A", "PRIMARY_SESSION_HYPOTHESIS", rows))
        units = cluster_units(observations)
        small = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]), cluster="bar", design_clusters=90
        )["minimum_detectable_effect"]
        large = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]), cluster="bar", design_clusters=360
        )["minimum_detectable_effect"]
        self.assertEqual(small["design_clusters"], 90)
        self.assertAlmostEqual(
            small["minimum_detectable_effect_bps"] / large["minimum_detectable_effect_bps"], 2.0, places=6
        )
        self.assertEqual(len(units), 24)

    def test_design_size_not_supplied_is_reported_not_guessed(self):
        block = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())]), cluster="bar"
        )["minimum_detectable_effect"]
        self.assertEqual(block["status"], "design_size_not_supplied")
        self.assertIsNone(block["minimum_detectable_effect_bps"])

    def test_concentration_and_leave_one_symbol_out(self):
        rows = [
            _row(
                f"2026-09-2{index}T00:00:00+00:00",
                BUCKETS[0],
                10.0,
                symbols={"BTC_USDT": index * 10.0, "ENA_USDT": -1.0},
            )
            for index in range(1, 6)
        ]
        report = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]), cluster="bar"
        )
        concentration = report["concentration"]
        self.assertEqual(concentration["symbol_count"], 2)
        self.assertEqual(concentration["positive_symbol_count"], 1)
        self.assertGreater(concentration["best_symbol_positive_pnl_share"], 0.9)
        self.assertLess(concentration["minimum_leave_one_symbol_out_mean_bps"], 0.0)

    def test_control_arms_are_paired_on_shared_bars(self):
        primary_rows = _correlated_rows()
        control_rows = [
            {**row, "portfolio_net_return": (row["portfolio_net_return"] + 0.0050)} for row in primary_rows
        ]
        report = build_robustness_report(
            _report(
                [
                    _variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", primary_rows),
                    _variant("EMA8", "CONTROL", control_rows),
                ]
            ),
            cluster="bar",
        )
        comparison = report["control_arms"]["EMA8"]["comparison_to_primary"]
        self.assertEqual(comparison["status"], "ok")
        self.assertEqual(comparison["shared_clusters"], 24)
        self.assertAlmostEqual(comparison["difference_mean_bps"], -50.0, places=6)
        self.assertTrue(comparison["interval_excludes_zero"])

    def test_control_comparison_reports_insufficient_shared_bars(self):
        primary = _correlated_rows(cluster_count=2)
        control = [
            _row("2026-01-01T00:00:00+00:00", BUCKETS[0], 5.0),
            _row("2026-01-02T00:00:00+00:00", BUCKETS[0], 5.0),
        ]
        report = build_robustness_report(
            _report(
                [
                    _variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", primary),
                    _variant("EMA8", "CONTROL", control),
                ]
            ),
            cluster="bar",
        )
        self.assertEqual(
            report["control_arms"]["EMA8"]["comparison_to_primary"]["status"], "insufficient_shared_clusters"
        )

    def test_placebo_side_reversed_is_the_mirror_arm(self):
        rows = [
            _row("2026-09-21T00:00:00+00:00", BUCKETS[0], 12.0, gross_bps=15.0, cost_bps=3.0),
            _row("2026-09-22T00:00:00+00:00", BUCKETS[1], -8.0, gross_bps=-5.0, cost_bps=3.0),
            _row("2026-09-23T00:00:00+00:00", BUCKETS[2], 4.0, gross_bps=7.0, cost_bps=3.0),
        ]
        report = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]), cluster="bar"
        )
        mirror = report["placebo_arms"]["side_reversed"]["mean_bps"]
        expected = -float(np.mean([15.0, -5.0, 7.0])) - 3.0
        self.assertAlmostEqual(mirror, expected, places=9)
        self.assertFalse(report["placebo_arms"]["bucket_rotation"]["phase_shift_available"])
        self.assertEqual(report["concentration"]["status"], "no_symbol_attribution")
        baskets = report["placebo_arms"]["single_symbol_baskets"]
        self.assertEqual(baskets["symbol_count"], 0)

    def test_symbol_attribution_absent_degrades_gracefully(self):
        rows = _correlated_rows(with_symbols=False)
        report = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]), cluster="bar"
        )
        self.assertEqual(report["concentration"]["status"], "no_symbol_attribution")
        self.assertIn("`no_symbol_attribution`", robustness_markdown(report))

    def test_cost_surface_reuses_the_shared_implementation(self):
        rows = [
            _row("2026-09-21T00:00:00+00:00", BUCKETS[0], 5.0, gross_bps=10.0, cost_bps=5.0),
            _row("2026-09-22T00:00:00+00:00", BUCKETS[0], 5.0, gross_bps=10.0, cost_bps=5.0),
        ]
        surface = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)]),
            cluster="bar",
            cost_multipliers=(1.0, 2.0),
        )["cost_surface"]
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(surface["break_even_round_trip_cost_bps"], 10.0)
        self.assertAlmostEqual(surface["break_even_to_base_cost_ratio"], 2.0)
        self.assertAlmostEqual(surface["cases"]["2.0"]["mean_net_bps"], 0.0)

    def test_family_selection_diagnostics_need_a_non_control_family(self):
        single = build_robustness_report(
            _report(
                [
                    _variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows()),
                    _variant("EMA8", "CONTROL", _correlated_rows()),
                ]
            ),
            cluster="bar",
        )["family_selection_diagnostics"]
        self.assertEqual(single["status"], "insufficient_variant_family")

        rows_a = _correlated_rows(cluster_count=8, per_cluster=1)
        rows_b = [
            {**row, "portfolio_net_return": row["portfolio_net_return"] * 0.5} for row in rows_a
        ]
        family = build_robustness_report(
            _report(
                [
                    _variant("V1", "VARIANT", rows_a),
                    _variant("V2", "VARIANT", rows_b),
                ]
            ),
            audit_id="V1",
            cluster="bar",
        )["family_selection_diagnostics"]
        self.assertEqual(family["status"], "ok")
        self.assertIn("deflated_sharpe", family)
        self.assertIn("reality_check", family)

    def test_multiplicity_requires_a_declared_family(self):
        report = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())]),
            cluster="bar",
            family_size=12,
        )
        self.assertEqual(report["multiplicity"]["status"], "declared")
        self.assertAlmostEqual(report["multiplicity"]["adjusted_alpha"], 0.05 / 12.0)
        undeclared = build_robustness_report(
            _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())]), cluster="bar"
        )
        self.assertEqual(undeclared["multiplicity"]["status"], "family_not_declared")

    def test_cluster_unit_selection(self):
        rows = _correlated_rows(cluster_count=3, per_cluster=3)
        variant = _variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", rows)
        self.assertEqual(len(cluster_units(interval_observations(variant, cluster="bar"))), 9)
        self.assertEqual(len(cluster_units(interval_observations(variant, cluster="day"))), 3)
        self.assertEqual(len(cluster_units(interval_observations(variant, cluster="bucket"))), 3)
        filtered = interval_observations(variant, cluster="bar", bucket=BUCKETS[0])
        self.assertTrue(all(obs["session_bucket"] == BUCKETS[0] for obs in filtered))

    def test_decision_rule_status_comes_from_the_watch_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics_only = root / "metrics_only.json"
            metrics_only.write_text(json.dumps({"reporting": {"metrics": ["a", "b"]}}), encoding="utf-8")
            with_rule = root / "with_rule.json"
            with_rule.write_text(
                json.dumps(
                    {
                        "decision_rule": {
                            "metric": "net_mean_bps",
                            "direction": ">",
                            "threshold": 0.0,
                            "inconclusive_when": "interval includes zero",
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = _report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())])
            self.assertEqual(
                build_robustness_report(report, watch_config=metrics_only)["decision_rule_status"],
                "declared_metrics_without_numeric_thresholds",
            )
            self.assertEqual(
                build_robustness_report(report, watch_config=with_rule)["decision_rule_status"],
                "pre_registered_numeric_thresholds",
            )


class InputValidationTests(unittest.TestCase):
    def test_missing_variants_rejected(self):
        with self.assertRaisesRegex(RobustnessError, "reports"):
            build_robustness_report({"analysis": "x"})

    def test_variant_without_interval_rows_rejected(self):
        with self.assertRaisesRegex(RobustnessError, "interval_rows"):
            build_robustness_report({"reports": [{"audit_id": "DON8", "role": "PRIMARY_SESSION_HYPOTHESIS"}]})

    def test_unknown_cluster_rejected(self):
        variant = _variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())
        with self.assertRaisesRegex(RobustnessError, "cluster must be one of"):
            interval_observations(variant, cluster="symbol")

    def test_missing_audit_id_rejected(self):
        variant = _variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())
        with self.assertRaisesRegex(RobustnessError, "audit_id"):
            build_robustness_report(_report([variant]), audit_id="NOPE")

    def test_unreadable_report_rejected(self):
        with self.assertRaises(RobustnessError):
            build_robustness_report(Path("does/not/exist.json"))


class CliTests(unittest.TestCase):
    def test_cli_writes_hash_pinned_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.json"
            source.write_text(
                json.dumps(_report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())])),
                encoding="utf-8",
            )
            output = root / "robustness.json"
            markdown = root / "robustness.md"
            code = robustness_main(
                [
                    str(source),
                    "--output",
                    str(output),
                    "--markdown",
                    str(markdown),
                    "--design-clusters",
                    "90",
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["analysis"], "post_hoc_descriptive_robustness")
            self.assertIn("Post-hoc descriptive robustness", markdown.read_text(encoding="utf-8"))

    def test_cli_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.json"
            source.write_text(
                json.dumps(_report([_variant("DON8", "PRIMARY_SESSION_HYPOTHESIS", _correlated_rows())])),
                encoding="utf-8",
            )
            output = root / "robustness.json"
            self.assertEqual(robustness_main([str(source), "--output", str(output)]), 0)
            self.assertEqual(robustness_main([str(source), "--output", str(output)]), 2)

    def test_cli_reports_failure_for_a_bad_report(self):
        self.assertEqual(robustness_main(["missing.json"]), 2)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from orderflow_edge_lab.cli.orthogonality import main as orthogonality_main
from orderflow_edge_lab.orthogonality import (
    OrthogonalityError,
    build_orthogonality_report,
    delta_r2_rank,
    incremental_information,
    leave_one_out_stability,
    load_rows,
    orthogonality_markdown,
    partial_rank_ic,
    ranks,
    redundancy_clusters,
    spearman,
    spearman_matrix,
)


def _rows(count=40, *, noise_seed=5, feature_copy=False, noise_target=False):
    rng = np.random.default_rng(noise_seed)
    rows = []
    for index in range(count):
        baseline = float(index % 7) + float((index * 3) % 5) / 10.0
        feature = baseline if feature_copy else float((index * 3) % 5)
        if noise_target:
            target = float(rng.normal(0.0, 1.0))
        else:
            target = baseline + feature
        rows.append(
            {
                "baseline": baseline,
                "feature": feature,
                "target": target,
                "cluster": f"batch_{index % 4}",
                "symbol": "BTC_USDT" if index % 2 == 0 else "ENA_USDT",
            }
        )
    return rows


class RankTests(unittest.TestCase):
    def test_average_ranks_for_ties(self):
        self.assertEqual(list(ranks([1.0, 2.0, 2.0, 4.0])), [1.0, 2.5, 2.5, 4.0])

    def test_spearman_extremes(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]), 1.0, places=9)
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]), -1.0, places=9)

    def test_matrix_is_symmetric_with_unit_diagonal(self):
        columns = {"a": [1, 2, 3, 4, 5], "b": [2, 4, 6, 8, 10], "c": [5, 1, 4, 2, 3]}
        matrix = spearman_matrix(columns)
        self.assertAlmostEqual(matrix["a"]["a"], 1.0)
        self.assertAlmostEqual(matrix["a"]["b"], 1.0)
        self.assertAlmostEqual(matrix["a"]["c"], matrix["c"]["a"])


class RedundancyTests(unittest.TestCase):
    def test_identical_columns_cluster_together(self):
        base = [1.0, 5.0, 2.0, 8.0, 3.0, 9.0, 4.0, 7.0]
        columns = {
            "a": base,
            "b": [value * 3.0 for value in base],
            "c": [value * -1.0 + 100.0 for value in base],
        }
        result = redundancy_clusters(columns, threshold=0.9)
        clusters = {tuple(members) for members in result["clusters"]}
        # c is a perfectly inverted copy of a, so absolute correlation links all three.
        self.assertEqual(clusters, {("a", "b", "c")})
        self.assertEqual(result["redundant_cluster_count"], 1)

    def test_independent_column_stays_alone(self):
        base = [1.0, 5.0, 2.0, 8.0, 3.0, 9.0, 4.0, 7.0]
        columns = {"a": base, "b": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0][::-1], "c": base}
        result = redundancy_clusters(columns, threshold=0.99)
        clusters = [sorted(members) for members in result["clusters"]]
        self.assertIn(["a", "c"], clusters)
        self.assertEqual(result["redundant_cluster_count"], 1)

    def test_threshold_is_required_and_validated(self):
        with self.assertRaises(OrthogonalityError):
            redundancy_clusters({"a": [1.0, 2.0, 3.0]}, threshold=0.0)
        with self.assertRaises(OrthogonalityError):
            redundancy_clusters({"a": [1.0, 2.0, 3.0]}, threshold=1.5)


class IncrementalInformationTests(unittest.TestCase):
    def test_copy_of_the_baseline_adds_nothing(self):
        rows = _rows(feature_copy=True)
        delta = delta_r2_rank(rows, target="target", baseline=["baseline"], feature="feature")
        self.assertAlmostEqual(delta, 0.0, places=9)

    def test_feature_with_signal_adds_rank_information(self):
        rows = _rows()
        delta = delta_r2_rank(rows, target="target", baseline=["baseline"], feature="feature")
        noise_delta = delta_r2_rank(
            _rows(noise_target=True), target="target", baseline=["baseline"], feature="feature"
        )
        # The magnitude is fixture-specific; the property that matters is that a
        # carrying feature scores well above an independent noise target.
        self.assertGreater(delta, 0.2)
        self.assertGreater(delta, noise_delta)
        partial = partial_rank_ic(rows, target="target", baseline=["baseline"], feature="feature")
        # The synthetic feature is heavily tied (five distinct values over 40 rows),
        # so the partial rank correlation is attenuated relative to Delta R^2.
        self.assertGreater(partial, 0.2)

    def test_cluster_bootstrap_excludes_zero_for_a_real_signal(self):
        result = incremental_information(
            _rows(), feature="feature", baseline=["baseline"], target="target", cluster="cluster", resamples=400
        )
        interval = result["delta_r2_rank_interval"]
        self.assertEqual(interval["status"], "ok")
        self.assertEqual(interval["cluster_count"], 4)
        self.assertTrue(interval["interval_excludes_zero"])

    def test_cluster_bootstrap_includes_zero_for_noise(self):
        result = incremental_information(
            _rows(noise_target=True),
            feature="feature",
            baseline=["baseline"],
            target="target",
            cluster="cluster",
            resamples=400,
        )
        interval = result["delta_r2_rank_interval"]
        self.assertEqual(interval["status"], "ok")
        self.assertFalse(interval["interval_excludes_zero"])

    def test_baseline_is_required(self):
        with self.assertRaises(OrthogonalityError):
            incremental_information(_rows(), feature="feature", baseline=[], target="target")

    def test_non_numeric_and_non_finite_values_are_rejected(self):
        rows = _rows()
        rows[0]["feature"] = "high"
        with self.assertRaises(OrthogonalityError):
            incremental_information(rows, feature="feature", baseline=["baseline"], target="target")
        rows[0]["feature"] = float("nan")
        with self.assertRaises(OrthogonalityError):
            incremental_information(rows, feature="feature", baseline=["baseline"], target="target")


class StabilityTests(unittest.TestCase):
    def test_leave_one_group_out_detects_a_sign_flip(self):
        rows = [
            {"value": 10.0, "symbol": "BTC_USDT", "cluster": "b1"},
            {"value": -9.0, "symbol": "ENA_USDT", "cluster": "b1"},
            {"value": -8.0, "symbol": "ENA_USDT", "cluster": "b2"},
        ]
        stability = leave_one_out_stability(
            rows, value_key="value", group_key="symbol", cluster_key="cluster"
        )
        group_block = stability["leave_one_group_out"]
        self.assertTrue(group_block["sign_flips"])
        self.assertEqual(group_block["count"], 2)
        self.assertLess(group_block["minimum"], 0.0)
        self.assertGreater(group_block["maximum"], 0.0)

    def test_stable_metric_reports_no_flip(self):
        rows = [
            {"value": 10.0, "symbol": "BTC_USDT", "cluster": "b1"},
            {"value": 9.0, "symbol": "ENA_USDT", "cluster": "b1"},
            {"value": 8.0, "symbol": "ENA_USDT", "cluster": "b2"},
        ]
        stability = leave_one_out_stability(rows, value_key="value", group_key="symbol")
        self.assertFalse(stability["leave_one_group_out"]["sign_flips"])
        self.assertNotIn("leave_one_cluster_out", stability)

    def test_missing_group_value_is_rejected(self):
        with self.assertRaises(OrthogonalityError):
            leave_one_out_stability(
                [{"value": 1.0}, {"value": 2.0}], value_key="value", group_key="symbol"
            )


class ReportTests(unittest.TestCase):
    def test_report_is_descriptive_only(self):
        report = build_orthogonality_report(
            _rows(),
            feature="feature",
            baseline=["baseline"],
            target="target",
            redundancy_threshold=0.9,
            cluster="cluster",
            group_key="symbol",
            resamples=300,
        )
        self.assertIsNone(report["verdict"])
        self.assertTrue(report["verdict_requires_human_review"])
        self.assertFalse(any(report["claims"].values()))
        self.assertEqual(report["redundancy"]["threshold"], 0.9)
        self.assertIsNotNone(report["stability"])
        text = orthogonality_markdown(report)
        self.assertIn("Indicator orthogonality and incremental information", text)
        self.assertIn("Redundancy clusters", text)
        self.assertIn("Stability", text)

    def test_identical_feature_and_baseline_cluster_together(self):
        report = build_orthogonality_report(
            _rows(feature_copy=True),
            feature="feature",
            baseline=["baseline"],
            target="target",
            redundancy_threshold=0.99,
            resamples=200,
        )
        clusters = [sorted(members) for members in report["redundancy"]["clusters"]]
        self.assertIn(["baseline", "feature"], clusters)

    def test_determinism_and_self_hash(self):
        args = dict(
            feature="feature",
            baseline=["baseline"],
            target="target",
            redundancy_threshold=0.9,
            cluster="cluster",
            resamples=300,
        )
        first = build_orthogonality_report(_rows(), **args)
        second = build_orthogonality_report(_rows(), **args)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class LoaderTests(unittest.TestCase):
    def test_json_lines_and_array(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lines = root / "rows.jsonl"
            lines.write_text("\n".join(json.dumps(row) for row in _rows(5)) + "\n", encoding="utf-8")
            array = root / "rows.json"
            array.write_text(json.dumps(_rows(5)), encoding="utf-8")
            self.assertEqual(len(load_rows(lines)), 5)
            self.assertEqual(len(load_rows(array)), 5)

    def test_empty_and_broken_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.jsonl"
            empty.write_text("\n", encoding="utf-8")
            with self.assertRaises(OrthogonalityError):
                load_rows(empty)
            broken = root / "broken.jsonl"
            broken.write_text("{nope}\n", encoding="utf-8")
            with self.assertRaises(OrthogonalityError):
                load_rows(broken)
        with self.assertRaises(OrthogonalityError):
            load_rows(Path("does/not/exist.jsonl"))


class CliTests(unittest.TestCase):
    def test_cli_writes_report_and_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = root / "rows.jsonl"
            rows.write_text("\n".join(json.dumps(row) for row in _rows()) + "\n", encoding="utf-8")
            output = root / "orthogonality.json"
            markdown = root / "orthogonality.md"
            code = orthogonality_main(
                [
                    str(rows),
                    "--feature",
                    "feature",
                    "--baseline",
                    "baseline",
                    "--target",
                    "target",
                    "--redundancy-threshold",
                    "0.9",
                    "--cluster",
                    "cluster",
                    "--group-key",
                    "symbol",
                    "--resamples",
                    "300",
                    "--output",
                    str(output),
                    "--markdown",
                    str(markdown),
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["analysis"], "indicator_orthogonality_and_incremental_information")
            self.assertIn("Redundancy clusters", markdown.read_text(encoding="utf-8"))

    def test_cli_requires_the_caller_threshold(self):
        with self.assertRaises(SystemExit):
            orthogonality_main(["rows.jsonl", "--feature", "f", "--baseline", "b", "--target", "t"])

    def test_cli_reports_failure_for_a_bad_input(self):
        self.assertEqual(
            orthogonality_main(
                [
                    "missing.jsonl",
                    "--feature",
                    "f",
                    "--baseline",
                    "b",
                    "--target",
                    "t",
                    "--redundancy-threshold",
                    "0.9",
                ]
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()

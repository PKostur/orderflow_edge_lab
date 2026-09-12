from copy import deepcopy
import unittest

from experiments.multi_agent_trial.ablation import RealizedObservation, evaluate_ablation
from experiments.multi_agent_trial.engine import MarketSnapshot


def snapshot(snapshot_id, event_time, **overrides):
    data = dict(
        snapshot_id=snapshot_id,
        event_time=event_time,
        symbol="ENAUSDT",
        price=0.80,
        spread_bps=4.0,
        volume_z=2.0,
        orderflow_imbalance=0.35,
        htf_15m_bias=1,
        htf_1h_bias=1,
        btc_shock=0.001,
        expected_r_after_costs=0.25,
        stop_distance_pct=0.005,
        equity=1000.0,
        risk_fraction=0.005,
    )
    data.update(overrides)
    return MarketSnapshot(**data)


class AblationTests(unittest.TestCase):
    def observations(self):
        return [
            RealizedObservation(
                snapshot("s1", "2026-09-11T12:00:00+00:00"),
                "2026-09-11T12:05:00+00:00",
                1.0,
            ),
            RealizedObservation(
                snapshot("s2", "2026-09-11T12:10:00+00:00", btc_shock=-0.02),
                "2026-09-11T12:15:00+00:00",
                -1.0,
            ),
            RealizedObservation(
                snapshot("s3", "2026-09-11T12:20:00+00:00", volume_z=0.0, orderflow_imbalance=0.0),
                "2026-09-11T12:25:00+00:00",
                2.0,
            ),
        ]

    def test_baseline_scores_every_candidate_and_full_gate_keeps_rejected_outcomes_visible(self):
        report = evaluate_ablation(self.observations())
        baseline = next(item for item in report["variants"] if item["name"] == "baseline")
        full = next(item for item in report["variants"] if item["name"] == "full")
        self.assertEqual(baseline["accepted_count"], 3)
        self.assertEqual(baseline["rejected_count"], 0)
        self.assertAlmostEqual(baseline["accepted_summary"]["mean_r"], 2 / 3)
        self.assertEqual(full["accepted_count"], 1)
        self.assertEqual(full["rejected_count"], 2)
        self.assertEqual(full["accepted_summary"]["n"], 1)
        self.assertEqual(full["rejected_summary"]["n"], 2)
        self.assertAlmostEqual(full["rejected_summary"]["mean_r"], 0.5)
        self.assertIn("EINSTEIN", full["rejection_by_agent"])
        self.assertIn("PROBE", full["rejection_by_agent"])
        self.assertFalse(report["deployment_eligible"])
        self.assertFalse(report["verified_out_of_sample_evidence"])

    def test_outcome_change_changes_evidence_hash_but_not_agent_acceptance(self):
        original = self.observations()
        changed = deepcopy(original)
        changed[0] = RealizedObservation(changed[0].snapshot, changed[0].outcome_time, -3.0)
        a = evaluate_ablation(original)
        b = evaluate_ablation(changed)
        self.assertNotEqual(a["evidence_sha256"], b["evidence_sha256"])
        counts_a = [(x["name"], x["accepted_count"], x["rejected_count"]) for x in a["variants"]]
        counts_b = [(x["name"], x["accepted_count"], x["rejected_count"]) for x in b["variants"]]
        self.assertEqual(counts_a, counts_b)

    def test_duplicate_snapshot_ids_fail_closed(self):
        rows = self.observations()
        rows[1] = RealizedObservation(rows[0].snapshot, "2026-09-11T12:15:00+00:00", -1.0)
        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            evaluate_ablation(rows)

    def test_out_of_order_input_is_rejected_not_sorted(self):
        rows = self.observations()
        with self.assertRaisesRegex(ValueError, "never silently sorted"):
            evaluate_ablation([rows[1], rows[0]])

    def test_invalid_outcome_timing_and_nonfinite_result_fail_closed(self):
        row = self.observations()[0]
        with self.assertRaisesRegex(ValueError, "strictly after"):
            evaluate_ablation([RealizedObservation(row.snapshot, row.snapshot.event_time, 1.0)])
        with self.assertRaisesRegex(ValueError, "finite number"):
            evaluate_ablation([RealizedObservation(row.snapshot, row.outcome_time, float("nan"))])


if __name__ == "__main__":
    unittest.main()

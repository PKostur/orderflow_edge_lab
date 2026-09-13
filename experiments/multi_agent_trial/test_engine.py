import json
import tempfile
import unittest
from pathlib import Path

from experiments.multi_agent_trial.engine import MarketSnapshot, TrialCoordinator, append_ledger


def good_snapshot(**overrides):
    data = dict(
        snapshot_id="ENA-20260911T120000Z-001",
        event_time="2026-09-11T12:00:00+00:00",
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


class TrialEngineTests(unittest.TestCase):
    def test_good_snapshot_passes(self):
        result = TrialCoordinator().evaluate(good_snapshot())
        self.assertEqual(result.final_verdict, "PASS")
        self.assertEqual(len(result.snapshot_sha256), 64)
        self.assertTrue(all(d.verdict == "PASS" for d in result.decisions))

    def test_negative_expectancy_hard_vetoes(self):
        result = TrialCoordinator().evaluate(good_snapshot(expected_r_after_costs=-0.01))
        self.assertEqual(result.final_verdict, "REJECT")
        limit = next(d for d in result.decisions if d.agent == "LIMIT")
        self.assertTrue(limit.hard_veto)

    def test_adverse_btc_shock_vetoes(self):
        result = TrialCoordinator().evaluate(good_snapshot(btc_shock=-0.02))
        self.assertEqual(result.final_verdict, "REJECT")
        einstein = next(d for d in result.decisions if d.agent == "EINSTEIN")
        self.assertTrue(einstein.hard_veto)

    def test_wide_spread_vetoes(self):
        result = TrialCoordinator().evaluate(good_snapshot(spread_bps=25.0))
        self.assertEqual(result.final_verdict, "REJECT")

    def test_position_size_is_deterministic(self):
        result = TrialCoordinator().evaluate(good_snapshot())
        scale = next(d for d in result.decisions if d.agent == "SCALE")
        self.assertAlmostEqual(scale.metadata["risk_cash"], 5.0)
        self.assertAlmostEqual(scale.metadata["units"], 1250.0)

    def test_snapshot_hash_changes_when_evidence_changes(self):
        c = TrialCoordinator()
        a = c.evaluate(good_snapshot())
        b = c.evaluate(good_snapshot(volume_z=2.1))
        self.assertNotEqual(a.snapshot_sha256, b.snapshot_sha256)

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            TrialCoordinator().evaluate(good_snapshot(event_time="2026-09-11T12:00:00"))

    def test_ledger_contains_snapshot_and_structured_decisions(self):
        snap = good_snapshot()
        result = TrialCoordinator().evaluate(snap)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            append_ledger(path, snap, result)
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["result"]["snapshot_sha256"], result.snapshot_sha256)
        self.assertEqual(record["result"]["final_verdict"], "PASS")
        self.assertEqual(record["snapshot"]["snapshot_id"], snap.snapshot_id)


if __name__ == "__main__":
    unittest.main()

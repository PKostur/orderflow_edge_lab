from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.risk_ladder import RiskLadderError, evaluate_risk_ladder


class RiskLadderTests(unittest.TestCase):
    def _write_pair(self, observations):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "pair.json"
        payload = {
            "experiment": "paired_original_vs_reversed_execution",
            "source_sha256": "a" * 64,
            "streams": {
                "original": {"observations": observations},
                "reversed": {"observations": [{**row, "net_bps": -float(row["net_bps"])} for row in observations]},
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return path

    @staticmethod
    def _obs(signal_ms, exit_ms, net_bps, *, fee=4.0):
        return {
            "family": "book",
            "horizon_ms": 1000,
            "fee_bps_round_trip": fee,
            "signal_observed_at_ns": signal_ms * 1_000_000,
            "exit_observed_at_ns": exit_ms * 1_000_000,
            "net_bps": net_bps,
        }

    def test_incremental_exposure_scales_close_to_close_return(self):
        path = self._write_pair([
            self._obs(0, 1000, 10.0),
            self._obs(2000, 3000, -5.0),
        ])
        report = evaluate_risk_ladder(path, exposure_multiples=(1.0, 10.0), fee_bps_cases=(4.0,))
        original = [row for row in report["results"] if row["stream"] == "original"]
        one = next(row for row in original if row["exposure_multiple"] == 1.0)
        ten = next(row for row in original if row["exposure_multiple"] == 10.0)
        self.assertGreater(one["return_pct"], 0)
        self.assertGreater(ten["return_pct"], one["return_pct"])
        self.assertGreater(ten["max_realized_drawdown_pct"], one["max_realized_drawdown_pct"])
        self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_overlapping_signals_are_not_stacked(self):
        path = self._write_pair([
            self._obs(0, 2000, 10.0),
            self._obs(1000, 3000, 10.0),
            self._obs(3000, 4000, 10.0),
        ])
        report = evaluate_risk_ladder(path, exposure_multiples=(1.0,), fee_bps_cases=(4.0,))
        row = next(item for item in report["results"] if item["stream"] == "original")
        self.assertEqual(row["raw_observations"], 3)
        self.assertEqual(row["overlap_filtered_observations"], 2)
        self.assertEqual(row["trades"], 2)

    def test_close_to_close_ruin_is_flagged(self):
        path = self._write_pair([self._obs(0, 1000, -200.0)])
        report = evaluate_risk_ladder(path, exposure_multiples=(50.0,), fee_bps_cases=(4.0,))
        row = next(item for item in report["results"] if item["stream"] == "original")
        self.assertTrue(row["ruined_on_close_to_close_path"])
        self.assertEqual(row["ending_equity"], 0.0)

    def test_missing_fee_case_fails_closed(self):
        path = self._write_pair([self._obs(0, 1000, 10.0, fee=4.0)])
        with self.assertRaises(RiskLadderError):
            evaluate_risk_ladder(path, exposure_multiples=(1.0,), fee_bps_cases=(8.0,))


if __name__ == "__main__":
    unittest.main()

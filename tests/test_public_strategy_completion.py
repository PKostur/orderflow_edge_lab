import copy
import json
import unittest
from pathlib import Path

from orderflow_edge_lab.public_strategy_completion import audit_sessions, clock_counts
from orderflow_edge_lab.public_strategy_shadow import utc

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "artifacts/public_spot_8h_20261010"


class PublicCompletionTests(unittest.TestCase):
    def test_session_boundaries_and_nonexclusive_overlap_counts(self):
        result = clock_counts([utc(f"2026-01-01T{hour:02d}:00:00Z") for hour in (6, 7, 8, 9, 13, 16, 22)])
        self.assertEqual(result["nonexclusive_session_counts"], {"Asia": 3, "London": 4, "New_York": 2})
        self.assertEqual(result["exclusive_membership_counts"]["Asia+London"], 2)
        self.assertEqual(result["exclusive_membership_counts"]["London+New_York"], 1)
        self.assertEqual(result["exclusive_membership_counts"]["outside_declared_windows"], 1)
        self.assertEqual(sum(result["exclusive_membership_counts"].values()), 7)

    def test_retained_clocks_reconcile_without_changing_trades(self):
        spec = json.loads((ROOT / "config/public_strategy_shadow_v1.json").read_bytes())
        exact = json.loads((DATA / "exact_v1_report.json").read_bytes())
        original = json.loads((DATA / "diagnostics_final.json").read_bytes())
        result = audit_sessions(spec, exact, DATA / "aligned_csv")
        for row, baseline in zip(result["results"], original["results"], strict=True):
            opening = row["all_signal_candle_open_clock"]["utc_hour_counts"]
            completion = row["all_signal_completion_clock"]["utc_hour_counts"]
            self.assertEqual(completion, baseline["all_signal_utc_hour_counts_including_skipped"])
            self.assertTrue(all(opening[str(h)] == completion[str((h + 8) % 24)] for h in (0, 8, 16)))
            self.assertEqual(row["completed_hypothetical_entry_clock"]["n"], baseline["metrics"]["n"])
            self.assertEqual(row["all_signal_completion_clock"]["n"], baseline["signals"])
        self.assertEqual(result["new_trading_cells"], 0)
        self.assertFalse(result["deployment_eligible"])

    def test_changed_specification_cannot_be_called_retained_v1(self):
        spec = json.loads((ROOT / "config/public_strategy_shadow_v1.json").read_bytes())
        exact = json.loads((DATA / "exact_v1_report.json").read_bytes())
        changed = copy.deepcopy(spec)
        changed["experiments"][0]["hold_bars"] += 1
        with self.assertRaisesRegex(ValueError, "specification mismatch"):
            audit_sessions(changed, exact, DATA / "aligned_csv")

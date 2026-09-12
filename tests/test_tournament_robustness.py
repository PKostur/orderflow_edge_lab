from __future__ import annotations

import unittest

from orderflow_edge_lab.tournament_robustness import SymbolBreadthGate, apply_symbol_breadth_gate


def _symbol(symbol: str, expectancy: float, pf: float | str, trades: int = 20) -> dict:
    return {
        "symbol": symbol,
        "trades": trades,
        "expectancy_bps": expectancy,
        "profit_factor": pf,
    }


class TournamentRobustnessTests(unittest.TestCase):
    def test_breadth_gate_rejects_concentrated_screening_winner(self):
        symbols = [
            _symbol("A", 100.0, 2.0),
            _symbol("B", 80.0, 1.8),
            _symbol("C", 50.0, 1.4),
            _symbol("D", 10.0, 1.1),
            _symbol("E", -5.0, 0.9),
            _symbol("F", -10.0, 0.8),
            _symbol("G", -20.0, 0.7),
            _symbol("H", -30.0, 0.6),
            _symbol("I", -40.0, 0.5),
            _symbol("J", -50.0, 0.4),
        ]
        board = {"leaderboard": [{"screening_eligible": True, "per_symbol": symbols}], "claims": {}}
        out = apply_symbol_breadth_gate(board)
        row = out["leaderboard"][0]
        self.assertFalse(row["breadth_eligible"])
        self.assertFalse(row["robust_screening_eligible"])
        self.assertEqual(out["robust_eligible_count"], 0)
        self.assertEqual(row["symbol_breadth"]["positive_expectancy_symbol_fraction"], 0.4)
        self.assertIn("positive_expectancy_symbol_fraction 0.4", row["breadth_fail_reasons"])

    def test_breadth_gate_accepts_broad_development_screen_only(self):
        symbols = [
            _symbol("A", 60.0, 2.0),
            _symbol("B", 50.0, 1.8),
            _symbol("C", 40.0, 1.6),
            _symbol("D", 30.0, 1.4),
            _symbol("E", 20.0, 1.2),
            _symbol("F", 10.0, 1.1),
            _symbol("G", -5.0, 0.9),
            _symbol("H", -10.0, 0.8),
            _symbol("I", -15.0, 0.7),
            _symbol("J", -20.0, 0.6),
        ]
        board = {"leaderboard": [{"screening_eligible": True, "per_symbol": symbols}], "claims": {}}
        out = apply_symbol_breadth_gate(board)
        row = out["leaderboard"][0]
        self.assertTrue(row["breadth_eligible"])
        self.assertTrue(row["robust_screening_eligible"])
        self.assertEqual(out["robust_eligible_count"], 1)
        self.assertTrue(out["claims"]["historical_results_were_seen_before_symbol_breadth_filter"])
        self.assertFalse(out["claims"]["symbol_breadth_filter_is_final_oos"])

    def test_minimum_symbol_observations_fail_closed(self):
        symbols = [_symbol(str(index), 10.0, 1.2) for index in range(7)]
        board = {"leaderboard": [{"screening_eligible": True, "per_symbol": symbols}]}
        out = apply_symbol_breadth_gate(board, SymbolBreadthGate(minimum_symbol_observations=8))
        row = out["leaderboard"][0]
        self.assertFalse(row["robust_screening_eligible"])
        self.assertIn("expectancy_symbol_observations 7/8", row["breadth_fail_reasons"])
        self.assertIn("pf_symbol_observations 7/8", row["breadth_fail_reasons"])


if __name__ == "__main__":
    unittest.main()

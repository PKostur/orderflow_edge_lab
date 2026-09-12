from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import TournamentConfig, backtest, generate_target_position, rank_results, run_family_tournament


def _frame(rows: int = 500, *, trending: bool = True) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC")
    if trending:
        close = 100.0 + np.arange(rows) * 0.05 + np.sin(np.arange(rows) / 8.0)
    else:
        close = 100.0 + np.sin(np.arange(rows) / 4.0) * 2.0
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0}, index=index)


class StrategyTournamentTests(unittest.TestCase):
    def test_donchian_uses_prior_range_not_current_bar(self):
        frame = _frame(150, trending=False)
        lookback = 20
        target = generate_target_position(frame, "donchian_breakout", {"lookback": lookback})
        prior_high = frame["high"].rolling(lookback, min_periods=lookback).max().shift(1)
        prior_low = frame["low"].rolling(lookback, min_periods=lookback).min().shift(1)
        for idx in frame.index[lookback + 1 :]:
            if target.loc[idx] == 1:
                self.assertGreater(frame.loc[idx, "close"], prior_high.loc[idx])
            if target.loc[idx] == -1:
                self.assertLess(frame.loc[idx, "close"], prior_low.loc[idx])

    def test_higher_execution_cost_cannot_improve_same_backtest_return(self):
        frame = _frame(700, trending=True)
        params = {"fast": 10, "slow": 50, "min_atr_spread": 0.0}
        low_cost = backtest(frame, "ema_tsmom", params, 12.0)
        high_cost = backtest(frame, "ema_tsmom", params, 20.0)
        self.assertIsNotNone(low_cost["total_return"])
        self.assertIsNotNone(high_cost["total_return"])
        self.assertLessEqual(high_cost["total_return"], low_cost["total_return"] + 1e-12)

    def test_tournament_retains_every_cost_case_and_is_development_only(self):
        frames = {"BTCUSDT": _frame(1000), "ETHUSDT": _frame(1000)}
        cfg = TournamentConfig(
            start="2026-01-01",
            end="2026-02-01",
            fold_days=5,
            round_trip_cost_bps=(12.0, 16.0, 20.0),
        )
        report = run_family_tournament(frames, "donchian_breakout", {"lookback": [20, 40]}, cfg)
        self.assertEqual(report["trial_count"], 6)
        self.assertEqual({row["round_trip_cost_bps"] for row in report["results"]}, {12.0, 16.0, 20.0})
        self.assertTrue(report["claims"]["development_only"])
        self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_rank_gate_requires_repeated_cost_adjusted_evidence(self):
        good = {
            "experiment": "strategy_tournament_v1",
            "family": "good",
            "interval": "15m",
            "results": [
                {
                    "family": "good",
                    "parameters": {"x": 1},
                    "round_trip_cost_bps": 16.0,
                    "fold_observations": 8,
                    "positive_fold_fraction": 0.75,
                    "median_fold_expectancy_bps": 2.0,
                    "median_fold_profit_factor": 1.25,
                    "total_trades_across_folds": 120,
                }
            ],
        }
        bad = {
            "experiment": "strategy_tournament_v1",
            "family": "bad",
            "interval": "15m",
            "results": [
                {
                    "family": "bad",
                    "parameters": {"x": 1},
                    "round_trip_cost_bps": 16.0,
                    "fold_observations": 8,
                    "positive_fold_fraction": 0.50,
                    "median_fold_expectancy_bps": -0.5,
                    "median_fold_profit_factor": 0.95,
                    "total_trades_across_folds": 200,
                }
            ],
        }
        board = rank_results([bad, good], minimum_trades=80, minimum_folds=6)
        self.assertEqual(board["eligible_count"], 1)
        self.assertEqual(board["leaderboard"][0]["family"], "good")
        self.assertTrue(board["leaderboard"][0]["screening_eligible"])
        self.assertFalse(board["claims"]["profitable_edge_established"])


if __name__ == "__main__":
    unittest.main()

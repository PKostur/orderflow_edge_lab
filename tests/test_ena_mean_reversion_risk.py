from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from orderflow_edge_lab.ena_mean_reversion_risk import (
    RiskExperimentConfig,
    analyze_risk_experiment,
    simulate_overlay,
)


def _frame(rows: int = 80) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="1h", tz="UTC")
    close = 100.0 + np.sin(np.arange(rows) / 8.0)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=index,
    )


class EnaMeanReversionRiskTests(unittest.TestCase):
    def test_signal_executes_at_next_bar_open(self):
        frame = _frame()
        target = pd.Series(0.0, index=frame.index)
        target.iloc[20:22] = 1.0
        cfg = RiskExperimentConfig(round_trip_cost_bps=0.0)
        with patch(
            "orderflow_edge_lab.ena_mean_reversion_risk.generate_target_position",
            return_value=target,
        ):
            trades = simulate_overlay(frame, cfg, stop_atr_multiple=None)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry_time"], frame.index[21].isoformat())
        self.assertEqual(trades[0]["entry_price"], float(frame["open"].iloc[21]))
        self.assertEqual(trades[0]["exit_time"], frame.index[23].isoformat())

    def test_same_bar_stop_and_target_assumes_stop_first(self):
        frame = _frame()
        target = pd.Series(0.0, index=frame.index)
        target.iloc[20:24] = 1.0
        frame.iloc[21, frame.columns.get_loc("open")] = 100.0
        frame.iloc[21, frame.columns.get_loc("high")] = 110.0
        frame.iloc[21, frame.columns.get_loc("low")] = 90.0
        frame.iloc[21, frame.columns.get_loc("close")] = 100.0
        cfg = RiskExperimentConfig(round_trip_cost_bps=0.0)
        with patch(
            "orderflow_edge_lab.ena_mean_reversion_risk.generate_target_position",
            return_value=target,
        ):
            trades = simulate_overlay(
                frame,
                cfg,
                stop_atr_multiple=1.0,
                target_r_multiple=1.0,
            )
        self.assertGreaterEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "stop")
        self.assertLess(trades[0]["net_return"], 0.0)

    def test_risk_exit_does_not_reenter_same_signal_episode(self):
        frame = _frame()
        target = pd.Series(0.0, index=frame.index)
        target.iloc[20:30] = 1.0
        frame.iloc[21, frame.columns.get_loc("open")] = 100.0
        frame.iloc[21, frame.columns.get_loc("high")] = 101.0
        frame.iloc[21, frame.columns.get_loc("low")] = 80.0
        frame.iloc[21, frame.columns.get_loc("close")] = 99.0
        cfg = RiskExperimentConfig(round_trip_cost_bps=0.0)
        with patch(
            "orderflow_edge_lab.ena_mean_reversion_risk.generate_target_position",
            return_value=target,
        ):
            trades = simulate_overlay(frame, cfg, stop_atr_multiple=1.0)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "stop")

    def test_higher_cost_cannot_improve_same_trade_path(self):
        frame = _frame()
        target = pd.Series(0.0, index=frame.index)
        target.iloc[20:22] = 1.0
        low_cost = RiskExperimentConfig(round_trip_cost_bps=10.0)
        high_cost = replace(low_cost, round_trip_cost_bps=30.0)
        with patch(
            "orderflow_edge_lab.ena_mean_reversion_risk.generate_target_position",
            return_value=target,
        ):
            low = simulate_overlay(frame, low_cost, stop_atr_multiple=None)
            high = simulate_overlay(frame, high_cost, stop_atr_multiple=None)
        self.assertEqual(len(low), len(high))
        self.assertLess(high[0]["net_return"], low[0]["net_return"])

    def test_report_never_claims_oos_or_live(self):
        frame = _frame(800)
        cfg = RiskExperimentConfig(minimum_trades=1, minimum_folds=1)
        report = analyze_risk_experiment(frame, cfg)
        self.assertTrue(report["claims"]["development_only"])
        self.assertTrue(report["claims"]["historical_period_already_inspected"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["untouched_oos_completed"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])
        self.assertEqual(
            {row["stop_atr_multiple"] for row in report["variants"]},
            {1.0, 1.5, 2.0},
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.vol8_payoff_amplitude_forward import (
    _partition_trades,
    _pre_entry_volatility,
    _review_progress,
    _spearman,
    build_forward_report,
)


class Vol8PayoffAmplitudeForwardTests(unittest.TestCase):
    def _config(self) -> dict:
        return json.loads(
            Path("config/vol8_payoff_amplitude_forward_v1.json").read_text(
                encoding="utf-8"
            )
        )

    def _frame(self, periods: int = 400) -> pd.DataFrame:
        idx = pd.date_range("2026-06-01T00:00:00Z", periods=periods, freq="8h")
        t = np.arange(periods, dtype=float)
        ret = 0.003 * np.sin(t / 9.0) + 0.0015 * np.cos(t / 17.0)
        open_ = 100.0 * np.cumprod(1.0 + ret)
        close = open_ * (1.0 + 0.001 * np.sin(t / 5.0))
        high = np.maximum(open_, close) * (1.0 + 0.006)
        low = np.minimum(open_, close) * (1.0 - 0.006)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close},
            index=idx,
        )

    def test_volatility_percentile_is_causal(self):
        config = self._config()["causal_pre_entry_volatility"]
        frame = self._frame()
        entry = frame.index[300]
        original = _pre_entry_volatility(frame, entry, config)
        mutated = frame.copy()
        mutated.loc[entry:, "close"] *= 5.0
        mutated.loc[entry:, "high"] *= 5.0
        mutated.loc[entry:, "low"] *= 0.2
        changed = _pre_entry_volatility(mutated, entry, config)
        self.assertEqual(original, changed)
        self.assertIsNotNone(original["pre_entry_volatility_percentile"])
        self.assertIn(
            original["pre_entry_volatility_state"],
            {"LOW", "MID", "HIGH"},
        )

    def test_midrank_percentile_is_bounded(self):
        config = self._config()["causal_pre_entry_volatility"]
        frame = self._frame()
        row = _pre_entry_volatility(frame, frame.index[300], config)
        percentile = float(row["pre_entry_volatility_percentile"])
        self.assertGreaterEqual(percentile, 0.0)
        self.assertLessEqual(percentile, 1.0)
        self.assertGreaterEqual(
            row["volatility_rank_history_count"],
            config["minimum_rank_history"],
        )

    def test_trade_partition_excludes_pre_start_and_terminal_snapshot(self):
        start = pd.Timestamp("2026-09-26T00:00:00Z")
        trades = [
            {
                "entry": "2026-09-25T16:00:00+00:00",
                "terminal_liquidation": False,
            },
            {
                "entry": "2026-09-26T08:00:00+00:00",
                "terminal_liquidation": False,
            },
            {
                "entry": "2026-09-26T16:00:00+00:00",
                "terminal_liquidation": True,
            },
        ]
        completed, open_rows = _partition_trades(trades, start)
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(completed[0]["entry"], "2026-09-26T08:00:00+00:00")

    def test_spearman_recovers_monotonic_amplitude(self):
        rows = [
            {
                "pre_entry_volatility_percentile": value,
                "mfe_bps": value * 1000.0,
            }
            for value in (0.1, 0.3, 0.5, 0.7, 0.9)
        ]
        self.assertAlmostEqual(_spearman(rows, "mfe_bps"), 1.0, places=12)

    def test_review_gate_requires_all_frozen_requirements(self):
        config = self._config()
        start = pd.Timestamp(config["prospective_start_utc"])
        rows = [
            {
                "entry": (start + pd.Timedelta(hours=8 * i)).isoformat(),
                "symbol": config["source"]["symbols"][i % 6],
            }
            for i in range(60)
        ]
        progress = _review_progress(
            rows,
            start=start,
            as_of=start + pd.Timedelta(days=31),
            symbols=config["source"]["symbols"],
            distinct_blocks=4,
            config=config,
        )
        self.assertTrue(progress["ready_for_review"])
        self.assertEqual(progress["formal_output"], "READY_FOR_REVIEW")

    def test_pre_start_report_scores_zero_trades(self):
        config = self._config()
        frame = self._frame()
        frames = {symbol: frame for symbol in config["source"]["symbols"]}
        report = build_forward_report(
            config,
            frames,
            as_of_utc="2026-09-25T16:00:00Z",
        )
        self.assertEqual(report["status"], "PRE_START")
        self.assertEqual(report["completed_trade_count"], 0)
        self.assertEqual(report["open_post_start_snapshot_count"], 0)
        self.assertEqual(report["review_progress"]["formal_output"], "WITHHELD")
        self.assertFalse(report["claims"]["strategy_filter_authorized"])
        self.assertFalse(report["claims"]["live_trading_authorized"])


if __name__ == "__main__":
    unittest.main()

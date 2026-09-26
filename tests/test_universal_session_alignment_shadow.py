from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_session_alignment_shadow import build_shadow_report


class UniversalSessionAlignmentShadowTests(unittest.TestCase):
    def _config(self):
        return {
            "watch_id": "fixture-shadow",
            "prospective_start_utc": "2026-09-24T00:00:00Z",
            "source": {
                "symbols": ["BTC_USDT", "ETH_USDT"],
                "interval": "8h",
            },
            "economics": {
                "round_trip_cost_bps": 20.0,
                "canonical_accounting_version": 2,
                "max_abs_position": 1.0,
            },
            "variants": [
                {
                    "audit_id": "DON8",
                    "family": "donchian_breakout",
                    "parameters": {"lookback": 2},
                    "role": "FROZEN",
                }
            ],
            "shadow_labels": {
                "exclusive_session_regime": "fixture",
                "btc_prior_bar_direction": "fixture",
                "own_prior_3bar_direction": "fixture",
            },
            "frozen_hypotheses": [
                {
                    "hypothesis_id": "H1",
                    "applies_to": ["DON8"],
                    "factor": "btc_prior_bar_direction",
                    "aligned_state": "ALIGNED",
                    "comparison_state": "AGAINST",
                }
            ],
            "reporting": {
                "review_after_calendar_days": 30,
                "minimum_completed_trades_per_strategy": 20,
            },
            "claims": {
                "original_strategy_trades_unchanged": True,
                "labels_are_observational_only": True,
                "candidate_promoted": False,
                "session_filter_authorized": False,
                "live_trading_authorized": False,
                "leverage_authorized": False,
            },
        }

    def _frame(self, scale: float = 1.0) -> pd.DataFrame:
        index = pd.date_range("2026-08-01T00:00:00Z", periods=210, freq="8h")
        amplitude = np.arange(len(index), dtype=float) * 0.15
        close = (100.0 + np.where(np.arange(len(index)) % 2 == 0, amplitude, -amplitude)) * scale
        open_ = np.r_[close[0], close[:-1]]
        return pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.0005,
                "low": np.minimum(open_, close) * 0.9995,
                "close": close,
                "volume": 1000.0,
            },
            index=index,
        )

    def test_pre_start_has_no_scored_trades(self):
        frames = {"BTC_USDT": self._frame(), "ETH_USDT": self._frame(2.0)}
        result = build_shadow_report(
            self._config(),
            frames,
            as_of_utc="2026-09-23T20:00:00Z",
        )
        self.assertEqual(result["status"], "PRE_START")
        self.assertEqual(result["reports"][0]["summary"]["completed_trade_count"], 0)
        self.assertEqual(
            result["reports"][0]["evidence_progress"]["open_post_start_snapshot_count"],
            0,
        )
        self.assertEqual(
            result["reports"][0]["evidence_progress"]["completed_trade_progress_fraction"],
            0.0,
        )
        self.assertFalse(result["evidence_progress"]["all_strategies_ready"])
        self.assertTrue(result["claims"]["pre_start_entries_excluded_from_scoring"])

    def test_post_start_trades_are_labeled_without_gating(self):
        frames = {"BTC_USDT": self._frame(), "ETH_USDT": self._frame(2.0)}
        result = build_shadow_report(
            self._config(),
            frames,
            as_of_utc="2026-09-29T08:10:00Z",
        )
        report = result["reports"][0]
        self.assertEqual(result["status"], "ACCUMULATING")
        self.assertTrue(report["completed_trades"])
        for trade in report["completed_trades"]:
            self.assertGreaterEqual(
                pd.Timestamp(trade["entry_utc"]),
                pd.Timestamp("2026-09-24T00:00:00Z"),
            )
            self.assertIn(
                trade["btc_prior_bar_direction"],
                {"ALIGNED", "AGAINST", "NEUTRAL"},
            )
            self.assertIn(
                trade["own_prior_3bar_direction"],
                {"ALIGNED", "AGAINST", "NEUTRAL"},
            )
            self.assertTrue(trade["scored_completed_trade"])
            self.assertFalse(trade["terminal_liquidation"])
        for trade in report["open_terminal_snapshots_not_scored"]:
            self.assertFalse(trade["scored_completed_trade"])
            self.assertTrue(trade["terminal_liquidation"])
        self.assertEqual(
            report["summary"]["completed_trade_count"],
            len(report["completed_trades"]),
        )
        per_symbol = report["summary"]["per_observed_symbol_compounded_return"]
        expected_equal_weight = (
            sum(1.0 + per_symbol.get(symbol, 0.0) for symbol in self._config()["source"]["symbols"])
            / len(self._config()["source"]["symbols"])
            - 1.0
        )
        self.assertAlmostEqual(
            report["summary"]["equal_weight_symbol_sleeve_completed_trade_return"],
            expected_equal_weight,
            places=12,
        )
        curve = report["summary"]["equal_weight_symbol_sleeve_curve"]
        self.assertTrue(curve)
        self.assertAlmostEqual(
            curve[-1]["equal_weight_symbol_sleeve_return"],
            report["summary"]["equal_weight_symbol_sleeve_completed_trade_return"],
            places=12,
        )
        self.assertLessEqual(
            report["summary"]["equal_weight_symbol_sleeve_max_drawdown"],
            0.0,
        )
        self.assertEqual(
            curve[-1]["completed_trade_count_cumulative"],
            report["summary"]["completed_trade_count"],
        )
        self.assertNotIn("compounded_completed_trade_return", report["summary"])
        self.assertEqual(
            report["frozen_hypothesis_comparisons"][0]["formal_verdict"],
            "WITHHELD",
        )
        progress = report["evidence_progress"]
        self.assertEqual(progress["completed_trade_count"], len(report["completed_trades"]))
        self.assertEqual(
            progress["open_post_start_snapshot_count"],
            len(report["open_terminal_snapshots_not_scored"]),
        )
        self.assertGreater(progress["completed_observed_symbol_count"], 0)
        self.assertFalse(progress["ready_for_review"])
        sample_progress = report["hypothesis_sample_progress"][0]
        self.assertEqual(sample_progress["formal_verdict"], "WITHHELD")
        self.assertEqual(sample_progress["factor"], "btc_prior_bar_direction")
        self.assertIn("paired_observed_symbol_count", sample_progress)
        self.assertFalse(result["evidence_progress"]["all_strategies_ready"])
        self.assertTrue(result["claims"]["labels_do_not_gate_trade_generation"])


if __name__ == "__main__":
    unittest.main()

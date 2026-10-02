from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry_forward import (
    build_payoff_geometry_forward_report,
)


class _Strategy:
    warmup_bars = 100


class PayoffGeometryForwardTests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        idx = pd.date_range("2026-06-01T00:00:00Z", periods=360, freq="8h")
        t = np.arange(len(idx), dtype=float)
        open_ = 100.0 * np.cumprod(1.0 + 0.001 * np.sin(t / 5.0))
        close = open_ * (1.0 + 0.001 * np.cos(t / 7.0))
        high = np.maximum(open_, close) * 1.01
        low = np.minimum(open_, close) * 0.99
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close},
            index=idx,
        )

    def _config(self) -> dict:
        return {
            "watch_id": "payoff-geometry-forward-v1",
            "prospective_start_utc": "2026-09-25T16:00:00Z",
            "hypothesis_provenance": {"historical_evidence_only": True},
            "source": {
                "symbols": ["BTC_USDT"],
                "interval": "8h",
                "warmup_start_utc": "2026-06-01T00:00:00Z",
            },
            "economics": {
                "round_trip_cost_bps": 20.0,
                "maximum_absolute_position": 1.0,
            },
            "strategies": [
                {
                    "audit_id": "DON8",
                    "family": "donchian_breakout",
                    "parameters": {"lookback": 55},
                }
            ],
            "volatility_state": {
                "realized_window_bars": 20,
                "rank_history_bars": 90,
                "minimum_rank_history": 30,
            },
            "primary_hypotheses": [
                {
                    "hypothesis_id": "DON8_HIGH_VS_LOW_MEDIAN_MFE",
                    "strategy_id": "DON8",
                }
            ],
            "review_gate": {
                "minimum_calendar_days": 30,
                "minimum_completed_post_start_trades_per_strategy": 20,
                "minimum_completed_HIGH_trades_per_strategy": 8,
                "minimum_completed_LOW_trades_per_strategy": 8,
            },
        }

    def test_pre_start_scores_no_forward_trades(self):
        frame = self._frame()
        with patch(
            "orderflow_edge_lab.payoff_geometry_forward.legacy_strategy",
            return_value=_Strategy(),
        ), patch(
            "orderflow_edge_lab.payoff_geometry_forward.run_canonical_backtest",
            return_value={"trades_ledger": []},
        ):
            report = build_payoff_geometry_forward_report(
                self._config(),
                {"BTC_USDT": frame},
                as_of_utc="2026-09-25T15:59:59Z",
            )
        self.assertEqual(report["status"], "PRE_START")
        self.assertEqual(report["reports"][0]["summary"]["completed_trade_count"], 0)
        self.assertEqual(report["reports"][0]["formal_verdict"], "WITHHELD")

    def test_post_start_terminal_snapshot_is_not_completed(self):
        frame = self._frame()
        entry = pd.Timestamp("2026-09-26T00:00:00Z")
        exit_ = pd.Timestamp("2026-09-26T08:00:00Z")
        entry_price = float(frame.loc[entry, "open"])
        held = frame.loc[entry:entry]
        mfe = max(0.0, float(held["high"].max()) / entry_price - 1.0) * 10_000.0
        mae = min(0.0, float(held["low"].min()) / entry_price - 1.0) * 10_000.0
        trade = {
            "entry": entry.isoformat(),
            "exit": exit_.isoformat(),
            "side": 1,
            "bars_held": 1,
            "gross_bps": 10.0,
            "net_bps": -10.0,
            "mfe_bps": mfe,
            "mae_bps": mae,
            "terminal_liquidation": True,
        }
        with patch(
            "orderflow_edge_lab.payoff_geometry_forward.legacy_strategy",
            return_value=_Strategy(),
        ), patch(
            "orderflow_edge_lab.payoff_geometry_forward.run_canonical_backtest",
            return_value={"trades_ledger": [trade]},
        ):
            report = build_payoff_geometry_forward_report(
                self._config(),
                {"BTC_USDT": frame},
                as_of_utc="2026-09-26T12:00:00Z",
            )
        row = report["reports"][0]
        self.assertEqual(row["summary"]["completed_trade_count"], 0)
        self.assertEqual(row["sample_progress"]["open_terminal_snapshot_count"], 1)
        self.assertFalse(row["sample_progress"]["ready_for_review"])
        self.assertEqual(row["formal_verdict"], "WITHHELD")

    def test_review_gate_requires_time_total_high_and_low_counts(self):
        config = self._config()
        config["review_gate"] = {
            "minimum_calendar_days": 0,
            "minimum_completed_post_start_trades_per_strategy": 2,
            "minimum_completed_HIGH_trades_per_strategy": 1,
            "minimum_completed_LOW_trades_per_strategy": 1,
        }
        frame = self._frame()
        entries = [
            pd.Timestamp("2026-09-26T00:00:00Z"),
            pd.Timestamp("2026-09-27T00:00:00Z"),
        ]
        trades = []
        for entry in entries:
            exit_ = entry + pd.Timedelta(hours=8)
            price = float(frame.loc[entry, "open"])
            held = frame.loc[entry:entry]
            trades.append(
                {
                    "entry": entry.isoformat(),
                    "exit": exit_.isoformat(),
                    "side": 1,
                    "bars_held": 1,
                    "gross_bps": 20.0,
                    "net_bps": 0.0,
                    "mfe_bps": max(
                        0.0,
                        float(held["high"].max()) / price - 1.0,
                    )
                    * 10_000.0,
                    "mae_bps": min(
                        0.0,
                        float(held["low"].min()) / price - 1.0,
                    )
                    * 10_000.0,
                    "terminal_liquidation": False,
                }
            )
        states = iter(["HIGH", "LOW"])
        with patch(
            "orderflow_edge_lab.payoff_geometry_forward.legacy_strategy",
            return_value=_Strategy(),
        ), patch(
            "orderflow_edge_lab.payoff_geometry_forward.run_canonical_backtest",
            return_value={"trades_ledger": trades},
        ), patch(
            "orderflow_edge_lab.payoff_geometry._prior_volatility_state",
            side_effect=lambda *args, **kwargs: next(states),
        ):
            # enrich_trade_geometry resolves its own module function, so use a
            # deterministic replacement to isolate the gate semantics.
            with patch(
                "orderflow_edge_lab.payoff_geometry_forward.enrich_trade_geometry"
            ) as enrich:
                enrich.side_effect = [
                    {
                        **trades[0],
                        "symbol": "BTC_USDT",
                        "pre_entry_volatility_state": "HIGH",
                        "abs_mae_bps": abs(trades[0]["mae_bps"]),
                        "gross_to_mfe_ratio": 0.5,
                        "winner_gross_to_mfe_ratio": 0.5,
                        "time_to_mfe_hours": 0.0,
                    },
                    {
                        **trades[1],
                        "symbol": "BTC_USDT",
                        "pre_entry_volatility_state": "LOW",
                        "abs_mae_bps": abs(trades[1]["mae_bps"]),
                        "gross_to_mfe_ratio": 0.5,
                        "winner_gross_to_mfe_ratio": 0.5,
                        "time_to_mfe_hours": 0.0,
                    },
                ]
                report = build_payoff_geometry_forward_report(
                    config,
                    {"BTC_USDT": frame},
                    as_of_utc="2026-09-28T00:00:00Z",
                )
        self.assertEqual(report["status"], "READY_FOR_REVIEW")
        self.assertTrue(
            report["reports"][0]["sample_progress"]["ready_for_review"]
        )
        self.assertEqual(report["reports"][0]["formal_verdict"], "WITHHELD")
        self.assertFalse(report["claims"]["volatility_filter_authorized"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import (
    _bootstrap_ci,
    _bootstrap_samples,
    _cell_definitions,
    _summary,
    enrich_trade_geometry,
)


def _frame(periods: int = 260) -> pd.DataFrame:
    idx = pd.date_range("2025-12-01T00:00:00Z", periods=periods, freq="8h")
    t = np.arange(periods, dtype=float)
    returns = 0.0015 * np.sin(t / 6.0) + 0.0008 * np.cos(t / 15.0)
    open_ = 100.0 * np.cumprod(1.0 + returns)
    close = open_ * (1.0 + 0.001 * np.sin(t / 4.0))
    high = np.maximum(open_, close) * (1.0 + 0.006 + 0.002 * np.sin(t / 9.0) ** 2)
    low = np.minimum(open_, close) * (1.0 - 0.005 - 0.002 * np.cos(t / 11.0) ** 2)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=idx,
    )


def _config() -> dict:
    return json.loads(Path("config/payoff_geometry_v1.json").read_text(encoding="utf-8"))


class PayoffGeometryTests(unittest.TestCase):
    def test_geometry_emits_capture_time_and_causal_volatility_state(self):
        frame = _frame()
        entry = frame.index[180]
        exit_ = frame.index[186]
        held = frame.loc[entry:frame.index[185]]
        entry_price = float(frame.loc[entry, "open"])
        mfe = max(0.0, float(held["high"].max()) / entry_price - 1.0) * 10_000.0
        mae = min(0.0, float(held["low"].min()) / entry_price - 1.0) * 10_000.0
        trade = {
            "entry": entry.isoformat(),
            "exit": exit_.isoformat(),
            "side": 1,
            "bars_held": 6,
            "gross_bps": 35.0,
            "net_bps": 15.0,
            "mfe_bps": mfe,
            "mae_bps": mae,
            "terminal_liquidation": False,
        }
        row = enrich_trade_geometry(
            trade,
            frame,
            strategy_id="DON8",
            symbol="BTC_USDT",
            cost_bps=20.0,
            btc_frame=frame,
            volatility_config=_config()["pre_entry_volatility_state"],
        )
        self.assertEqual(row["outcome_label"], "CORRECT")
        self.assertEqual(row["side_label"], "LONG")
        self.assertIn(
            row["pre_entry_volatility_state"],
            {"LOW", "MID", "HIGH", "UNKNOWN"},
        )
        self.assertIsNotNone(row["gross_to_mfe_ratio"])
        self.assertIsNotNone(row["time_to_mfe_hours"])
        self.assertGreaterEqual(row["abs_mae_bps"], 0.0)

    def test_predeclared_cell_set_contains_outcome_side_volatility_and_empty_cells(self):
        cfg = _config()
        cells = _cell_definitions(cfg)
        names = [name for name, _ in cells]
        for expected in (
            "OUTCOME=CORRECT",
            "OUTCOME=INCORRECT",
            "SIDE=LONG",
            "SIDE=SHORT",
            "PRE_ENTRY_VOLATILITY=LOW",
            "PRE_ENTRY_VOLATILITY=MID",
            "PRE_ENTRY_VOLATILITY=HIGH",
            "PRE_ENTRY_VOLATILITY=UNKNOWN",
        ):
            self.assertIn(expected, names)
        self.assertTrue(cfg["cell_grid"]["emit_empty_cells"])
        one_row = {
            "outcome_label": "CORRECT",
            "side_label": "LONG",
            "pre_entry_volatility_state": "LOW",
            "session_regime": "ASIA",
            "btc_prior_bar_direction": "ALIGNED",
            "own_prior_3bar_direction": "ALIGNED",
        }
        empty = [name for name, predicate in cells if not predicate(one_row)]
        self.assertGreater(len(empty), 0)

    def test_summary_reports_requested_distribution_quantiles_and_capture_median(self):
        rows = [
            {
                "symbol": "BTC_USDT",
                "entry": f"2026-01-0{i+1}T00:00:00+00:00",
                "net_bps": float(i * 10 - 10),
                "gross_bps": float(i * 12 - 8),
                "mfe_bps": float(30 + i * 10),
                "abs_mae_bps": float(15 + i * 4),
                "gross_to_mfe_ratio": float((i * 12 - 8) / (30 + i * 10)),
                "winner_gross_to_mfe_ratio": (
                    float((i * 12 - 8) / (30 + i * 10)) if i >= 1 else None
                ),
                "time_to_mfe_hours": float(i * 8),
                "time_to_mae_hours": float((3 - i) * 8),
                "duration_hours": 32.0,
                "mfe_to_abs_mae_ratio": float((30 + i * 10) / (15 + i * 4)),
                "correct_direction": i >= 1,
            }
            for i in range(4)
        ]
        summary = _summary(rows, [0.10, 0.25, 0.50, 0.75, 0.90])
        self.assertIsNotNone(summary["median_gross_to_mfe_ratio"])
        for field in (
            "mfe_bps",
            "abs_mae_bps",
            "gross_to_mfe_ratio",
            "time_to_mfe_hours",
        ):
            self.assertEqual(
                set(summary["distributions"][field]),
                {"p10", "p25", "p50", "p75", "p90"},
            )

    def test_zero_mfe_does_not_report_fake_zero_hour_time(self):
        frame = _frame()
        entry = frame.index[180]
        exit_ = frame.index[183]
        frame.loc[entry:frame.index[182], "high"] = frame.loc[entry, "open"]
        entry_price = float(frame.loc[entry, "open"])
        frame.loc[entry:frame.index[182], "low"] = entry_price * 0.99
        trade = {
            "entry": entry.isoformat(),
            "exit": exit_.isoformat(),
            "side": 1,
            "bars_held": 3,
            "gross_bps": -50.0,
            "net_bps": -70.0,
            "mfe_bps": 0.0,
            "mae_bps": -100.0,
            "terminal_liquidation": False,
        }
        row = enrich_trade_geometry(
            trade,
            frame,
            strategy_id="DON8",
            symbol="BTC_USDT",
            cost_bps=20.0,
            btc_frame=frame,
            volatility_config=_config()["pre_entry_volatility_state"],
        )
        self.assertIsNone(row["time_to_mfe_hours"])
        self.assertIsNone(row["gross_to_mfe_ratio"])

    def test_cell_contract_is_complete_unique_and_reports_per_symbol_counts(self):
        cfg = _config()
        cells = _cell_definitions(cfg)
        names = [name for name, _ in cells]
        self.assertEqual(len(names), 71)
        self.assertEqual(len(names), len(set(names)))
        summary = _summary(
            [
                {
                    "symbol": "BTC_USDT",
                    "entry": "2026-01-01T00:00:00+00:00",
                    "net_bps": 10.0,
                    "gross_bps": 20.0,
                    "mfe_bps": 40.0,
                    "abs_mae_bps": 15.0,
                    "gross_to_mfe_ratio": 0.5,
                    "winner_gross_to_mfe_ratio": 0.5,
                    "time_to_mfe_hours": 8.0,
                    "time_to_mae_hours": 0.0,
                    "duration_hours": 24.0,
                    "mfe_to_abs_mae_ratio": 40.0 / 15.0,
                    "correct_direction": True,
                },
                {
                    "symbol": "ETH_USDT",
                    "entry": "2026-01-02T00:00:00+00:00",
                    "net_bps": -5.0,
                    "gross_bps": 5.0,
                    "mfe_bps": 30.0,
                    "abs_mae_bps": 20.0,
                    "gross_to_mfe_ratio": 1.0 / 6.0,
                    "winner_gross_to_mfe_ratio": 1.0 / 6.0,
                    "time_to_mfe_hours": 16.0,
                    "time_to_mae_hours": 8.0,
                    "duration_hours": 24.0,
                    "mfe_to_abs_mae_ratio": 1.5,
                    "correct_direction": True,
                },
            ],
            cfg["quantiles"],
        )
        self.assertEqual(
            summary["per_symbol_counts"],
            {"BTC_USDT": 1, "ETH_USDT": 1},
        )

    def test_shared_block_bootstrap_is_reproducible(self):
        rows = [
            {
                "_block_id": block,
                "net_bps": float((block + 1) * 10),
                "mfe_bps": float((block + 1) * 20),
                "abs_mae_bps": float((block + 1) * 5),
                "gross_to_mfe_ratio": 0.5,
                "winner_gross_to_mfe_ratio": 0.5,
                "time_to_mfe_hours": float(block * 8),
            }
            for block in range(4)
        ]
        fields = (
            "expectancy_bps",
            "win_rate",
            "median_mfe_bps",
            "median_abs_mae_bps",
            "median_gross_to_mfe_ratio",
            "median_winner_gross_to_mfe_ratio",
            "median_time_to_mfe_hours",
        )
        a = _bootstrap_samples([0, 1, 2, 3], replicates=25, seed=123)
        b = _bootstrap_samples([0, 1, 2, 3], replicates=25, seed=123)
        quantiles = _config()["quantiles"]
        ci_a = _bootstrap_ci(
            rows,
            quantiles,
            a,
            (0.025, 0.975),
            fields,
        )
        ci_b = _bootstrap_ci(
            rows,
            quantiles,
            b,
            (0.025, 0.975),
            fields,
        )
        self.assertEqual(ci_a, ci_b)
        self.assertEqual(ci_a["expectancy_bps"]["valid_replicates"], 25)

    def test_multiple_testing_is_reserved_for_later_decision_affecting_claims(self):
        cfg = _config()
        policy = cfg["multiplicity_policy"]
        self.assertTrue(policy["diagnostics_are_non_gating"])
        self.assertTrue(policy["cell_selection_after_results_prohibited"])
        reserved = " ".join(
            policy["decision_affecting_claims_require_later_correction"]
        )
        self.assertIn("Reality Check", reserved)
        self.assertIn("SPA", reserved)
        self.assertIn("Deflated Sharpe", reserved)
        self.assertIn("Backtest Overfitting", reserved)
        amendment = cfg["preregistration_amendment"]
        self.assertTrue(amendment["recorded_before_first_diagnostic_run"])
        self.assertFalse(amendment["results_observed_before_amendment"])


if __name__ == "__main__":
    unittest.main()

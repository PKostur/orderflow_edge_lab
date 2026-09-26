from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
from orderflow_edge_lab.short_convention_comparison import static_net_bps
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    FunctionStrategy,
    UniversalBacktestError,
    legacy_strategy,
    run_canonical_backtest,
)


def _frame(periods: int = 900, seed: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=periods, freq="8h")
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, periods)))
    open_ = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
        },
        index=idx,
    )


def _fixed(targets: list[float]) -> FunctionStrategy:
    def fn(frame: pd.DataFrame, params):
        del params
        return pd.Series(targets, index=frame.index[: len(targets)]).reindex(frame.index).fillna(0.0)

    return FunctionStrategy(strategy_id="fixed", target_fn=fn, warmup_bars=3)


class CanonicalV3Tests(unittest.TestCase):
    def test_version_and_ledger_reconciles_with_equity(self):
        report = run_canonical_backtest_v3(
            _frame(), legacy_strategy("donchian_breakout"), {"lookback": 20},
            ExecutionModel(round_trip_cost_bps=20.0),
        )
        self.assertEqual(report["accounting"]["version"], 3)
        self.assertEqual(report["accounting"]["position_model"], "fixed_quantity_between_target_changes")
        self.assertTrue(report["accounting"]["ledger_equity_reconciled"])
        self.assertGreater(report["trades"], 10)

    def test_unit_longs_identical_to_v2_and_unit_shorts_are_fixed_quantity(self):
        frame = _frame()
        strategy = legacy_strategy("donchian_breakout")
        execution = ExecutionModel(round_trip_cost_bps=20.0)
        v2 = run_canonical_backtest(frame, strategy, {"lookback": 20}, execution)["trades_ledger"]
        v3 = run_canonical_backtest_v3(frame, strategy, {"lookback": 20}, execution)["trades_ledger"]
        self.assertEqual([(t["entry"], t["exit"], t["side"]) for t in v2],
                         [(t["entry"], t["exit"], t["side"]) for t in v3])
        opens = frame["open"]
        shorts = 0
        for a, b in zip(v2, v3):
            self.assertAlmostEqual(a["mfe_bps"], b["mfe_bps"])
            self.assertAlmostEqual(a["mae_bps"], b["mae_bps"])
            if b["terminal_liquidation"]:
                continue
            if b["side"] > 0:
                self.assertAlmostEqual(a["net_bps"], b["net_bps"], places=6)
            else:
                shorts += 1
                static = -(opens[b["exit"]] / opens[b["entry"]] - 1.0) * 1e4
                self.assertAlmostEqual(b["gross_bps"], static, places=6)
                # Exit cost is charged on the notional actually closed (quantity x exit price).
                g = static / 1e4
                exit_weight = (opens[b["exit"]] / opens[b["entry"]]) / (1.0 + g)
                exact = ((1 - 0.001) * (1 + g) * (1 - 0.001 * exit_weight) - 1.0) * 1e4
                self.assertAlmostEqual(b["net_bps"], exact, places=6)
                self.assertAlmostEqual(b["net_bps"], static_net_bps(static, 20.0), delta=5.0)
        self.assertGreater(shorts, 0)

    def test_short_drift_charges_exit_on_drifted_weight(self):
        frame = _frame(8)
        frame["open"] = [100.0, 100.0, 80.0, 80.0, 80.0, 80.0, 80.0, 80.0]
        frame["high"] = frame[["open", "close"]].max(axis=1) * 1.01
        frame["low"] = frame[["open", "close"]].min(axis=1) * 0.99
        # target at bar 0 executes at bar 1 open (100); exits at bar 3 open (80).
        report = run_canonical_backtest_v3(
            frame, _fixed([-1.0, -1.0, 0.0]), {}, ExecutionModel(round_trip_cost_bps=20.0)
        )
        trade = report["trades_ledger"][0]
        self.assertAlmostEqual(trade["gross_bps"], 2000.0)
        # entry cost 0.001 on weight 1; exit weight has drifted to 0.8/1.2.
        c = 0.001
        equity = (1 - c) * 1.2 * (1 - c * (0.8 / 1.2))
        self.assertAlmostEqual(trade["net_bps"], (equity - 1.0) * 1e4)

    def test_resize_trades_only_the_target_change(self):
        frame = _frame(10)
        report = run_canonical_backtest_v3(
            frame, _fixed([0.5, 0.5, 1.0, 1.0]), {}, ExecutionModel(round_trip_cost_bps=20.0)
        )
        self.assertEqual(report["trades"], 1)
        self.assertTrue(report["accounting"]["ledger_equity_reconciled"])

    def test_bankruptcy_is_rejected(self):
        frame = _frame(8)
        frame["open"] = [100.0, 100.0, 250.0, 250.0, 250.0, 250.0, 250.0, 250.0]
        frame["high"] = frame[["open", "close"]].max(axis=1) * 1.01
        frame["low"] = frame[["open", "close"]].min(axis=1) * 0.99
        with self.assertRaises(UniversalBacktestError):
            run_canonical_backtest_v3(frame, _fixed([-1.0, -1.0, -1.0]), {}, ExecutionModel())


if __name__ == "__main__":
    unittest.main()

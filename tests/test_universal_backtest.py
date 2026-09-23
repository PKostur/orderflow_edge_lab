from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import backtest as legacy_backtest
from orderflow_edge_lab.universal_accounting_audit import audit_accounting
from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    FunctionStrategy,
    legacy_strategy,
    run_backtest,
    run_canonical_backtest,
    run_sweep,
)


def frame(rows=800):
    idx = pd.date_range("2025-01-01", periods=rows, freq="1h", tz="UTC")
    close = 100 + np.arange(rows) * 0.03 + np.sin(np.arange(rows) / 9)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + .2
    low = np.minimum(open_, close) - .2
    return pd.DataFrame({"open":open_,"high":high,"low":low,"close":close,"volume":1000.0}, index=idx)


class UniversalBacktestTests(unittest.TestCase):
    def test_legacy_adapter_matches_existing_engine_return(self):
        f=frame()
        params={"fast":10,"slow":50,"min_atr_spread":0.0}
        old=legacy_backtest(f,"ema_tsmom",params,16.0)
        new=run_backtest(f,legacy_strategy("ema_tsmom"),params,ExecutionModel(16.0))
        self.assertAlmostEqual(float(old["total_return"]),float(new["total_return"]),places=12)
        self.assertEqual(old["trades"],new["trades"])
        self.assertAlmostEqual(float(old["expectancy_bps"]),float(new["expectancy_bps"]),places=10)

    def test_signal_executes_next_bar(self):
        f=frame(150)
        target=pd.Series(0.0,index=f.index)
        target.iloc[100:]=1.0
        s=FunctionStrategy("fixture",lambda _f,_p: target,warmup_bars=1)
        r=run_backtest(f,s,{},ExecutionModel(0.0))
        self.assertTrue(r["claims"]["causal_next_bar_execution"])
        self.assertEqual(r["trades"],1)
        self.assertEqual(r["trades_ledger"][0]["entry"],f.index[101].isoformat())

    def test_cost_stress_cannot_improve_same_path(self):
        f=frame()
        s=legacy_strategy("donchian_breakout")
        lo=run_backtest(f,s,{"lookback":20},ExecutionModel(12.0))
        hi=run_backtest(f,s,{"lookback":20},ExecutionModel(20.0))
        self.assertLessEqual(float(hi["total_return"]),float(lo["total_return"])+1e-12)

    def test_sweep_retains_all_parameter_and_cost_cells(self):
        frames={"BTC":frame(),"ETH":frame()}
        r=run_sweep(frames,legacy_strategy("donchian_breakout"),{"lookback":[20,55]},[12.0,20.0])
        self.assertEqual(r["trial_count"],4)
        self.assertEqual({x["round_trip_cost_bps"] for x in r["results"]},{12.0,20.0})
        self.assertFalse(r["claims"]["profitable_edge_established"])

    def test_accounting_audit_reports_terminal_ledger_difference(self):
        f = frame(150)
        target = pd.Series(0.0, index=f.index)
        target.iloc[100:] = 1.0
        s = FunctionStrategy("fixture", lambda _f, _p: target, warmup_bars=1)
        r = audit_accounting(f, s, {}, ExecutionModel(20.0))
        self.assertEqual(r["status"], "accounting_mismatch")
        self.assertAlmostEqual(r["ledger_cost_delta_bps"], 10.0, places=12)
        self.assertAlmostEqual(r["terminal_position"], 1.0, places=12)
        self.assertIn("terminal_open_position_has_no_vectorized_exit_cost", r["issues"])

    def test_accounting_audit_detects_fractional_turnover(self):
        f = frame(150)
        target = pd.Series(0.0, index=f.index)
        target.iloc[100:] = 0.5
        s = FunctionStrategy("fractional", lambda _f, _p: target, warmup_bars=1)
        r = audit_accounting(f, s, {}, ExecutionModel(20.0))
        self.assertTrue(r["fractional_position_detected"])
        self.assertIn("fractional_position_ledger_cost_is_fixed_per_trade", r["issues"])

    def test_canonical_path_includes_terminal_liquidation(self):
        f = frame(150)
        target = pd.Series(0.0, index=f.index)
        target.iloc[100:] = 1.0
        s = FunctionStrategy("fixture", lambda _f, _p: target, warmup_bars=1)
        r = run_canonical_backtest(f, s, {}, ExecutionModel(20.0))
        self.assertTrue(r["claims"]["canonical_turnover_cost_accounting"])
        self.assertTrue(r["claims"]["terminal_liquidation_included"])
        self.assertAlmostEqual(r["accounting"]["terminal_liquidation_turnover_units"], 1.0, places=12)
        self.assertAlmostEqual(r["accounting"]["terminal_liquidation_cost_bps"], 10.0, places=12)
        self.assertAlmostEqual(r["turnover_units"], 2.0, places=12)
        self.assertEqual(r["trades"], 1)
        self.assertTrue(r["trades_ledger"][0]["terminal_liquidation"])

    def test_canonical_path_scales_fractional_turnover_cost(self):
        f = frame(150)
        target = pd.Series(0.0, index=f.index)
        target.iloc[100:] = 0.5
        s = FunctionStrategy("fractional", lambda _f, _p: target, warmup_bars=1)
        r = run_canonical_backtest(f, s, {}, ExecutionModel(20.0))
        self.assertAlmostEqual(r["accounting"]["terminal_liquidation_turnover_units"], 0.5, places=12)
        self.assertAlmostEqual(r["accounting"]["terminal_liquidation_cost_bps"], 5.0, places=12)
        self.assertAlmostEqual(r["turnover_units"], 1.0, places=12)
        self.assertAlmostEqual(r["trades_ledger"][0]["cost_bps"], 10.0, places=12)

    def test_canonical_reversal_reconciles_to_hand_calculated_equity(self):
        f = frame(5)
        f["open"] = [100., 100., 110., 99., 105.]
        target = pd.Series([1., -1., 0., 0., 0.], index=f.index)
        strategy = FunctionStrategy("reversal", lambda _f, _p: target, 1)
        result = run_canonical_backtest(f, strategy, {}, ExecutionModel(20.))
        # Two 10% winning episodes; each entry and exit costs 0.1%.
        expected = 1.1 ** 2 * .999 ** 4 - 1.0
        self.assertAlmostEqual(result["total_return"], expected, places=12)
        self.assertAlmostEqual(result["accounting"]["ledger_compounded_return"], expected, places=12)
        self.assertTrue(result["accounting"]["ledger_equity_reconciled"])

    def test_canonical_resizing_flat_and_terminal_paths_reconcile(self):
        f = frame(150)
        rng = np.random.default_rng(812)
        target = pd.Series(rng.choice([0., .25, .5, 1., -.25, -1.], len(f)), index=f.index)
        strategy = FunctionStrategy("resize", lambda _f, _p: target, 1)
        result = run_canonical_backtest(f, strategy, {}, ExecutionModel(20., 3.))
        reconstructed = np.prod([1 + t["net_bps"] / 10000 for t in result["trades_ledger"]]) - 1
        self.assertAlmostEqual(result["total_return"], reconstructed, places=12)
        self.assertAlmostEqual(sum(t["cost_bps"] for t in result["trades_ledger"]), result["turnover_units"] * 13., places=10)


if __name__=="__main__":
    unittest.main()

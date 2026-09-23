from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import backtest as legacy_backtest
from orderflow_edge_lab.universal_backtest import ExecutionModel, FunctionStrategy, legacy_strategy, run_backtest, run_sweep


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


if __name__=="__main__":
    unittest.main()

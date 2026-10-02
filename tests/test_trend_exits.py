from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.trend_exits import core_strategy, exit_overlay_target, with_channel_exit


def _frame(prices) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01T00:00Z", periods=len(prices), freq="8h")
    c = np.asarray(prices, dtype=float)
    return pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c}, index=idx)


class ChannelExitTests(unittest.TestCase):
    def test_exit_on_channel_break_and_no_reentry_without_event(self):
        prices = [100 + i for i in range(30)] + [120, 115, 110, 105, 100] + [101, 102, 103]
        f = _frame(prices)
        base = pd.Series(1.0, index=f.index)  # base stays long throughout
        long_ev = np.zeros(len(f), dtype=bool)
        long_ev[5] = True
        out = with_channel_exit(f, base, long_ev, np.zeros(len(f), dtype=bool), exit_window=5)
        self.assertEqual(out.iloc[5], 1.0)
        self.assertTrue((out.iloc[-3:] == 0.0).all())  # exited on the drop and not re-entered
        self.assertIn(0.0, out.iloc[30:35].tolist())

    def test_reentry_requires_fresh_event(self):
        f = _frame([100.0] * 20)
        base = pd.Series(1.0, index=f.index)
        ev = np.zeros(20, dtype=bool)
        ev[[2, 12]] = True
        out = with_channel_exit(f, base, ev, np.zeros(20, dtype=bool), exit_window=3)
        self.assertEqual(out.iloc[2], 1.0)
        self.assertEqual(out.iloc[12], 1.0)

    def test_overlay_never_trades_against_base(self):
        rng = np.random.default_rng(0)
        f = _frame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 800))))
        for fam, p in (("donchian_breakout", {"lookback": 55}), ("ema_tsmom", {"fast": 24, "slow": 96, "min_atr_spread": 0.25})):
            from orderflow_edge_lab.strategy_tournament import generate_target_position
            base = generate_target_position(f, fam, p).reindex(f.index).fillna(0.0)
            ov = exit_overlay_target(f, fam, p, 20)
            nz = ov != 0
            self.assertTrue((np.sign(ov[nz]) == np.sign(base[nz])).all())
            self.assertLessEqual(float((ov != 0).mean()), float((base != 0).mean()) + 1e-12)

    def test_core_without_exit_matches_frozen_average(self):
        rng = np.random.default_rng(1)
        f = _frame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600))))
        params = {"DON8": {"lookback": 55}, "EMA8": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}
        t = core_strategy(params, exit_window=None).generate_target(f, {}, None)
        self.assertTrue(set(np.round(t.unique(), 6)) <= {-1.0, -0.5, 0.0, 0.5, 1.0})


if __name__ == "__main__":
    unittest.main()

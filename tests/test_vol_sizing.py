from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_backtest import FunctionStrategy
from orderflow_edge_lab.vol_sizing import entry_sized_target, vol_sized_strategy


def _frame(vol: float, periods: int = 600, seed: int = 0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq="8h")
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, vol / np.sqrt(3 * 365), periods)))
    open_ = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001,
                         "low": np.minimum(open_, close) * 0.999, "close": close}, index=idx)


class VolSizingTests(unittest.TestCase):
    def test_size_scales_inversely_with_vol_and_is_capped(self):
        raw = pd.Series(1.0, index=_frame(0.8).index)
        hi = entry_sized_target(_frame(0.8), raw, window=180, target_vol=0.15, cap=1.0)
        lo = entry_sized_target(_frame(0.05), raw, window=180, target_vol=0.15, cap=1.0)
        self.assertAlmostEqual(float(hi.iloc[-1]), 0.15 / 0.8, delta=0.05)
        self.assertEqual(float(lo.iloc[-1]), 1.0)

    def test_size_is_fixed_within_an_episode_and_reset_on_new_episode(self):
        f = _frame(0.6)
        raw = pd.Series(0.0, index=f.index)
        raw.iloc[200:300] = 1.0
        raw.iloc[350:450] = -1.0
        sized = entry_sized_target(f, raw, window=180, target_vol=0.15, cap=1.0)
        self.assertEqual(sized.iloc[200:300].nunique(), 1)
        self.assertEqual(sized.iloc[350:450].nunique(), 1)
        self.assertTrue((sized.iloc[350:450] < 0).all())
        self.assertTrue((sized.iloc[300:350] == 0).all())

    def test_causal_size_uses_only_returns_up_to_the_signal_bar(self):
        f = _frame(0.6)
        raw = pd.Series(0.0, index=f.index)
        raw.iloc[250:] = 1.0
        a = entry_sized_target(f, raw, window=180, target_vol=0.15, cap=1.0)
        g = f.copy()
        g.iloc[251:, g.columns.get_loc("close")] *= 3.0  # future path changes
        b = entry_sized_target(g, raw, window=180, target_vol=0.15, cap=1.0)
        self.assertEqual(float(a.iloc[250]), float(b.iloc[250]))

    def test_insufficient_history_means_no_position(self):
        f = _frame(0.6)
        raw = pd.Series(1.0, index=f.index)
        sized = entry_sized_target(f, raw, window=180, target_vol=0.15, cap=1.0)
        self.assertTrue((sized.iloc[:180] == 0).all())

    def test_wrapper_keeps_signal_direction(self):
        f = _frame(0.6)
        base = FunctionStrategy(strategy_id="b", target_fn=lambda fr, p: pd.Series(
            np.where(np.arange(len(fr)) % 200 < 100, 1.0, -1.0), index=fr.index), warmup_bars=10)
        wrapped = vol_sized_strategy(base, window=180, target_vol=0.15, cap=1.0)
        t = wrapped.generate_target(f, {}, None)
        raw = base.generate_target(f, {}, None)
        nz = t != 0
        self.assertTrue((np.sign(t[nz]) == np.sign(raw[nz])).all())
        self.assertTrue((t.abs() <= 1.0).all())


if __name__ == "__main__":
    unittest.main()

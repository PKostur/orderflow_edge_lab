from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_zoo_v2 import highvol_breakout_targets, pairs_targets, us_session, zoo_v2_books


def _opens(n=400, k=12, seed=1):
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 0.03, n))
    cols = ["BTC_USDT"] + [f"C{i}_USDT" for i in range(k - 1)]
    data = {c: 100 * np.exp(common + np.cumsum(rng.normal(0, 0.01, n))) for c in cols}
    return pd.DataFrame(data, index=idx)


def _frames(opens):
    frames = {}
    for c in opens:
        idx = pd.date_range(opens.index[0], periods=3 * len(opens), freq="8h")
        o = np.repeat(opens[c].to_numpy(), 3) * (1 + 0.001 * np.tile([0, 1, -1], len(opens)))
        frames[c] = pd.DataFrame({"open": o, "high": o, "low": o, "close": o, "volume": np.ones(len(o))}, index=idx)
    return frames


class StrategyZooV2Tests(unittest.TestCase):
    def test_config_declared(self):
        cfg = json.loads(Path("config/strategy_zoo_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["status"], "DECLARED_BEFORE_EVALUATION")
        self.assertEqual(len(cfg["strategies"]), 5)

    def test_pairs_are_dollar_neutral_and_bounded(self):
        t = pairs_targets(_opens())
        self.assertLess(float(t.sum(axis=1).abs().max()), 1e-12)
        self.assertLessEqual(float(t.abs().sum(axis=1).max()), 1.0 + 1e-9)
        self.assertGreater(float(t.abs().sum().sum()), 0.0)

    def test_pairs_are_causal(self):
        o = _opens()
        f = o.copy()
        f.iloc[300:] *= np.linspace(1, 3, 100)[:, None] ** np.arange(o.shape[1])[None, :] ** 0.2
        pd.testing.assert_frame_equal(pairs_targets(o).iloc[:300], pairs_targets(f).iloc[:300])

    def test_breakout_needs_high_vol_and_is_causal(self):
        o = _opens()
        f = o.copy()
        f.iloc[300:] *= 2.0
        pd.testing.assert_frame_equal(highvol_breakout_targets(o).iloc[:300], highvol_breakout_targets(f).iloc[:300])
        self.assertLessEqual(float(highvol_breakout_targets(o).abs().sum(axis=1).max()), 1.0 + 1e-9)

    def test_us_session_holds_only_the_16utc_bar(self):
        o = _opens(n=30)
        net, gross = us_session(_frames(o), cost_bps=0.0)
        self.assertEqual(len(net), len(gross))
        pd.testing.assert_series_equal(net, gross)

    def test_books_run(self):
        o = _opens(n=260)
        books, gross = zoo_v2_books(_frames(o), pd.DataFrame(0.0, index=o.index, columns=o.columns))
        self.assertEqual(books.shape[1], 5)
        self.assertEqual(set(gross), {"Y2_us_session", "Y3_8h_reversal"})


if __name__ == "__main__":
    unittest.main()

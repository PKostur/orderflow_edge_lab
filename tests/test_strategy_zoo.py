from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_zoo import (
    btc_leadlag_targets,
    high_proximity_score,
    market_regimes,
    max_lottery_score,
    run_targets,
    volume_shock_score,
    weekend_targets,
    zoo_books,
)


def _opens(n=400, k=12, seed=0):
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(seed)
    cols = ["BTC_USDT"] + [f"C{i}_USDT" for i in range(k - 1)]
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (n, k)), axis=0)), index=idx, columns=cols)


def _frames(opens):
    frames = {}
    for c in opens:
        idx = pd.date_range(opens.index[0], periods=3 * len(opens), freq="8h")
        o = np.repeat(opens[c].to_numpy(), 3)
        frames[c] = pd.DataFrame({"open": o, "high": o, "low": o, "close": o, "volume": np.ones(len(o))}, index=idx)
    return frames


class StrategyZooTests(unittest.TestCase):
    def test_config_declared_before_evaluation(self):
        cfg = json.loads(Path("config/strategy_zoo_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["status"], "DECLARED_BEFORE_EVALUATION")
        self.assertEqual(len(cfg["strategies"]), 7)
        self.assertFalse(any(cfg["claims"].values()))

    def test_weekend_holds_only_fri_sat_sun(self):
        w = weekend_targets(_opens())
        held = w.sum(axis=1) > 0
        self.assertTrue(set(w.index[held].dayofweek) <= {4, 5, 6})
        self.assertAlmostEqual(float(w[held].sum(axis=1).max()), 1.0)

    def test_leadlag_uses_btc_return_known_at_the_open(self):
        o = _opens()
        o.iloc[10, 0] = o.iloc[9, 0] * 1.10  # BTC +10% into day 10
        t = btc_leadlag_targets(o)
        self.assertGreater(t.iloc[10].drop("BTC_USDT").sum(), 0.99)
        self.assertEqual(t["BTC_USDT"].abs().sum(), 0.0)

    def test_scores_are_causal(self):
        o = _opens()
        future = o.copy()
        future.iloc[300:] *= 3.0
        for fn in (max_lottery_score, high_proximity_score):
            pd.testing.assert_frame_equal(fn(o).iloc[:300], fn(future).iloc[:300])
        vol = pd.DataFrame(1.0, index=o.index, columns=o.columns)
        vfut = vol.copy()
        vfut.iloc[300:] = 50.0
        pd.testing.assert_frame_equal(volume_shock_score(vol, o.index).iloc[:301], volume_shock_score(vfut, o.index).iloc[:301])
        r1, r2 = market_regimes(o), market_regimes(future)
        pd.testing.assert_frame_equal(r1.iloc[:301], r2.iloc[:301])

    def test_run_targets_charges_turnover_and_funding(self):
        o = pd.DataFrame({"A": [100.0, 110.0, 110.0]}, index=pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"))
        t = pd.DataFrame({"A": [1.0, 0.0, 0.0]}, index=o.index)
        f = pd.DataFrame({"A": [0.001, 0.0, 0.0]}, index=o.index)
        r = run_targets(t, o, f, cost_bps=20)
        self.assertAlmostEqual(r.iloc[0], 0.10 - 0.001 - 0.001)
        self.assertAlmostEqual(r.iloc[1], -1.1 * 0.001)

    def test_zoo_books_run_end_to_end(self):
        o = _opens()
        books = zoo_books(_frames(o), pd.DataFrame(0.0, index=o.index, columns=o.columns))
        self.assertEqual(list(books.columns)[0], "Z1_weekend")
        self.assertEqual(books.shape[1], 7)
        self.assertTrue(np.isfinite(books.dropna(how="all").fillna(0).to_numpy()).all())

    def test_btc_context_is_signal_only_when_not_in_sample(self):
        o = _opens()
        fr = _frames(o)
        btc = fr.pop("BTC_USDT")
        books = zoo_books(fr, pd.DataFrame(0.0, index=o.index, columns=[c for c in o if c != "BTC_USDT"]), btc_frame=btc)
        self.assertEqual(books.shape[1], 7)
        with self.assertRaises(ValueError):
            zoo_books(fr, pd.DataFrame(0.0, index=o.index, columns=[c for c in o if c != "BTC_USDT"]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.fx_index import fx_xs_momentum_weights, rsi2_dip_weights, run_book, tsmom_weights


def _closes(n=600, k=8, seed=0, drift=0.0):
    idx = pd.bdate_range("2010-01-01", periods=n, tz="UTC")
    rng = np.random.default_rng(seed)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, (n, k)), axis=0)), index=idx, columns=[f"A{i}" for i in range(k)])


class FxIndexTests(unittest.TestCase):
    def test_config_declared(self):
        cfg = json.loads(Path("config/fx_index_prop_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["status"], "DECLARED_BEFORE_EVALUATION")
        self.assertEqual(len(cfg["universe"]["fx"]) + len(cfg["universe"]["indices"]), 20)

    def test_tsmom_follows_persistent_trend_and_is_causal(self):
        c = _closes(drift=0.002)
        w = tsmom_weights(c)
        self.assertGreater(float(w.iloc[-1].sum()), 0)
        future = c.copy()
        future.iloc[400:] *= 0.5
        pd.testing.assert_frame_equal(tsmom_weights(c).iloc[:400], tsmom_weights(future).iloc[:400])

    def test_book_applies_next_day_and_charges_costs(self):
        idx = pd.bdate_range("2020-01-06", periods=3, tz="UTC")
        c = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=idx)
        w = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, index=idx)
        r = run_book(w, c, cost_bps=0.0)
        self.assertAlmostEqual(r.iloc[1], 0.10)  # decided on day 0, earns day 1
        r2 = run_book(w, c, cost_bps=20.0, long_financing=0.0)
        self.assertAlmostEqual(r2.iloc[1], 0.10 - 0.001)  # entry turnover 1 x 10 bps

    def test_rsi_dip_and_xs_weights_are_bounded(self):
        c = _closes(seed=2)
        self.assertGreaterEqual(float(rsi2_dip_weights(c).min().min()), 0.0)
        x = fx_xs_momentum_weights(c)
        self.assertLess(abs(float((np.sign(x.iloc[-1])).sum())), 1e-9)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.news_sentiment_forward import build_report, n1_targets, n2_targets, n4_scale


def _idx(n=60):
    return pd.date_range("2026-11-02", periods=n, freq="D", tz="UTC")  # starts on a Monday


class NewsSentimentForwardTests(unittest.TestCase):
    def test_n1_uses_only_prior_days_and_is_neutral(self):
        idx = _idx(21)
        cols = [f"C{i}_USDT" for i in range(8)]
        m = pd.DataFrame(1.0, index=idx, columns=cols)
        s = pd.DataFrame(np.tile(np.arange(8.0), (21, 1)), index=idx, columns=cols)
        t = n1_targets(m, s)
        self.assertEqual(t.iloc[0].abs().sum(), 0.0)  # no prior week yet
        mon = t.loc[idx[7]]
        self.assertAlmostEqual(mon.sum(), 0.0)
        self.assertGreater(mon["C7_USDT"], 0)
        self.assertLess(mon["C0_USDT"], 0)
        s2 = s.copy()
        s2.iloc[7:] = -s2.iloc[7:]
        pd.testing.assert_series_equal(n1_targets(m, s2).loc[idx[7]], mon)  # day-7 items do not affect day-7 positions

    def test_n2_long_attention_hedged_by_basket(self):
        idx = _idx(60)
        cols = ["A_USDT", "B_USDT", "C_USDT"]
        m = pd.DataFrame(1.0, index=idx, columns=cols)
        s = pd.DataFrame(0.1, index=idx, columns=cols)
        m.iloc[50:53, 0] = 10.0
        opens = pd.DataFrame(100.0, index=idx, columns=cols)
        t = n2_targets(m, s, opens)
        self.assertAlmostEqual(t.iloc[53].sum(), 0.0, places=9)
        self.assertGreater(t.iloc[53]["A_USDT"], 0)
        self.assertEqual(t.iloc[40].abs().sum(), 0.0)

    def test_n4_scale_halves_only_in_panics(self):
        idx = _idx(80)
        mk = pd.Series(0.1 + 0.05 * np.sin(np.arange(80)), index=idx)
        mk.iloc[60] = 0.3
        mk.iloc[70:73] = -0.8
        sc = n4_scale(mk)
        self.assertEqual(sc.iloc[62], 1.0)
        self.assertEqual(sc.iloc[72], 0.5)

    def test_report_pre_start(self):
        cfg = json.loads(Path("config/news_sentiment_v1.json").read_text(encoding="utf-8"))
        bcfg = json.loads(Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))
        bcfg["symbols"] = bcfg["symbols"][:12]
        frames, funding = {}, {}
        for k, sym in enumerate(bcfg["symbols"]):
            ix = pd.date_range("2026-01-01T00:00Z", periods=800, freq="8h")
            c = 100 * np.exp(np.cumsum(np.random.default_rng(k).normal(0, 0.02, 800)))
            o = np.concatenate([[100.0], c[:-1]])
            frames[sym] = pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 1.0}, index=ix)
            funding[sym] = pd.Series(0.0, index=ix)
        daily = {"market": {"2026-09-30": {"score": 0.1, "items": 5}}, "coins": {"BTC": {"2026-09-30": {"mentions": 3, "score_sum": 0.5}}}}
        r = build_report(cfg, bcfg, daily, frames, funding, as_of="2026-10-02T00:00:00Z")
        self.assertEqual(r["status"], "PRE_START")
        self.assertIn("N4_blend_with_panic_pause", r["forward"])
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

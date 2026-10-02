from __future__ import annotations

import json
import math
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.trend_portfolio_forward import (
    build_report,
    causal_beta,
    hedged_returns,
    minimum_detectable_sharpe,
    newey_west_t,
)


def _config() -> dict:
    return json.loads(Path("config/universal_trend_portfolio_forward_v1.json").read_text(encoding="utf-8"))


def _frames(periods: int, seed: int = 5) -> dict[str, pd.DataFrame]:
    out = {}
    for k, symbol in enumerate(_config()["source"]["symbols"]):
        rng = np.random.default_rng(seed + k)
        idx = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq="8h")
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        out[symbol] = pd.DataFrame(
            {"open": open_, "high": np.maximum(open_, close) * 1.01,
             "low": np.minimum(open_, close) * 0.99, "close": close},
            index=idx,
        )
    return out


class TrendPortfolioTests(unittest.TestCase):
    def test_config_frozen_with_disclosed_anchor(self):
        cfg = _config()
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_PROSPECTIVE_START")
        self.assertEqual(cfg["prospective_start_utc"], "2026-09-28T00:00:00Z")
        self.assertIn("already inspected", cfg["historical_anchor"]["window"])
        self.assertTrue(all(not v for k, v in cfg["claims"].items() if k.endswith("_authorized")))

    def test_beta_is_causal(self):
        idx = pd.date_range("2026-01-01", periods=200, freq="D", tz="UTC")
        rng = np.random.default_rng(0)
        b = pd.Series(rng.normal(0, 0.02, 200), index=idx)
        p = 0.5 * b + pd.Series(rng.normal(0, 0.01, 200), index=idx)
        beta = causal_beta(p, b, window=90, minimum=60)
        changed = p.copy()
        changed.iloc[150:] = -3.0 * b.iloc[150:]
        beta2 = causal_beta(changed, b, window=90, minimum=60)
        # beta for day 150 is built from days < 150, so changing day 150 onward cannot move it
        self.assertEqual(beta.iloc[150], beta2.iloc[150])
        self.assertNotEqual(beta.iloc[151], beta2.iloc[151])
        self.assertEqual(beta.iloc[0], 0.0)
        self.assertAlmostEqual(float(beta.iloc[199]), 0.5, delta=0.15)

    def test_hedge_turnover_is_charged(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
        p = pd.Series([0.0, 0.0, 0.0], index=idx)
        b = pd.Series([0.0, 0.0, 0.0], index=idx)
        beta = pd.Series([0.0, 1.0, 1.0], index=idx)
        h = hedged_returns(p, b, beta, side_cost_bps=10.0)
        self.assertEqual(list(h), [0.0, -0.001, 0.0])

    def test_detectability_and_newey_west(self):
        self.assertAlmostEqual(minimum_detectable_sharpe(365), 2.0)
        self.assertAlmostEqual(minimum_detectable_sharpe(4 * 365), 1.0)
        self.assertIsNone(minimum_detectable_sharpe(0))
        rng = np.random.default_rng(1)
        x = pd.Series(rng.normal(0.001, 0.01, 2000))
        t = newey_west_t(x, 5)
        self.assertAlmostEqual(t, x.mean() / (x.std(ddof=0) / math.sqrt(len(x))), delta=0.6)

    def test_pre_start_then_collecting(self):
        frames = _frames(900)  # 2026-01-01 .. ~2026-10-26
        cfg = _config()
        pre = build_report(cfg, frames, as_of="2026-09-27T12:00:00Z")
        self.assertEqual(pre["status"], "PRE_START")
        self.assertEqual(pre["forward"]["plain"]["days"], 0)
        post = build_report(cfg, frames, as_of="2026-10-20T00:00:00Z")
        self.assertEqual(post["status"], "COLLECTING")
        days = post["forward"]["plain"]["days"]
        self.assertGreater(days, 15)
        first = min(post["daily_returns"]["plain"])
        # first scored return covers 2026-09-28 and is stamped at 2026-09-29 00:00
        self.assertEqual(first, "2026-09-29T00:00:00+00:00")
        self.assertIsNotNone(post["days_to_detect_anchor_sharpe"]["plain"])
        json.dumps(post, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

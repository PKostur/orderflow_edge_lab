from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.regime_switch import combine, regime_labels, regime_strategy


def _cfg() -> dict:
    return json.loads(Path("config/regime_switch_v1.json").read_text(encoding="utf-8"))


def _frame(n: int = 1400, seed: int = 0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01T00:00Z", periods=n, freq="8h")
    rng = np.random.default_rng(seed)
    # alternating trending and mean-reverting segments
    steps = rng.normal(0, 0.01, n)
    steps[:700] += 0.003
    close = 100 * np.exp(np.cumsum(steps))
    close[700:] = close[700] * np.exp(0.03 * np.sin(np.arange(n - 700) / 3.0))
    open_ = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.003,
                         "low": np.minimum(open_, close) * 0.997, "close": close}, index=idx)


class RegimeSwitchTests(unittest.TestCase):
    def test_labels_are_causal_and_warm_up_unknown(self):
        f = _frame()
        lab = regime_labels(f, _cfg()["regime"])
        self.assertTrue((lab.iloc[:580] == "UNKNOWN").all())
        g = f.copy()
        g.iloc[1000:, g.columns.get_loc("close")] *= 1.5
        self.assertTrue((regime_labels(g, _cfg()["regime"]).iloc[:1000] == lab.iloc[:1000]).all())

    def test_combine_routes_by_regime(self):
        idx = pd.RangeIndex(4)
        reg = pd.Series(["TREND", "MIXED", "CHOP", "UNKNOWN"], index=idx)
        trend = pd.Series([1.0, 1.0, 1.0, 1.0], index=idx)
        mr = pd.Series([-1.0, -1.0, -1.0, -1.0], index=idx)
        self.assertEqual(list(combine("switch", reg, trend, mr)), [1.0, 1.0, -1.0, 0.0])
        self.assertEqual(list(combine("chop_filter", reg, trend, mr)), [1.0, 1.0, 0.0, 0.0])
        self.assertEqual(list(combine("trend_only", reg, trend, mr)), [1.0, 1.0, 1.0, 0.0])
        self.assertEqual(list(combine("meanrev_only", reg, trend, mr)), [-1.0, -1.0, -1.0, 0.0])

    def test_strategy_generates_bounded_targets(self):
        f = _frame()
        for v in ("trend_only", "meanrev_only", "switch", "chop_filter"):
            t = regime_strategy(v, _cfg(), "crypto").generate_target(f, {}, None)
            self.assertTrue(t.abs().max() <= 1.0)
            self.assertEqual(len(t), len(f))

    def test_declared_before_evaluation(self):
        cfg = _cfg()
        self.assertEqual(cfg["status"], "DECLARED_BEFORE_EVALUATION")
        self.assertTrue(cfg["universes"]["etf"]["contaminated"])
        self.assertIn("textbook", cfg["components"]["mean_reversion"]["provenance"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_asset_trend_forward import build_report


def _config() -> dict:
    return json.loads(Path("config/universal_cross_asset_trend_forward_v1.json").read_text(encoding="utf-8"))


def _inputs(periods: int, rate: float) -> tuple[dict, dict]:
    cfg = _config()
    frames, funding = {}, {}
    symbols = [s for m in cfg["groups"].values() for s in m]
    for k, s in enumerate(symbols):
        rng = np.random.default_rng(20 + k)
        idx = pd.date_range("2026-02-01T00:00:00Z", periods=periods, freq="8h")
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0008, 0.02, periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        frames[s] = pd.DataFrame(
            {"open": open_, "high": np.maximum(open_, close) * 1.005,
             "low": np.minimum(open_, close) * 0.995, "close": close}, index=idx)
        funding[s] = pd.Series(rate, index=idx)
    return frames, funding


class CrossAssetTests(unittest.TestCase):
    def test_universe_is_the_mechanical_rule_result(self):
        cfg = _config()
        self.assertEqual(cfg["groups"]["tradfi"], cfg["universe_rule"]["result_on_2026-09-26"])
        self.assertEqual(cfg["prospective_start_utc"], "2026-09-28T00:00:00Z")
        self.assertTrue(all(not v for k, v in cfg["claims"].items() if k.endswith("_authorized")))

    def test_pre_start(self):
        frames, funding = _inputs(700, 0.0)
        r = build_report(_config(), frames, funding, as_of="2026-09-27T12:00:00Z")
        self.assertEqual(r["status"], "PRE_START")
        self.assertEqual(set(r["forward"]), {"combined", "crypto", "tradfi"})

    def test_positive_funding_hurts_a_mostly_long_trend_book(self):
        frames, zero = _inputs(900, 0.0)
        _, paid = _inputs(900, 0.0005)
        a = build_report(_config(), frames, zero, as_of="2026-10-20T00:00:00Z")
        b = build_report(_config(), frames, paid, as_of="2026-10-20T00:00:00Z")
        self.assertEqual(a["status"], "COLLECTING")
        self.assertAlmostEqual(a["funding_contribution"]["combined"]["annualized"], 0.0, places=12)
        self.assertLess(b["funding_contribution"]["combined"]["annualized"], 0.0)
        self.assertLess(b["forward"]["combined"]["mean_daily_bps"], a["forward"]["combined"]["mean_daily_bps"])
        json.dumps(b, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

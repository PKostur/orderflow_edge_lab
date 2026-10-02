from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_asset_trend_forward import build_report


def _cfg() -> dict:
    return json.loads(Path("config/crypto_trend_core_v1.json").read_text(encoding="utf-8"))


def _inputs(periods: int, rate: float = 0.0):
    frames, funding = {}, {}
    for k, s in enumerate(_cfg()["groups"]["crypto"]):
        rng = np.random.default_rng(90 + k)
        idx = pd.date_range("2026-05-01T00:00:00Z", periods=periods, freq="8h")
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0008, 0.03, periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        frames[s] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.01,
                                  "low": np.minimum(open_, close) * 0.99, "close": close}, index=idx)
        funding[s] = pd.Series(rate, index=idx)
    return frames, funding


class CryptoTrendCoreTests(unittest.TestCase):
    def test_frozen_design(self):
        cfg = _cfg()
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_PROSPECTIVE_START")
        self.assertEqual(cfg["prospective_start_utc"], "2026-09-29T00:00:00Z")
        self.assertEqual([s["audit_id"] for s in cfg["strategies"]], ["DON8", "EMA8"])
        self.assertEqual(len(cfg["groups"]["crypto"]), 17)
        self.assertEqual(cfg["sizing"]["method"], "entry_inverse_vol")
        self.assertIn("drop_VOL8", cfg["design_choices_disclosed"])
        self.assertTrue(all(not v for k, v in cfg["claims"].items() if k.endswith("_authorized")))

    def test_pre_start_and_collecting(self):
        frames, funding = _inputs(700)
        pre = build_report(_cfg(), frames, funding, as_of="2026-09-28T12:00:00Z")
        self.assertEqual(pre["status"], "PRE_START")
        post = build_report(_cfg(), frames, funding, as_of="2026-11-01T00:00:00Z")
        self.assertEqual(post["status"], "COLLECTING")
        self.assertEqual(min(post["daily_returns"]["crypto"]), "2026-09-30T00:00:00+00:00")
        self.assertTrue(post["forward"]["crypto"]["days"] > 20)
        json.dumps(post, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

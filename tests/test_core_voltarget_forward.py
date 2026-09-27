from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.core_voltarget_forward import build_report


def _cfg() -> dict:
    return json.loads(Path("config/crypto_trend_core_voltarget_v1.json").read_text(encoding="utf-8"))


def _inputs(periods: int):
    frames, funding = {}, {}
    for k, s in enumerate(_cfg()["groups"]["crypto"]):
        idx = pd.date_range("2026-05-01T00:00:00Z", periods=periods, freq="8h")
        c = 100 * np.exp(np.cumsum(np.random.default_rng(110 + k).normal(0.0008, 0.03, periods)))
        o = np.concatenate([[100.0], c[:-1]])
        frames[s] = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99,
                                  "close": c}, index=idx)
        funding[s] = pd.Series(0.0001, index=idx)
    return frames, funding


class CoreVolTargetTests(unittest.TestCase):
    def test_frozen_companion_of_core(self):
        cfg = _cfg()
        core = json.loads(Path("config/crypto_trend_core_v1.json").read_text(encoding="utf-8"))
        for k in ("groups", "strategies", "sizing", "economics", "prospective_start_utc"):
            self.assertEqual(cfg[k], core[k])
        self.assertEqual(cfg["portfolio_overlay"]["target_annual_vol"], 0.12)
        self.assertIn("target_choice_disclosed", cfg["portfolio_overlay"])

    def test_pre_start_then_collecting(self):
        frames, funding = _inputs(700)
        self.assertEqual(build_report(_cfg(), frames, funding, as_of="2026-09-28T12:00:00Z")["status"], "PRE_START")
        r = build_report(_cfg(), frames, funding, as_of="2026-11-01T00:00:00Z")
        self.assertEqual(r["status"], "COLLECTING")
        self.assertEqual(min(r["daily_returns"]["core"]), "2026-09-30T00:00:00+00:00")
        self.assertIsNotNone(r["overlay_state"]["latest_leverage"])
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

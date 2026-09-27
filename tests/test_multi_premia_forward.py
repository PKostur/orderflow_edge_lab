from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_forward import blend, build_report


def _cfg() -> dict:
    return json.loads(Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))


class MultiPremiaForwardTests(unittest.TestCase):
    def test_blend_weights_by_inverse_vol_and_is_causal(self):
        idx = pd.date_range("2026-01-05", periods=200, freq="D", tz="UTC")
        rng = np.random.default_rng(0)
        legs = pd.DataFrame({"A": rng.normal(0, 0.01, 200), "B": rng.normal(0, 0.03, 200)}, index=idx)
        b1 = blend(legs, vol_window=90, min_obs=60)
        legs2 = legs.copy()
        legs2.iloc[150:] *= 10
        b2 = blend(legs2, vol_window=90, min_obs=60)
        pd.testing.assert_series_equal(b1.iloc[:80], b2.iloc[:80])

    def test_pre_start_on_synthetic_data(self):
        cfg = _cfg()
        cfg["symbols"] = cfg["symbols"][:12]
        frames, funding = {}, {}
        for k, s in enumerate(cfg["symbols"]):
            idx = pd.date_range("2026-01-01T00:00Z", periods=800, freq="8h")
            c = 100 * np.exp(np.cumsum(np.random.default_rng(k).normal(0, 0.02, 800)))
            o = np.concatenate([[100.0], c[:-1]])
            frames[s] = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c}, index=idx)
            funding[s] = pd.Series(0.0001 * (k - 6), index=idx)
        r = build_report(cfg, frames, funding, as_of="2026-09-28T12:00:00Z")
        self.assertEqual(r["status"], "PRE_START")
        self.assertIn("S4_blend", r["forward"])
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

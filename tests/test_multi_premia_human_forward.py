from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_human_forward import build_report, truncate


def _inputs(n_syms: int = 12, periods: int = 800):
    cfg = json.loads(Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))
    cfg["symbols"] = cfg["symbols"][:n_syms]
    frames, funding = {}, {}
    for k, s in enumerate(cfg["symbols"]):
        idx = pd.date_range("2026-01-01T00:00Z", periods=periods, freq="8h")
        c = 100 * np.exp(np.cumsum(np.random.default_rng(k).normal(0, 0.02, periods)))
        o = np.concatenate([[100.0], c[:-1]])
        frames[s] = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c}, index=idx)
        funding[s] = pd.Series(0.0001 * (k - 6), index=idx)
    return cfg, frames, funding


class TruncateTests(unittest.TestCase):
    def test_keeps_k_largest_and_matches_full_gross_capped_at_one(self):
        a = pd.Series({"A": 0.3, "B": -0.2, "C": 0.05, "D": -0.01})
        t = truncate(a, 2)
        self.assertEqual(set(t[t != 0].index), {"A", "B"})
        self.assertAlmostEqual(t.abs().sum(), a.abs().sum())
        self.assertGreater(t["A"], 0)
        self.assertLess(t["B"], 0)
        big = pd.Series({"A": 0.9, "B": -0.8, "C": 0.5})
        self.assertAlmostEqual(truncate(big, 2).abs().sum(), 1.0)
        pd.testing.assert_series_equal(truncate(a, None), a)


class ReportTests(unittest.TestCase):
    def test_pre_start_and_json_safe(self):
        cfg, frames, funding = _inputs()
        r = build_report(cfg, frames, funding, as_of="2026-09-28T12:00:00Z")
        self.assertEqual(r["status"], "PRE_START")
        self.assertEqual(set(r["forward"]), {"V_ALL", "H5", "H10"})
        self.assertLessEqual(len(r["latest_book"]["H5"]["weights"]), 5)
        self.assertFalse(any(v for k, v in r["claims"].items() if k.endswith("_authorized")))
        json.dumps(r, allow_nan=False)

    def test_collecting_scores_only_post_start_days_and_is_causal(self):
        cfg, frames, funding = _inputs()
        cfg["prospective_start_utc"] = "2026-08-01T00:00:00Z"
        a = build_report(cfg, frames, funding, as_of="2026-09-20T00:00:00Z")
        self.assertEqual(a["status"], "COLLECTING")
        start = pd.Timestamp("2026-08-01T00:00:00Z")
        for series in a["daily_returns"].values():
            self.assertTrue(all(pd.Timestamp(t) > start for t in series))
        # future bars must not change past scored days
        b = build_report(cfg, frames, funding, as_of="2026-09-27T00:00:00Z")
        early = [t for t in a["daily_returns"]["H5"] if pd.Timestamp(t) <= pd.Timestamp("2026-09-18T00:00Z")]
        for t in early:
            self.assertAlmostEqual(a["daily_returns"]["H5"][t], b["daily_returns"]["H5"][t], places=12)


if __name__ == "__main__":
    unittest.main()
